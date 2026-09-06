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
                    # UniFi OS returns a CSRF token in the headers which is required for POST/PUT requests
                    self.csrf_token = response.headers.get("X-CSRF-Token")
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
        return headers

    async def set_traffic_rule(self, rule_id: str, enabled: bool) -> bool:
        """Toggle a specific traffic rule on or off"""
        if not self.session:
            await self.login()

        url = f"{self.base_url}/proxy/network/v2/api/site/{self.site}/trafficrules/{rule_id}"
        payload = {
            "_id": rule_id,
            "enabled": enabled
        }

        try:
            async with self.session.put(url, json=payload, headers=self._get_headers(), timeout=10) as response:
                if response.status == 200:
                    logger.info(f"Traffic rule {rule_id} set to enabled={enabled}")
                    return True
                else:
                    logger.error(f"Failed to set traffic rule {rule_id}. Status: {response.status}")
                    # If unauthorized, we might need to login again next time
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
