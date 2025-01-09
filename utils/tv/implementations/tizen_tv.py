import asyncio
import logging
import base64
import json
import time
import websocket
from typing import List, Optional
from wakeonlan import send_magic_packet

from ..base.tv_base import TVControlBase, TVError, TVConnectionError, TVAppError

logger = logging.getLogger(__name__)

class SamsungTVWS:
    URL_FORMAT = 'ws://{host}:{port}/api/v2/channels/samsung.remote.control?name={name}'
    KEY_INTERVAL = 1.5

    def __init__(self, host, port=8001, name='MovieRoulette'):
        self.connection = None
        self.host = host
        self.port = port
        self.name = name

    def _serialize_string(self, string):
        if isinstance(string, str):
            string = str.encode(string)
        return base64.b64encode(string).decode('utf-8')

    def connect(self):
        try:
            self.connection = websocket.create_connection(
                self.URL_FORMAT.format(
                    host=self.host,
                    port=self.port,
                    name=self._serialize_string(self.name)
                )
            )
            response = json.loads(self.connection.recv())
            if response['event'] != 'ms.channel.connect':
                self.close()
                raise Exception(response)
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.debug('Connection closed.')

    def send_key(self, key, repeat=1):
        if not self.connection:
            raise Exception("Not connected")

        for n in range(repeat):
            payload = json.dumps({
                'method': 'ms.remote.control',
                'params': {
                    'Cmd': 'Click',
                    'DataOfCmd': key,
                    'Option': 'false',
                    'TypeOfRemote': 'SendRemoteKey'
                }
            })
            logger.info(f'Sending key {key}')
            self.connection.send(payload)
            time.sleep(self.KEY_INTERVAL)

class TizenTV(TVControlBase):
    """Implementation for Samsung Tizen TV control"""

    def __init__(self, ip: str = None, mac: str = None):
        super().__init__(ip, mac)
        self._tv = None
        self._default_app_ids = {
            'plex': '3201512006963',
            'jellyfin': 'AprZAARz4r.Jellyfin',
            'emby': '3201606009872'
        }

    @property
    def tv_type(self) -> str:
        return 'tizen'

    @property
    def manufacturer(self) -> str:
        return 'samsung'

    def send_wol(self) -> bool:
        """Send Wake-on-LAN packet to TV"""
        if not self.mac:
            logger.error("Cannot send WoL packet: No MAC address configured")
            return False

        try:
            # Send to both ports commonly used by Samsung TVs
            for port in [7, 9]:
                try:
                    send_magic_packet(self.mac, port=port)
                    logger.info(f"Sent WoL packet to {self.mac} on port {port}")
                except Exception as e:
                    logger.debug(f"Failed to send WoL on port {port}: {e}")

            return True
        except Exception as e:
            logger.error(f"Failed to send Wake-on-LAN packet: {e}")
            return False

    async def connect(self) -> bool:
        """Connect to TV via WebSocket"""
        try:
            if self._tv and self._tv.connection:
                return True

            logger.info(f"Attempting to connect to TV at {self.ip}")
            self._tv = SamsungTVWS(host=self.ip, port=8001, name='MovieRoulette')

            # Run the synchronous connect in the executor
            success = await asyncio.get_event_loop().run_in_executor(None, self._tv.connect)

            if success:
                logger.info("Successfully connected to TV")
                try:
                    # Try to wake up TV via key command
                    await asyncio.get_event_loop().run_in_executor(None, self._tv.send_key, 'KEY_POWER')
                except:
                    pass  # Ignore if power key fails
                return True

            return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> bool:
        """Disconnect from TV"""
        if self._tv:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._tv.close)
                self._tv = None
                return True
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        return False

    async def is_available(self) -> bool:
        """Check if TV is available on network"""
        try:
            if not self._tv:
                return await self.connect()
            return bool(self._tv.connection)
        except Exception as e:
            logger.debug(f"TV availability check failed: {str(e)}")
            return False

    async def _wait_for_tv(self):
        """Wait for TV to become available after wake-on-lan"""
        max_attempts = 5
        for attempt in range(max_attempts):
            logger.info(f"Waiting for TV to wake up (attempt {attempt + 1}/{max_attempts})")
            if await self.is_available():
                logger.info(f"TV became available after {attempt + 1} attempts")
                await asyncio.sleep(2)  # Give it a little more time to stabilize
                return True
            await asyncio.sleep(3)  # Longer delay between attempts
        return False

    def get_app_id(self, service: str) -> Optional[str]:
        """Get platform-specific app ID for given service"""
        return self._default_app_ids.get(service.lower())

    async def get_installed_apps(self) -> List[str]:
        """Not implemented for basic version"""
        logger.warning("get_installed_apps not implemented")
        return []

    async def launch_app(self, app_id: str) -> bool:
        """Launch app using REST API"""
        if not self._tv:
            raise TVConnectionError("Not connected to TV")

        try:
            # Use REST API to launch app
            import requests
            url = f"http://{self.ip}:8001/api/v2/applications/{app_id}"
            response = requests.post(url)

            if response.status_code == 200:
                logger.info(f"Successfully launched app {app_id}")
                return True
            else:
                logger.error(f"Failed to launch app, status code: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error launching app: {e}")
            raise TVAppError(f"Failed to launch app: {e}")

    async def get_power_state(self) -> str:
        """Get TV power state"""
        if await self.is_available():
            return "on"
        return "off"
