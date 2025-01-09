import asyncio
import logging
from pathlib import Path
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
import adb_shell.adb_device
from typing import List, Optional

from ..base.tv_base import TVControlBase, TVError, TVConnectionError, TVAppError

logger = logging.getLogger(__name__)

class AndroidTV(TVControlBase):
    """Implementation for Sony Android TV control"""

    def __init__(self, ip: str = None, mac: str = None):
        super().__init__(ip, mac)
        self.adb_port = self._config.get('android', {}).get('adb_port', '5555')
        self.pairing_port = self._config.get('android', {}).get('pairing_port', '6466')
        self._device = None
        self._default_app_ids = {
            'plex': 'com.plexapp.android',
            'jellyfin': 'org.jellyfin.androidtv',
            'emby': 'tv.emby.embyatv'
        }
        self._load_adb_keys()

    @property
    def tv_type(self) -> str:
        return 'android'

    @property
    def manufacturer(self) -> str:
        return 'sony'

    def get_app_id(self, service: str) -> Optional[str]:
        """Get platform-specific app ID for given service"""
        return self._default_app_ids.get(service.lower())

    def _load_adb_keys(self):
        """Load or create ADB key pair"""
        key_path = Path(path_manager.base_dir) / 'adbkey'
        try:
            if not key_path.exists():
                keygen(str(key_path))
            with open(key_path, 'rb') as f:
                private_key = f.read()
            with open(f"{key_path}.pub", 'rb') as f:
                public_key = f.read()
            self.signer = PythonRSASigner(public_key, private_key)
            logger.info("ADB keys loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load ADB keys: {e}")
            raise TVConnectionError("Could not initialize ADB authentication")

    async def connect(self) -> bool:
        """Connect to TV via ADB"""
        try:
            if self._device and self._device.available:
                return True

            self._device = adb_shell.adb_device.AdbDeviceTcp(
                self.ip,
                int(self.adb_port),
                default_transport_timeout_s=9.
            )

            connected = await asyncio.to_thread(
                self._device.connect,
                rsa_keys=[self.signer],
                auth_timeout_s=5
            )

            if connected:
                logger.info(f"Connected to Android TV at {self.ip}")
                return True
            else:
                logger.error("Failed to connect to TV")
                return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> bool:
        """Disconnect from TV"""
        if self._device:
            try:
                await asyncio.to_thread(self._device.close)
                self._device = None
                return True
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        return False

    async def is_available(self) -> bool:
        """Check if TV is available on network"""
        try:
            # First try basic socket connection
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((self.ip, int(self.adb_port)))
                sock.close()
                if result != 0:
                    logger.debug(f"Basic socket connection failed with result {result}")
                    return False
                logger.debug("Basic socket connection successful")
            except Exception as e:
                logger.error(f"Socket test failed: {e}")
                return False

            # Then try ADB connection
            if not self._device:
                return await self.connect()
            return self._device.available

        except Exception as e:
            logger.error(f"TV not available: {e}")
            return False

    async def get_installed_apps(self) -> List[str]:
        """Get list of installed apps"""
        if not self._device:
            raise TVConnectionError("Not connected to TV")

        try:
            result = await asyncio.to_thread(
                self._device.shell,
                "pm list packages -3"
            )
            apps = [line.split(':')[1] for line in result.splitlines() if ':' in line]
            return [{'app_id': app, 'name': app} for app in apps]
        except Exception as e:
            logger.error(f"Error getting installed apps: {e}")
            raise TVError(f"Failed to get app list: {e}")

    async def launch_app(self, app_id: str) -> bool:
        """Launch app with given ID"""
        if not self._device:
            raise TVConnectionError("Not connected to TV")

        try:
            # Try to launch the app using monkey tool first
            try:
                cmd = f"monkey -p {app_id} -c android.intent.category.LAUNCHER 1"
                result = await asyncio.to_thread(self._device.shell, cmd)
                if "Events injected: 1" in result:
                    logger.info(f"Launched app {app_id} using monkey tool")
                    return True
            except Exception as e:
                logger.debug(f"Monkey tool launch failed: {e}, trying activity manager")

            # Fallback to activity manager
            try:
                cmd = f"am start -n {app_id}/.MainActivity"
                await asyncio.to_thread(self._device.shell, cmd)
                logger.info(f"Launched app {app_id} using activity manager")
                return True
            except Exception as e:
                logger.error(f"All launch methods failed for app {app_id}: {e}")
                raise TVAppError(f"Failed to launch app: {e}")

        except Exception as e:
            logger.error(f"Error launching app: {e}")
            raise TVAppError(f"Failed to launch app: {e}")

    async def get_power_state(self) -> str:
        """Get TV power state"""
        if await self.is_available():
            return "on"
        return "off"

    async def _wait_for_tv(self):
        """Wait for TV to become available after wake-on-lan"""
        max_attempts = 20
        for attempt in range(max_attempts):
            if await self.is_available():
                logger.info(f"TV became available after {attempt + 1} attempts")
                await asyncio.sleep(2)  # Give it a little more time to stabilize
                return True
            await asyncio.sleep(1)
        return False
