from abc import ABC, abstractmethod
import socket
import logging
import asyncio
from typing import Optional, Dict, Any
from utils.settings import settings

logger = logging.getLogger(__name__)

class TVControlBase(ABC):
    """Base class for TV control implementations"""

    def __init__(self, ip: str = None, mac: str = None):
        """Initialize TV control with optional IP and MAC address"""
        self.ip = ip
        self.mac = mac
        self._config = self._load_config()

        if not self.ip:
            self.ip = self._config.get('ip')
        if not self.mac:
            self.mac = self._config.get('mac')

    @property
    @abstractmethod
    def tv_type(self) -> str:
        """Return TV type (webos, tizen, android)"""
        pass

    @property
    @abstractmethod
    def manufacturer(self) -> str:
        """Return TV manufacturer (lg, samsung, sony)"""
        pass

    def get_name(self) -> str:
        """Get TV name from configuration"""
        tv_instances = settings.get('clients', {}).get('tvs', {}).get('instances', {})
        for instance_id, instance in tv_instances.items():
            if (instance.get('ip') == self.ip and
                instance.get('mac') == self.mac and
                instance.get('type') == self.tv_type):
                return instance.get('name', instance_id)
        return f"{self.manufacturer.upper()} TV ({self.ip})"

    def _load_config(self) -> Dict[str, Any]:
        """Load TV configuration from settings"""
        tv_settings = settings.get('clients', {}).get('tv', {})
        if tv_settings.get('type') == self.tv_type and tv_settings.get('model') == self.manufacturer:
            return tv_settings
        return {}

    def get_app_id(self, service: str) -> Optional[str]:
        """Get platform-specific app ID for given service"""
        # Default app IDs for different platforms
        default_app_ids = {
            'webos': {
                'plex': ['plex', 'plexapp', 'plex media player'],
                'jellyfin': ['jellyfin', 'jellyfin media player', 'jellyfin for webos'],
                'emby': ['emby', 'embytv', 'emby theater', 'emby for webos', 'emby for lg']
            },
            'tizen': {
                'plex': 'QJxQHhr3rY',  # Tizen Plex app ID
                'jellyfin': 'jellyfin.tizen',
                'emby': 'emby.tizen'
            },
            'android': {
                'plex': 'com.plexapp.android.tv',
                'jellyfin': 'org.jellyfin.androidtv',
                'emby': 'tv.emby.embyatv'
            }
        }
        
        if self.tv_type in default_app_ids:
            return default_app_ids[self.tv_type].get(service)
        
        # Fallback to config if exists
        app_ids = self._config.get('app_ids', {}).get(self.tv_type, {})
        return app_ids.get(service)

    def send_wol(self) -> bool:
        """Send Wake-on-LAN packet to TV"""
        if not self.mac:
            logger.error("Cannot send WoL packet: No MAC address configured")
            return False

        try:
            # Clean up MAC address format
            mac_address = str(self.mac).replace(':', '').replace('-', '')
            if len(mac_address) != 12:
                raise ValueError("Invalid MAC address format")

            # Create magic packet
            data = bytes.fromhex('FF' * 6 + mac_address * 16)

            # Send packet
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(data, ('<broadcast>', 9))

            logger.info(f"Wake-on-LAN packet sent to {self.mac}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Wake-on-LAN magic packet: {e}")
            return False

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to TV"""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Close connection to TV"""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if TV is available on the network"""
        pass

    @abstractmethod
    async def get_installed_apps(self) -> list:
        """Get list of installed apps"""
        pass

    @abstractmethod
    async def launch_app(self, app_id: str) -> bool:
        """Launch app with given ID"""
        pass

    async def launch_service(self, service: str) -> bool:
        """Launch media service (plex, jellyfin, emby)"""
        app_id = self.get_app_id(service)
        if not app_id:
            logger.error(f"No app ID found for service: {service}")
            return False

        return await self.launch_app(app_id)

    async def turn_on(self, app_to_launch: Optional[str] = None) -> bool:
        """Turn on TV and optionally launch an app"""
        # If we have a MAC address, always start with WoL
        if self.mac:
            logger.info(f"Sending WoL packet to {self.mac}")
            try:
                # Try async send_wol if implemented by child class
                if hasattr(self, 'async_send_wol'):
                    if not await self.async_send_wol():
                        logger.error("Failed to send WoL packet (async)")
                        return False
                # Fall back to sync send_wol from base class
                else:
                    if not self.send_wol():
                        logger.error("Failed to send WoL packet")
                        return False
            except Exception as e:
                logger.error(f"Error sending WoL packet: {e}")
                return False

            # Give TV time to wake up
            if not await self._wait_for_tv():
                logger.error("TV failed to wake up after WoL")
                return False
        else:
            # No MAC address, try to connect directly
            if not await self.is_available():
                logger.error("TV is not available and no MAC address configured for WoL")
                return False

        if not await self.connect():
            return False

        if app_to_launch:
            return await self.launch_service(app_to_launch)

        return True

    @abstractmethod
    async def _wait_for_tv(self):
        """Wait for TV to become available after wake-on-lan"""
        pass

    @abstractmethod
    async def get_power_state(self) -> str:
        """Get current power state of TV"""
        pass

class TVError(Exception):
    """Base exception for TV-related errors"""
    pass

class TVConnectionError(TVError):
    """Error establishing connection to TV"""
    pass

class TVAuthenticationError(TVError):
    """Error authenticating with TV"""
    pass

class TVAppError(TVError):
    """Error launching or controlling apps"""
    pass
