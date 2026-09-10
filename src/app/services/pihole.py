import aiohttp
import asyncio
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PiholeClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def fetch_queries(self, base_url: str, api_key: str, from_epoch: int, until_epoch: int) -> list:
        """
        Fetches queries from the Pi-hole API between two epoch timestamps.
        Supports both Pi-hole v5 (token) and Pi-hole v6 (App Password session).
        """
        if not base_url or not api_key:
            return []

        base_url = base_url.rstrip('/')
        v6_auth_url = f"{base_url}/api/auth"
        
        headers = {}
        # 1. Try Pi-hole v6 Authentication
        try:
            async with self.session.post(v6_auth_url, json={"password": api_key}, timeout=5) as response:
                if response.status == 200:
                    auth_data = await response.json()
                    sid = auth_data.get("session", {}).get("sid")
                    if sid:
                        headers["sid"] = sid
                        
                        try:
                            # Fetch v6 queries
                            v6_queries_url = f"{base_url}/api/queries"
                            params = {"from": from_epoch, "until": until_epoch}
                            async with self.session.get(v6_queries_url, params=params, headers=headers, timeout=10) as q_resp:
                                if q_resp.status == 200:
                                    data = await q_resp.json()
                                    # v6 returns a dict with 'queries' array of objects
                                    queries = data.get("queries", [])
                                    formatted_queries = []
                                    for q in queries:
                                        if isinstance(q, dict):
                                            # Pi-hole v6 client is a dict {"ip": "...", "name": "..."}
                                            client_obj = q.get("client")
                                            client_ip = client_obj.get("ip") if isinstance(client_obj, dict) else str(client_obj)
                                            # Format: [timestamp, type, domain, client]
                                            formatted_queries.append([
                                                q.get("time"), q.get("type"), q.get("domain"), client_ip
                                            ])
                                    return formatted_queries
                                else:
                                    logger.error(f"v6 API fetched failed: {q_resp.status}")
                                    return None
                        finally:
                            # Always delete the session to prevent "API seats exceeded" errors in Pi-hole v6
                            try:
                                async with self.session.delete(v6_auth_url, headers=headers, timeout=3):
                                    pass
                            except Exception as e:
                                logger.error(f"Failed to cleanly logout of Pi-hole v6: {e}")
                elif response.status == 401:
                    logger.error(f"Pi-hole v6 authentication failed for {base_url}. Is the App Password correct?")
                    return None
        except Exception as e:
            # Not v6, or v6 is disabled/unreachable, fall back to v5
            pass

        # 2. Fall back to Pi-hole v5
        url = f"{base_url}/admin/api.php"
        params = {
            "getAllQueries": 1,
            "from": from_epoch,
            "until": until_epoch,
            "auth": api_key
        }

        try:
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    # v5 returns dict with 'data' array of arrays
                    return data.get("data", [])
                elif response.status == 400:
                    logger.error(f"Failed to fetch v5 queries from {base_url}. Status 400. (If this is Pi-hole v6, your App Password is wrong).")
                    return None
                else:
                    logger.error(f"Failed to fetch queries from {base_url}. Status: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Exception while fetching queries from {base_url}: {e}")
            return None

async def process_pihole_telemetry(db_session, start_epoch: int, end_epoch: int):
    """
    Polls configured Pi-holes and calculates active usage minutes for each profile.
    """
    from ..models.schema import SystemSettings, Profile, Category, ProfileQuota, DailyUsage
    from sqlalchemy.future import select

    # 1. Fetch system settings
    result = await db_session.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()

    if not settings:
        return

    # 2. Fetch active profiles and their configured categories/quotas
    profiles_result = await db_session.execute(select(Profile))
    profiles = profiles_result.scalars().all()

    categories_result = await db_session.execute(select(Category))
    categories = categories_result.scalars().all()

    if not profiles or not categories:
        return

    # Create mappings for quick lookup
    # ip_to_profile maps IP address to profile object
    ip_to_profile = {p.ip_address: p for p in profiles if p.ip_address}

    # domain_to_category maps domain strings to category IDs
    domain_to_category = {}
    for cat in categories:
        if cat.domains:
            domains = [d.strip() for d in cat.domains.split(",")]
            for d in domains:
                domain_to_category[d] = cat.id

    # 3. Poll Pi-holes
    all_queries = []
    async with aiohttp.ClientSession() as session:
        pihole_client = PiholeClient(session)

        # Poll Pi-hole 1
        if settings.pihole_url_1 and settings.pihole_api_key_1:
            q1 = await pihole_client.fetch_queries(settings.pihole_url_1, settings.pihole_api_key_1, start_epoch, end_epoch)
            if q1 is not None:
                all_queries.extend(q1)

        # Poll Pi-hole 2
        if settings.pihole_url_2 and settings.pihole_api_key_2:
            q2 = await pihole_client.fetch_queries(settings.pihole_url_2, settings.pihole_api_key_2, start_epoch, end_epoch)
            if q2 is not None:
                all_queries.extend(q2)

    if not all_queries:
        return

    # 4. Process queries & count distinct active minutes
    # Data structure to hold active minutes:
    # { profile_id: { category_id: set(minute_epochs) } }
    active_minutes_tracker = {}

    for query in all_queries:
        if len(query) < 4:
            continue

        try:
            timestamp = int(query[0])
            domain = query[2]
            client_ip = query[3]
        except (ValueError, TypeError):
            continue

        # Check if the query is from a managed profile
        profile = ip_to_profile.get(client_ip)
        if not profile:
            continue

        # Try exact domain match first
        matched_cat_id = domain_to_category.get(domain)

        # If no exact match, try partial match (e.g. if category domain is 'youtube.com' and query is 'r1.sn-xxx.googlevideo.com')
        # This is a basic wildcard match
        if not matched_cat_id:
            for cat_domain, cat_id in domain_to_category.items():
                if domain.endswith(f".{cat_domain}") or domain == cat_domain:
                    matched_cat_id = cat_id
                    break

        if matched_cat_id:
            minute_epoch = timestamp // 60

            if profile.id not in active_minutes_tracker:
                active_minutes_tracker[profile.id] = {}
            if matched_cat_id not in active_minutes_tracker[profile.id]:
                active_minutes_tracker[profile.id][matched_cat_id] = set()

            active_minutes_tracker[profile.id][matched_cat_id].add(minute_epoch)

    # 5. Update DailyUsage in database
    today_str = datetime.now().strftime("%Y-%m-%d") # Use current date for usage

    for profile_id, category_tracker in active_minutes_tracker.items():
        for category_id, minutes_set in category_tracker.items():
            new_active_minutes = len(minutes_set)

            if new_active_minutes > 0:
                # Get or create daily usage record
                usage_result = await db_session.execute(
                    select(DailyUsage)
                    .where(DailyUsage.profile_id == profile_id)
                    .where(DailyUsage.category_id == category_id)
                    .where(DailyUsage.date == today_str)
                )
                usage_record = usage_result.scalars().first()

                if usage_record:
                    usage_record.active_minutes += new_active_minutes
                else:
                    new_usage = DailyUsage(
                        date=today_str,
                        profile_id=profile_id,
                        category_id=category_id,
                        active_minutes=new_active_minutes,
                        is_blocked=False
                    )
                    db_session.add(new_usage)

    if active_minutes_tracker:
        await db_session.commit()
