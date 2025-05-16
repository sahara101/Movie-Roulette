import logging
import re
import subprocess
import shlex
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

    def _get_default_interface(self) -> Optional[str]:
        """Try to determine the default network interface."""
        try:
            cmd = "ip route get 1.1.1.1"
            result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=True, timeout=5)
            output = result.stdout.strip()
            match = re.search(r'dev\s+(\S+)', output)
            if match:
                interface = match.group(1)
                logger.info(f"Detected default network interface: {interface}")
                return interface
            else:
                logger.warning(f"Could not parse interface from 'ip route' output: {output}")
                return None
        except FileNotFoundError:
            logger.error("'ip' command not found. Cannot determine default interface. Falling back.")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running 'ip route': {e}. stderr: {e.stderr}")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Timeout running 'ip route'.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting default interface: {e}")
            return None

    def scan_network(self) -> List[Dict[str, str]]:
        """Scan network for TVs of this type"""
        try:
            interface = self._get_default_interface()
            if not interface:
                logger.warning("Could not detect default interface, falling back to 'eth0'.")
                interface = 'eth0'

            arp_scan_cmd = ['arp-scan', '-I', interface, '--localnet']
            logger.info(f"Running arp-scan command: {' '.join(arp_scan_cmd)}")

            from utils.settings import settings
            blacklisted_macs = settings.get('clients', {}).get('tvs', {}).get('blacklist', {}).get('mac_addresses', [])
            logger.debug(f"Loaded blacklist: {blacklisted_macs}")
            result = subprocess.run(
                arp_scan_cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            devices = []
            for line in result.stdout.splitlines():
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
                        logger.info(warning_msg)
            return devices
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running arp-scan on interface {interface}: {e}. stderr: {e.stderr}")
            return []
        except subprocess.TimeoutExpired:
             logger.error(f"Timeout running arp-scan on interface {interface}.")
             return []
        except Exception as e:
            logger.error(f"Error during network scan on interface {interface}: {e}")
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
