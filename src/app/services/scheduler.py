import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.future import select

from ..models.database import async_session
from ..models.schema import SystemSettings, Profile, ProfileQuota, DailyUsage, AuditLog, Category
from .pihole import process_pihole_telemetry
from .unifi import UnifiClient

logger = logging.getLogger(__name__)

async def get_unifi_client(session) -> UnifiClient | None:
    result = await session.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()
    if not settings or not settings.unifi_host:
        return None

    return UnifiClient(
        host=settings.unifi_host,
        port=settings.unifi_port,
        username=settings.unifi_username,
        password=settings.unifi_password,
        site=settings.unifi_site
    )

async def check_quotas_and_enforce():
    """
    Evaluates current usage against quotas and curfews, and enforces blocks via UniFi.
    """
    async with async_session() as db:
        today_str = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().time()

        # 1. Fetch profiles and usages
        profiles_result = await db.execute(select(Profile))
        profiles = profiles_result.scalars().all()

        unifi = await get_unifi_client(db)
        if not unifi:
            logger.warning("UniFi client not configured, skipping enforcement")
            return

        unifi_logged_in = False

        for profile in profiles:
            # Check curfew
            curfew_active = False
            if profile.curfew_start and profile.curfew_end:
                if profile.curfew_start <= profile.curfew_end:
                    curfew_active = profile.curfew_start <= now <= profile.curfew_end
                else: # Curfew spans midnight
                    curfew_active = now >= profile.curfew_start or now <= profile.curfew_end

            if curfew_active:
                if not profile.is_blocked:
                    if not unifi_logged_in:
                        await unifi.login()
                        unifi_logged_in = True

                    logger.info(f"Enforcing curfew for {profile.name} via {profile.curfew_enforcement}")
                    success = False

                    if profile.audit_only:
                        logger.info(f"Audit mode: Skipping UniFi block for {profile.name}")
                        success = True
                    else:
                        if profile.curfew_enforcement == "station_block":
                            success = await unifi.block_station(profile.mac_address)
                        elif profile.curfew_enforcement == "traffic_rule":
                             success = await unifi.block_station(profile.mac_address)

                    if success:
                        profile.is_blocked = True
                        log = AuditLog(profile_id=profile.id, action="BLOCK", target="STATION", reason="Curfew started (Audit)" if profile.audit_only else "Curfew started")
                        db.add(log)
            else:
                # If curfew is over, we should unblock the station IF it was blocked by curfew
                if profile.is_blocked:
                    if not unifi_logged_in and not profile.audit_only:
                        await unifi.login()
                        unifi_logged_in = True

                    logger.info(f"Lifting curfew for {profile.name}")
                    success = True
                    if not profile.audit_only:
                        success = await unifi.unblock_station(profile.mac_address)
                        
                    if success:
                        profile.is_blocked = False
                        log = AuditLog(profile_id=profile.id, action="UNBLOCK", target="STATION", reason="Curfew ended")
                        db.add(log)

            # Check individual quotas
            quotas_result = await db.execute(select(ProfileQuota).where(ProfileQuota.profile_id == profile.id))
            quotas = quotas_result.scalars().all()

            for quota in quotas:
                usage_result = await db.execute(
                    select(DailyUsage)
                    .where(DailyUsage.profile_id == profile.id)
                    .where(DailyUsage.category_id == quota.category_id)
                    .where(DailyUsage.date == today_str)
                )
                usage = usage_result.scalars().first()

                if usage and usage.active_minutes >= quota.daily_limit_minutes and not usage.is_blocked:
                    # Time limit reached
                    if not unifi_logged_in and not profile.audit_only:
                        await unifi.login()
                        unifi_logged_in = True

                    logger.info(f"Profile {profile.name} reached quota for category ID {quota.category_id}")
                    success = False

                    if profile.audit_only:
                        logger.info(f"Audit mode: Skipping UniFi quota block for {profile.name}")
                        success = True
                    else:
                        if quota.enforcement == "traffic_rule" and quota.traffic_rule_id:
                            success = await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=True)
                        elif quota.enforcement == "station_block":
                            success = await unifi.block_station(profile.mac_address)
                            if success:
                                profile.is_blocked = True # Update global block state

                    if success:
                        usage.is_blocked = True
                        log = AuditLog(profile_id=profile.id, action="BLOCK", target=f"Category {quota.category_id}", reason="Quota exceeded")
                        db.add(log)

        if unifi_logged_in:
            await unifi.close()

        await db.commit()

async def midnight_reset():
    """
    Runs daily to reset all active blocks (traffic rules and station blocks).
    Usage records naturally reset because the date string changes.
    """
    async with async_session() as db:
        profiles_result = await db.execute(select(Profile))
        profiles = profiles_result.scalars().all()

        unifi = await get_unifi_client(db)
        if not unifi:
            return

        unifi_logged_in = False

        for profile in profiles:
            # Unblock station if it was globally blocked
            if profile.is_blocked:
                if not unifi_logged_in:
                    await unifi.login()
                    unifi_logged_in = True

                await unifi.unblock_station(profile.mac_address)
                profile.is_blocked = False
                db.add(AuditLog(profile_id=profile.id, action="RESET", target="STATION", reason="Midnight reset"))

            # Disable traffic rules for quotas
            quotas_result = await db.execute(select(ProfileQuota).where(ProfileQuota.profile_id == profile.id))
            quotas = quotas_result.scalars().all()

            for quota in quotas:
                if quota.enforcement == "traffic_rule" and quota.traffic_rule_id:
                    if not unifi_logged_in:
                        await unifi.login()
                        unifi_logged_in = True

                    await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=False)
                    db.add(AuditLog(profile_id=profile.id, action="RESET", target=f"Category {quota.category_id}", reason="Midnight reset"))

        if unifi_logged_in:
            await unifi.close()

        await db.commit()


async def background_task():
    """Main scheduler loop."""
    logger.info("Starting background scheduler...")

    # Store the last poll time, defaulting to 1 minute ago
    last_poll = datetime.now() - timedelta(minutes=1)

    while True:
        try:
            now = datetime.now()

            # 1. Process Pi-hole Telemetry
            start_epoch = int(last_poll.timestamp())
            end_epoch = int(now.timestamp())

            async with async_session() as db:
                await process_pihole_telemetry(db, start_epoch, end_epoch)

            last_poll = now

            # 2. Check Quotas & Enforce
            await check_quotas_and_enforce()

            # 3. Check for midnight reset (if we just crossed midnight)
            # A simple heuristic: if it's 00:00, run reset
            if now.hour == 0 and now.minute == 0:
                await midnight_reset()
                # Sleep a minute to avoid double triggering
                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Error in background scheduler: {e}")

        # Run every 30 seconds
        await asyncio.sleep(30)
