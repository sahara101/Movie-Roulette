import asyncio
import logging
import json
import socket
import os
from typing import List, Optional
from pywebostv.connection import WebOSClient
from pywebostv.controls import ApplicationControl

from ..base.tv_base import TVControlBase, TVError, TVConnectionError, TVAppError
from utils.path_manager import path_manager

logger = logging.getLogger(__name__)

class WebOSTV(TVControlBase):
    def __init__(self, ip: str = None, mac: str = None):
        super().__init__(ip, mac)
        self._store_path = path_manager.get_path('lgtv_store')
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
        try:
            with open(self._store_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"Error loading store: {e}")
            return {}

    def _save_store(self, store: dict):
        try:
            os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
            with open(self._store_path, 'w') as f:
                json.dump(store, f)
        except Exception as e:
            logger.error(f"Error saving store: {e}")

    async def connect(self) -> bool:
        try:
            if not self.ip:
                raise TVConnectionError("No IP address configured")

            logger.info(f"Connecting to TV at {self.ip}")
            store = self._load_store()

            self._client = WebOSClient(self.ip)
            self._client.connect()

            for status in self._client.register(store):
                if status == WebOSClient.PROMPTED:
                    logger.info("Please accept connection on TV")
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
        if self._client:
            try:
                self._client.close()
                self._client = None
                return True
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        return False

    async def is_available(self) -> bool:
        try:
            if not self._client:
                await self.connect()
            return bool(self._client)
        except Exception:
            return False

    async def get_installed_apps(self) -> List[str]:
        if not self._client:
            raise TVConnectionError("Not connected to TV")
 
        try:
            app_control = ApplicationControl(self._client)
            return app_control.list_apps()
        except Exception as e:
            logger.error(f"Error getting apps: {e}")
            raise TVError(f"Failed to get apps: {e}")

    async def launch_app(self, app_id: str) -> bool:
        if not self._client:
            raise TVConnectionError("Not connected to TV")

        try:
            app_control = ApplicationControl(self._client)
            apps = app_control.list_apps()

            target_app = None
            app_names = app_id if isinstance(app_id, list) else [app_id]

            for app in apps:
                if any(name in app['title'].lower() for name in app_names):
                    target_app = app
                    break

            if target_app:
                app_control.launch(target_app)
                logger.info(f"Launched app: {target_app['title']}")
                return True
           
            logger.error(f"App not found: {app_id}")
            return False

        except Exception as e:
            logger.error(f"Error launching app: {e}")
            raise TVAppError(f"Failed to launch app: {e}")

    async def _wait_for_tv(self):
    	max_attempts = 20
    	try:
            # Format MAC for WoL
            if self.mac and ':' in self.mac:
            	formatted_mac = self.mac.replace(':', '')
            elif self.mac and '-' in self.mac:
            	formatted_mac = self.mac.replace('-', '')
            else:
            	formatted_mac = self.mac

            # Try wake on LAN first
            if formatted_mac:
            	self.wake_on_lan(formatted_mac)
    	except Exception as e:
            logger.error(f"WoL error: {e}")

    	# Rest of wait logic
    	for attempt in range(max_attempts):
            if await self.is_available():
            	logger.info(f"TV available after attempt {attempt + 1}")
            	await asyncio.sleep(2)
            	return True
            await asyncio.sleep(1)
    	return False

    async def get_power_state(self) -> str:
        return "on" if await self.is_available() else "off"

    def wake_on_lan(self, mac: str):
    	"""Send Wake-on-LAN magic packet"""
    	if len(mac) != 12:
            raise ValueError("MAC address must be 12 characters without separators")
    
    	magic = 'FF' * 6 + mac * 16
    	send_data = bytes.fromhex(magic)
    
    	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    	sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    	sock.sendto(send_data, ('<broadcast>', 9))

    def get_app_id(self, service: str) -> Optional[str]:
        return self._app_ids.get(service.lower(), [service.lower()])
