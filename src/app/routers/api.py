from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from datetime import datetime

from ..models.database import get_db
from ..models.schema import SystemSettings, Category, Profile, ProfileQuota, DailyUsage, AuditLog
from ..models.pydantic_schemas import (
    SettingsCreateUpdate, CategoryCreate, CategoryResponse,
    ProfileCreate, ProfileResponse, ProfileQuotaCreate, DashboardUsage, AuditLogResponse
)
from ..services.unifi import UnifiClient
from sqlalchemy.orm import selectinload

from ..models.auth import verify_credentials

router = APIRouter(prefix="/api", dependencies=[Depends(verify_credentials)])

# --- System Settings ---
@router.get("/settings", response_model=SettingsCreateUpdate)
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()
    if not settings:
        settings = SystemSettings()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings

@router.put("/settings", response_model=SettingsCreateUpdate)
async def update_settings(settings_in: SettingsCreateUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()
    if not settings:
        settings = SystemSettings(**settings_in.model_dump())
        db.add(settings)
    else:
        for k, v in settings_in.model_dump().items():
            setattr(settings, k, v)
    await db.commit()
    return settings

# --- Categories ---
@router.get("/categories", response_model=List[CategoryResponse])
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category))
    return result.scalars().all()

@router.post("/categories", response_model=CategoryResponse)
async def create_category(cat_in: CategoryCreate, db: AsyncSession = Depends(get_db)):
    cat = Category(**cat_in.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat

@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(cat)
    await db.commit()
    return {"status": "deleted"}

# --- Profiles ---
@router.get("/profiles", response_model=List[ProfileResponse])
async def get_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)))
    profiles = result.scalars().all()
    return list(profiles)

@router.post("/profiles", response_model=ProfileResponse)
async def create_profile(prof_in: ProfileCreate, db: AsyncSession = Depends(get_db)):
    prof = Profile(**prof_in.model_dump())
    db.add(prof)
    await db.commit()
    # Explicitly load relationships for response
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)).where(Profile.id == prof.id))
    prof_with_quotas = result.scalars().first()
    return prof_with_quotas

@router.put("/profiles/{prof_id}", response_model=ProfileResponse)
async def update_profile(prof_id: int, prof_in: ProfileCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(status_code=404, detail="Not found")
    
    for k, v in prof_in.model_dump().items():
        setattr(prof, k, v)
        
    await db.commit()
    return prof

@router.delete("/profiles/{prof_id}")
async def delete_profile(prof_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(prof)
    await db.commit()
    return {"status": "deleted"}

# --- Profile Quotas ---
@router.post("/profiles/{prof_id}/quotas", response_model=ProfileResponse)
async def add_quota(prof_id: int, quota_in: ProfileQuotaCreate, db: AsyncSession = Depends(get_db)):
    quota = ProfileQuota(profile_id=prof_id, **quota_in.model_dump())
    db.add(quota)
    await db.commit()
    # Return updated profile
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)).where(Profile.id == prof_id))
    prof = result.scalars().first()
    return prof

@router.put("/quotas/{quota_id}", response_model=ProfileResponse)
async def update_quota(quota_id: int, quota_in: ProfileQuotaCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProfileQuota).where(ProfileQuota.id == quota_id))
    quota = result.scalars().first()
    if not quota:
        raise HTTPException(status_code=404, detail="Not found")
    
    for k, v in quota_in.model_dump().items():
        setattr(quota, k, v)
        
    await db.commit()
    # Return updated profile
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)).where(Profile.id == quota.profile_id))
    prof = result.scalars().first()
    return prof

@router.delete("/quotas/{quota_id}")
async def delete_quota(quota_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProfileQuota).where(ProfileQuota.id == quota_id))
    quota = result.scalars().first()
    if not quota:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(quota)
    await db.commit()
    return {"status": "deleted"}

from pydantic import BaseModel
class QuotaToggle(BaseModel):
    enabled: bool

@router.post("/quotas/{quota_id}/toggle")
async def toggle_quota_rule(quota_id: int, payload: QuotaToggle, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProfileQuota).where(ProfileQuota.id == quota_id))
    quota = result.scalars().first()
    if not quota:
        raise HTTPException(status_code=404, detail="Quota not found")
    
    if not quota.traffic_rule_id:
        raise HTTPException(status_code=400, detail="No Traffic Rule ID configured for this limit.")
        
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    
    if not settings or not settings.unifi_host:
        raise HTTPException(status_code=400, detail="UniFi settings not configured.")
        
    from ..services.unifi import UnifiClient
    unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
    success = await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=payload.enabled)
    await unifi.close()
    
    if success:
        # Sync the block state to all DailyUsage records that share this traffic rule ID for today
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Find all quotas sharing this rule
        shared_quotas_result = await db.execute(select(ProfileQuota).where(ProfileQuota.traffic_rule_id == quota.traffic_rule_id))
        shared_quotas = shared_quotas_result.scalars().all()
        
        for sq in shared_quotas:
            # Update their daily usage for today
            usage_result = await db.execute(
                select(DailyUsage)
                .where(DailyUsage.profile_id == sq.profile_id)
                .where(DailyUsage.category_id == sq.category_id)
                .where(DailyUsage.date == today_str)
            )
            usage = usage_result.scalars().first()
            if usage:
                usage.is_blocked = payload.enabled
            else:
                # If usage doesn't exist yet, we create it to track the block state
                new_usage = DailyUsage(
                    profile_id=sq.profile_id,
                    category_id=sq.category_id,
                    date=today_str,
                    active_minutes=0,
                    is_blocked=payload.enabled
                )
                db.add(new_usage)
                
        await db.commit()
        return {"status": "success", "message": f"Rule turned {'ON (Blocked)' if payload.enabled else 'OFF (Unblocked)'}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to toggle UniFi traffic rule. Check Rule ID and connection.")

# --- Dashboard & Logs ---
@router.get("/dashboard", response_model=List[DashboardUsage])
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    today_str = datetime.now().strftime("%Y-%m-%d")

    # We need to join Profile, ProfileQuota, and DailyUsage to build the dashboard view
    profiles_result = await db.execute(select(Profile).options(selectinload(Profile.quotas)))
    profiles = profiles_result.scalars().all()

    categories_result = await db.execute(select(Category))
    categories = {c.id: c.name for c in categories_result.scalars().all()}

    dashboard_data = []

    for prof in profiles:
        for quota in prof.quotas:
            usage_result = await db.execute(
                select(DailyUsage)
                .where(DailyUsage.profile_id == prof.id)
                .where(DailyUsage.category_id == quota.category_id)
                .where(DailyUsage.date == today_str)
            )
            usage = usage_result.scalars().first()

            dashboard_data.append(DashboardUsage(
                profile_id=prof.id,
                profile_name=prof.name,
                profile_is_blocked=prof.is_blocked,
                category_id=quota.category_id,
                category_name=categories.get(quota.category_id, "Unknown"),
                active_minutes=usage.active_minutes if usage else 0,
                limit_minutes=quota.daily_limit_minutes,
                is_blocked=usage.is_blocked if usage else False
            ))

    return dashboard_data

@router.get("/logs", response_model=List[AuditLogResponse])
async def get_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit))
    return result.scalars().all()

@router.get("/usage/{profile_id}/{category_id}")
async def get_usage_charts(profile_id: int, category_id: int, db: AsyncSession = Depends(get_db)):
    from ..models.schema import HourlyUsage
    from datetime import timedelta
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # Intraday (Today)
    hourly_result = await db.execute(
        select(HourlyUsage)
        .where(HourlyUsage.profile_id == profile_id)
        .where(HourlyUsage.category_id == category_id)
        .where(HourlyUsage.date == today_str)
        .order_by(HourlyUsage.hour.asc())
    )
    hourly_records = hourly_result.scalars().all()
    today_hourly = {hr.hour: hr.active_minutes for hr in hourly_records}
    
    # Format intraday for 0-23
    intraday = [{"hour": h, "minutes": today_hourly.get(h, 0)} for h in range(24)]
    
    # Historical (Last 30 Days)
    daily_result = await db.execute(
        select(DailyUsage)
        .where(DailyUsage.profile_id == profile_id)
        .where(DailyUsage.category_id == category_id)
        .where(DailyUsage.date >= thirty_days_ago)
        .order_by(DailyUsage.date.asc())
    )
    daily_records = daily_result.scalars().all()
    
    # Build historical from the actual date range to ensure 0s for missing days
    historical = []
    for i in range(30):
        d = (datetime.now() - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        record = next((r for r in daily_records if r.date == d), None)
        historical.append({"date": d, "minutes": record.active_minutes if record else 0})
        
    return {"intraday": intraday, "historical": historical}

# --- Manual Overrides ---
@router.post("/overrides/unblock-station/{prof_id}")
async def manual_unblock_station(prof_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Update DB
    result = await db.execute(select(Profile).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(404, "Profile not found")

    prof.is_blocked = False
    log = AuditLog(profile_id=prof.id, action="UNBLOCK", target="STATION", reason="Manual Override")
    db.add(log)

    # 2. Update UniFi
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if settings and settings.unifi_host:
        unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
        await unifi.unblock_station(prof.mac_address)
        await unifi.close()

    await db.commit()
    return {"status": "success"}

@router.post("/overrides/block-station/{prof_id}")
async def manual_block_station(prof_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(404, "Profile not found")

    prof.is_blocked = True
    log = AuditLog(profile_id=prof.id, action="BLOCK", target="STATION", reason="Manual Override")
    db.add(log)

    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if settings and settings.unifi_host:
        unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
        await unifi.block_station(prof.mac_address)
        await unifi.close()

    await db.commit()
    return {"status": "success"}

@router.post("/overrides/reset-usage/{prof_id}/{cat_id}")
async def reset_usage(prof_id: int, cat_id: int, db: AsyncSession = Depends(get_db)):
    today_str = datetime.now().strftime("%Y-%m-%d")
    result = await db.execute(
        select(DailyUsage)
        .where(DailyUsage.profile_id == prof_id)
        .where(DailyUsage.category_id == cat_id)
        .where(DailyUsage.date == today_str)
    )
    usage = result.scalars().first()

    if usage:
        usage.active_minutes = 0
        usage.is_blocked = False
        db.add(AuditLog(profile_id=prof_id, action="RESET", target=f"Category {cat_id}", reason="Manual Override"))

        # Unblock in UniFi if it was a traffic rule
        quota_result = await db.execute(select(ProfileQuota).where(ProfileQuota.profile_id == prof_id).where(ProfileQuota.category_id == cat_id))
        quota = quota_result.scalars().first()

        if quota and quota.enforcement == "traffic_rule" and quota.traffic_rule_id:
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalars().first()
            if settings and settings.unifi_host:
                unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
                await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=False)
                await unifi.close()
                
                # Sync the unblock state to all other DailyUsage records sharing this rule
                shared_quotas_result = await db.execute(select(ProfileQuota).where(ProfileQuota.traffic_rule_id == quota.traffic_rule_id))
                shared_quotas = shared_quotas_result.scalars().all()
                for sq in shared_quotas:
                    if sq.profile_id != prof_id or sq.category_id != cat_id:
                        sq_usage_result = await db.execute(
                            select(DailyUsage)
                            .where(DailyUsage.profile_id == sq.profile_id)
                            .where(DailyUsage.category_id == sq.category_id)
                            .where(DailyUsage.date == today_str)
                        )
                        sq_usage = sq_usage_result.scalars().first()
                        if sq_usage:
                            sq_usage.is_blocked = False

        await db.commit()

    return {"status": "success"}

@router.post("/overrides/add-bonus/{prof_id}/{cat_id}/{minutes}")
async def add_bonus(prof_id: int, cat_id: int, minutes: int, db: AsyncSession = Depends(get_db)):
    today_str = datetime.now().strftime("%Y-%m-%d")
    result = await db.execute(
        select(DailyUsage)
        .where(DailyUsage.profile_id == prof_id)
        .where(DailyUsage.category_id == cat_id)
        .where(DailyUsage.date == today_str)
    )
    usage = result.scalars().first()

    if usage:
        usage.active_minutes = max(0, usage.active_minutes - minutes)
        
        # Determine if we need to unblock
        quota_result = await db.execute(
            select(ProfileQuota)
            .where(ProfileQuota.profile_id == prof_id)
            .where(ProfileQuota.category_id == cat_id)
        )
        quota = quota_result.scalars().first()
        
        if quota and usage.active_minutes < quota.daily_limit_minutes and usage.is_blocked:
            usage.is_blocked = False
            
            # Unblock in UniFi
            if quota.enforcement == "traffic_rule" and quota.traffic_rule_id:
                settings_result = await db.execute(select(SystemSettings).limit(1))
                settings = settings_result.scalars().first()
                if settings and settings.unifi_host:
                    unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
                    await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=False)
                    await unifi.close()
                    
                    # Sync the unblock state to all other DailyUsage records sharing this rule
                    shared_quotas_result = await db.execute(select(ProfileQuota).where(ProfileQuota.traffic_rule_id == quota.traffic_rule_id))
                    shared_quotas = shared_quotas_result.scalars().all()
                    for sq in shared_quotas:
                        if sq.profile_id != prof_id or sq.category_id != cat_id:
                            sq_usage_result = await db.execute(
                                select(DailyUsage)
                                .where(DailyUsage.profile_id == sq.profile_id)
                                .where(DailyUsage.category_id == sq.category_id)
                                .where(DailyUsage.date == today_str)
                            )
                            sq_usage = sq_usage_result.scalars().first()
                            if sq_usage:
                                sq_usage.is_blocked = False
            elif quota.enforcement == "station_block":
                # We need the profile MAC to unblock station
                prof_result = await db.execute(select(Profile).where(Profile.id == prof_id))
                prof = prof_result.scalars().first()
                if prof and prof.is_blocked:
                    prof.is_blocked = False
                    settings_result = await db.execute(select(SystemSettings).limit(1))
                    settings = settings_result.scalars().first()
                    if settings and settings.unifi_host:
                        unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
                        await unifi.unblock_station(prof.mac_address)
                        await unifi.close()

        db.add(AuditLog(profile_id=prof_id, action="BONUS", target=f"Category {cat_id}", reason=f"Added {minutes}m bonus"))
        await db.commit()

    return {"status": "success"}

# --- Connection Testing ---
@router.post("/test-connection/unifi")
async def test_unifi_connection(db: AsyncSession = Depends(get_db)):
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if not settings or not settings.unifi_host:
        raise HTTPException(status_code=400, detail="UniFi settings not configured")

    unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
    success = await unifi.login()
    await unifi.close()

    if success:
        return {"status": "success", "message": "Successfully connected to UniFi Controller"}
    else:
        raise HTTPException(status_code=400, detail="Failed to connect to UniFi Controller. Check credentials and host.")

@router.post("/test-connection/pihole")
async def test_pihole_connection(db: AsyncSession = Depends(get_db)):
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if not settings or not settings.pihole_url_1:
        raise HTTPException(status_code=400, detail="Pi-hole 1 URL not configured")

    import aiohttp
    import time
    from ..services.pihole import PiholeClient

    now = int(time.time())
    success_count = 0
    messages = []
    
    async with aiohttp.ClientSession() as session:
        pihole_client = PiholeClient(session)
        
        # Test Pi-hole 1
        if settings.pihole_url_1 and settings.pihole_api_key_1:
            try:
                # Test fetching 1 minute of queries to verify auth and connectivity
                res = await pihole_client.fetch_queries(settings.pihole_url_1, settings.pihole_api_key_1, now - 60, now)
                if isinstance(res, list):
                    success_count += 1
                    messages.append("Pi-hole 1: Connected")
                else:
                    messages.append("Pi-hole 1: Auth failed or invalid response")
            except Exception as e:
                messages.append(f"Pi-hole 1: Error ({str(e)})")
        
        # Test Pi-hole 2
        if settings.pihole_url_2 and settings.pihole_api_key_2:
            try:
                res = await pihole_client.fetch_queries(settings.pihole_url_2, settings.pihole_api_key_2, now - 60, now)
                if isinstance(res, list):
                    success_count += 1
                    messages.append("Pi-hole 2: Connected")
                else:
                    messages.append("Pi-hole 2: Auth failed or invalid response")
            except Exception as e:
                messages.append(f"Pi-hole 2: Error ({str(e)})")

    if success_count > 0:
        return {"status": "success", "message": " | ".join(messages)}
    else:
        raise HTTPException(status_code=400, detail=" | ".join(messages) if messages else "No Pi-holes configured with both URL and API Key")

@router.get("/unifi/rules")
async def get_unifi_rules(db: AsyncSession = Depends(get_db)):
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if not settings or not settings.unifi_host:
        raise HTTPException(status_code=400, detail="UniFi settings not configured")

    unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
    await unifi.login()
    rules = await unifi.get_traffic_rules()
    await unifi.close()

    return [{"id": r.get("_id") or r.get("id"), "description": r.get("description"), "enabled": r.get("enabled", False)} for r in rules]

@router.get("/unifi/clients")
async def get_unifi_clients(db: AsyncSession = Depends(get_db)):
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if not settings or not settings.unifi_host:
        raise HTTPException(status_code=400, detail="UniFi settings not configured")

    unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
    result = await unifi.get_clients()
    await unifi.close()

    clients_data = result.get("clients", [])
    errors = result.get("errors", [])

    if not clients_data and errors:
        raise HTTPException(status_code=400, detail=f"Failed to fetch clients. Errors: {', '.join(errors)}")

    processed_clients = []
    for c in clients_data:
        ip = c.get("fixed_ip") or c.get("ip") or c.get("last_ip") or "Unknown"
        name = c.get("name") or c.get("hostname") or c.get("mac")
        if not name:
            continue
            
        processed_clients.append({
            "mac": c.get("mac", ""),
            "ip": ip,
            "name": name
        })
        
    processed_clients.sort(key=lambda x: (x.get("name") or "").lower())
    return processed_clients

@router.get("/version")
async def get_version():
    return {"version": "v1.0.1"}

@router.post("/database/wipe-usage")
async def wipe_usage_history(db: AsyncSession = Depends(get_db)):
    """Wipes all historical usage data from the daily_usage table."""
    from sqlalchemy import delete
    try:
        await db.execute(delete(DailyUsage))
        db.add(AuditLog(profile_id=0, action="WIPE", target="Database", reason="Manual Wipe All Usage History"))
        await db.commit()
        return {"status": "success", "message": "Successfully wiped all usage history."}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to wipe database: {str(e)}")
