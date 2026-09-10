import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class UnifiClient:
    def __init__(self, host: str, port: int, username: str, password: str, site: str = "default", verify_ssl: bool = False):
        self.host = host.rstrip('/')
        self.port = port
        self.username = username
        self.password = password
        self.site = site
        self.verify_ssl = verify_ssl
        self.base_url = f"{self.host}:{self.port}"
        self.session: Optional[aiohttp.ClientSession] = None
        self.csrf_token: Optional[str] = None
        self.cookie_header: Optional[str] = None

    async def _init_session(self):
        if not self.session:
            # Create a session with a cookie jar to persist the TOKEN cookie automatically
            jar = aiohttp.CookieJar(unsafe=True)
            connector = aiohttp.TCPConnector(ssl=self.verify_ssl)
            self.session = aiohttp.ClientSession(cookie_jar=jar, connector=connector)

    async def login(self) -> bool:
        """Authenticate with UniFi OS (UDM / Cloud Gateway Max)"""
        await self._init_session()
        login_url = f"{self.base_url}/api/auth/login"
        payload = {
            "username": self.username,
            "password": self.password
        }

        try:
            async with self.session.post(login_url, json=payload, timeout=10) as response:
                if response.status == 200:
                    self.csrf_token = response.headers.get("X-CSRF-Token")
                    
                    # Manually extract cookies from raw headers
                    raw_cookies = response.headers.getall("Set-Cookie", [])
                    cookies = []
                    for rc in raw_cookies:
                        cookie_part = rc.split(";")[0]
                        cookies.append(cookie_part)
                    
                    if cookies:
                        self.cookie_header = "; ".join(cookies)

                    logger.info("Successfully authenticated with UniFi Controller")
                    return True
                else:
                    logger.error(f"Failed to authenticate with UniFi Controller. Status: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Connection error during UniFi login: {e}")
            return False

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    def _get_headers(self) -> dict:
        headers = {}
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        return headers

    async def get_traffic_rules(self) -> list:
        """Fetch all traffic rules"""
        if not self.session:
            return []
            
        url = f"{self.base_url}/proxy/network/v2/api/site/{self.site}/trafficrules"
        try:
            async with self.session.get(url, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    # v2 API might return a flat list or {data: [...]}
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("data", [])
                    return []
                else:
                    logger.error(f"Failed to fetch UniFi traffic rules. Status: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Connection error fetching UniFi traffic rules: {e}")
            return []

    async def set_traffic_rule(self, rule_id: str, enabled: bool) -> bool:
        """Toggle a specific traffic rule on or off"""
        if not self.session:
            await self.login()

        url = f"{self.base_url}/proxy/network/v2/api/site/{self.site}/trafficrules/{rule_id}"
        
        try:
            # 1. Fetch all rules (UniFi v2 API does not support GETting a single rule, and requires the full payload for PUT)
            all_rules = await self.get_traffic_rules()
            rule_payload = None
            
            for r in all_rules:
                if r.get("_id") == rule_id or r.get("id") == rule_id:
                    rule_payload = r
                    break
                    
            if not rule_payload:
                logger.error(f"Rule {rule_id} not found in UniFi traffic rules list")
                return False

            # 2. Modify the enabled flag
            rule_payload["enabled"] = enabled

            # 3. PUT the full payload back
            async with self.session.put(url, json=rule_payload, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    logger.info(f"Traffic rule {rule_id} set to enabled={enabled}")
                    return True
                else:
                    err = await response.text()
                    logger.error(f"Failed to set traffic rule {rule_id}. Status: {response.status}. Msg: {err}")
                    if response.status == 401:
                        self.csrf_token = None
                    return False
        except Exception as e:
            logger.error(f"Connection error setting traffic rule: {e}")
            return False

    async def block_station(self, mac_address: str) -> bool:
        """Block a specific client device entirely from the network"""
        return await self._station_command(mac_address, "block-sta")

    async def unblock_station(self, mac_address: str) -> bool:
        """Unblock a client device"""
        return await self._station_command(mac_address, "unblock-sta")

    async def _station_command(self, mac_address: str, cmd: str) -> bool:
        if not self.session:
            await self.login()

        url = f"{self.base_url}/proxy/network/api/s/{self.site}/cmd/stamgr"
        payload = {
            "cmd": cmd,
            "mac": mac_address.lower()
        }

        try:
            async with self.session.post(url, json=payload, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    logger.info(f"Successfully executed {cmd} for MAC {mac_address}")
                    return True
                else:
                    logger.error(f"Failed to execute {cmd} for MAC {mac_address}. Status: {response.status}")
                    if response.status == 401:
                        self.csrf_token = None
                    return False
        except Exception as e:
            logger.error(f"Connection error executing {cmd}: {e}")
            return False

    async def get_clients(self) -> dict:
        """Fetch all known clients from UniFi (active and historical)"""
        if not self.session:
            await self.login()

        clients = {}
        errors = []
        
        # 1. Fetch active clients
        url_sta = f"{self.base_url}/proxy/network/api/s/{self.site}/stat/sta"
        try:
            async with self.session.get(url_sta, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    for c in data.get("data", []):
                        clients[c.get("mac")] = c
                elif response.status == 401:
                    self.csrf_token = None
                    errors.append("401 Unauthorized for STA")
                else:
                    errors.append(f"HTTP {response.status} for STA")
        except Exception as e:
            logger.error(f"Error fetching active clients: {e}")
            errors.append(f"Exception for STA: {str(e)}")

        # 2. Fetch all historical clients
        url_all = f"{self.base_url}/proxy/network/api/s/{self.site}/stat/alluser"
        try:
            async with self.session.get(url_all, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    for c in data.get("data", []):
                        if c.get("mac") not in clients:
                            clients[c.get("mac")] = c
                elif response.status == 401:
                    self.csrf_token = None
                    errors.append("401 Unauthorized for ALLUSER")
                else:
                    errors.append(f"HTTP {response.status} for ALLUSER")
        except Exception as e:
            logger.error(f"Error fetching historical clients: {e}")
            errors.append(f"Exception for ALLUSER: {str(e)}")

        return {"clients": list(clients.values()), "errors": errors}
