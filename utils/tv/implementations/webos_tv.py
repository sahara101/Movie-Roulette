import asyncio
import logging
import json
from typing import List, Optional
from pywebostv.connection import WebOSClient
from pywebostv.controls import ApplicationControl

from ..base.tv_base import TVControlBase, TVError, TVConnectionError, TVAppError

logger = logging.getLogger(__name__)

class WebOSTV(TVControlBase):
    """Implementation for LG WebOS TV control"""

    def __init__(self, ip: str = None, mac: str = None):
        super().__init__(ip, mac)
        self._store_path = '/app/data/webos_store.json'
        self._client = None
        self._app_ids = {
            'plex': ['plex', 'plexapp', 'plex media player'],
            'jellyfin': ['jellyfin', 'jellyfin media player', 'jellyfin for webos'],
            'emby': ['emby', 'embytv', 'emby theater', 'emby for webos', 'emby for lg']
        }

    @property
    def tv_type(self) -> str:
        return 'webos'

    @property
    def manufacturer(self) -> str:
        return 'lg'

    def _load_store(self) -> dict:
        """Load TV client store from disk"""
        try:
            with open(self._store_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"Error loading store: {e}")
            return {}

    def _save_store(self, store: dict):
        """Save TV client store to disk"""
        try:
            with open(self._store_path, 'w') as f:
                json.dump(store, f)
        except Exception as e:
            logger.error(f"Error saving store: {e}")

    async def connect(self) -> bool:
        """Connect to TV via WebSocket"""
        try:
            if not self.ip:
                raise TVConnectionError("No IP address configured")

            logger.info(f"Attempting to connect to TV at {self.ip}")
            store = self._load_store()
            
            self._client = WebOSClient(self.ip)
            self._client.connect()

            for status in self._client.register(store):
                if status == WebOSClient.PROMPTED:
                    logger.info("Please accept the connection on your TV")
                elif status == WebOSClient.REGISTERED:
                    logger.info("TV registration successful")
                    self._save_store(store)
                    return True

            return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._client = None
            raise TVConnectionError(f"Failed to connect to TV: {e}")

    async def disconnect(self) -> bool:
        """Disconnect from TV"""
        if self._client:
            try:
                self._client.close()
                self._client = None
                return True
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        return False

    async def is_available(self) -> bool:
        """Check if TV is available on network"""
        try:
            if not self._client:
                await self.connect()
            return bool(self._client)
        except Exception:
            return False

    async def get_installed_apps(self) -> List[str]:
        """Get list of installed apps"""
        if not self._client:
            raise TVConnectionError("Not connected to TV")

        try:
            app_control = ApplicationControl(self._client)
            return app_control.list_apps()
        except Exception as e:
            logger.error(f"Error getting installed apps: {e}")
            raise TVError(f"Failed to get app list: {e}")

    async def launch_app(self, app_id: str) -> bool:
        """Launch app with given ID"""
        if not self._client:
            raise TVConnectionError("Not connected to TV")

        try:
            app_control = ApplicationControl(self._client)
            apps = app_control.list_apps()
            
            # Look for app matching any of the possible names
            target_app = None
            app_names = app_id if isinstance(app_id, list) else [app_id]
            
            for app in apps:
                app_title = app['title'].lower()
                if any(name in app_title for name in app_names):
                    target_app = app
                    break

            if target_app:
                app_control.launch(target_app)
                logger.info(f"Launched app: {target_app['title']}")
                return True
            else:
                logger.error(f"App not found: {app_id}")
                return False

        except Exception as e:
            logger.error(f"Error launching app: {e}")
            raise TVAppError(f"Failed to launch app: {e}")

    async def _wait_for_tv(self):
        """Wait for TV to become available after wake"""
        max_attempts = 20
        for attempt in range(max_attempts):
            if await self.is_available():
                logger.info(f"TV became available after {attempt + 1} attempts")
                await asyncio.sleep(2)  # Give it a little more time to stabilize
                return True
            await asyncio.sleep(1)
        return False

    async def get_power_state(self) -> str:
        """Get TV power state"""
        if await self.is_available():
            return "on"
        return "off"

    def get_app_id(self, service: str) -> Optional[str]:
        """Override to return list of possible app names"""
        return self._app_ids.get(service.lower(), [service.lower()])
