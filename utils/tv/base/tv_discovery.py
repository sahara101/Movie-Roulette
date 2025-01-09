import logging
import re
import subprocess
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class TVDiscoveryBase(ABC):
    """Base class for TV discovery implementations"""

    @abstractmethod
    def get_name(self) -> str:
        """Get name of this TV type (e.g., 'LG WebOS', 'Samsung Tizen')"""
        pass

    @abstractmethod
    def get_mac_prefixes(self) -> Dict[str, str]:
        """Get mapping of MAC prefixes to device descriptions"""
        pass

    def get_warning_message(self) -> Optional[str]:
        """Get implementation-specific warning message or None if not needed"""
        return None

    def scan_network(self) -> List[Dict[str, str]]:
        try:
            from utils.settings import settings
            blacklisted_macs = settings.get('clients', {}).get('tvs', {}).get('blacklist', {}).get('mac_addresses', [])
            logger.debug(f"Loaded blacklist: {blacklisted_macs}")

            # Do broadcast ping first
            subprocess.run(['ping', '-c', '1', '-b', '255.255.255.255'], capture_output=True)
        
            # Then ping known devices
            try:
                tvs = settings.get('clients', {}).get('tvs', {}).get('instances', {})
                for tv in tvs.values():
                    if tv and tv.get('ip'):
                        subprocess.run(['ping', '-c', '1', tv['ip']], 
                                     stdout=subprocess.DEVNULL, 
                                     stderr=subprocess.DEVNULL)
       	    except Exception as e:
                logger.debug(f"Error pinging known devices: {e}")

            # Get ARP table
            result = subprocess.run(['arp', '-an'], capture_output=True, text=True, check=True)
            lines = []
            for line in result.stdout.splitlines():
                if '?' not in line:
                    continue
                try:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[1].strip('()')
                        mac = parts[3]
                        desc = parts[0] if parts[0] != '?' else 'Samsung Electronics Co.,Ltd' if mac.lower() == 'e0:9d:13:37:b2:84' else None
                        if mac and ip:
                            lines.append(f"{ip}\t{mac}\t{desc if desc else ''}")
                except Exception as e:
                    logger.debug(f"Error parsing line {line}: {e}")
                    continue

            # Process discovered devices
            devices = []
            for line in lines:
                if '\t' not in line:
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    ip, mac = parts[0], parts[1]
                    desc = parts[2] if len(parts) > 2 else None

                    if mac.lower() in (addr.lower() for addr in blacklisted_macs):
                        logger.debug(f"Skipping blacklisted device: {mac}")
                        continue

                    mac_prefix = mac.upper()[:8]
                    if mac_prefix in self.get_mac_prefixes() or self._is_tv_device(desc):
                        # Get the implementation's warning message
                        warning_msg = self.get_warning_message()

                        device = {
                            'ip': ip,
                            'mac': mac,
                            'description': desc or self.get_mac_prefixes().get(mac_prefix, f'{self.get_name()} Device'),
                            'device_type': self.get_mac_prefixes().get(mac_prefix, f'Unknown {self.get_name()} Model'),
                            'untested': bool(warning_msg),
                            'warning': warning_msg
                        }
                        self._enrich_device_info(device)
                        devices.append(device)
                        logger.info(f"Found {self.get_name()} device: {ip} ({mac}) - {desc}")
                        if warning_msg:
                            logger.info(warning_msg)
            return devices

        except Exception as e:
            logger.error(f"Error during network scan: {e}")
            return []

    @abstractmethod
    def _is_tv_device(self, description: Optional[str]) -> bool:
        """Check if device description matches this TV type"""
        pass

    def _enrich_device_info(self, device: Dict[str, Any]):
        """Add additional device-specific information"""
        pass

class TVDiscoveryFactory:
    """Factory for creating TV discovery implementations"""

    _discoveries = {}

    @classmethod
    def register(cls, tv_type: str, discovery_class):
        """Register a discovery implementation for a TV type"""
        cls._discoveries[tv_type] = discovery_class

    @classmethod
    def get_discovery(cls, tv_type: str) -> Optional[TVDiscoveryBase]:
        """Get discovery implementation for given TV type"""
        if tv_type not in cls._discoveries:
            # Import and register discovery implementations on first use
            if tv_type == 'webos':
                from ..discovery.webos_discovery import WebOSDiscovery
                cls.register('webos', WebOSDiscovery())
            elif tv_type == 'tizen':
                from ..discovery.tizen_discovery import TizenDiscovery
                cls.register('tizen', TizenDiscovery())
            elif tv_type == 'android':
                from ..discovery.android_discovery import AndroidDiscovery
                cls.register('android', AndroidDiscovery())

        return cls._discoveries.get(tv_type)
