import logging
import asyncio
import socket
from typing import Dict
from typing import Optional
import adb_shell.adb_device
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
import zeroconf

from ..base.tv_discovery import TVDiscoveryBase, TVDiscoveryFactory

logger = logging.getLogger(__name__)

class AndroidDiscovery(TVDiscoveryBase):
    """Discovery implementation for Sony Android TVs"""

    def get_mac_prefixes(self) -> Dict[str, str]:
        return {
            # Sony TV Specific
            '00:04:1F': 'Sony TV',
            '00:13:A9': 'Sony TV',
            '00:1A:80': 'Sony TV',
            '00:24:BE': 'Sony TV',
            '00:EB:2D': 'Sony TV',
            '04:5D:4B': 'Sony TV',
            '10:4F:A8': 'Sony TV',
            '18:E3:BC': 'Sony TV',
            '24:21:AB': 'Sony TV',
            '30:52:CB': 'Sony TV',
            '34:99:71': 'Sony TV',
            '3C:01:EF': 'Sony TV',
            '40:2B:A1': 'Sony TV',
            '54:42:49': 'Sony TV',
            '58:17:0C': 'Sony TV',
            '78:84:3C': 'Sony TV',
            '7C:6D:62': 'Sony TV',
            '84:C7:EA': 'Sony TV',
            '8C:B8:4A': 'Sony TV',
            '94:CE:2C': 'Sony TV',
            'A0:E4:53': 'Sony TV',
            'AC:9B:0A': 'Sony TV',
            'BC:30:7D': 'Sony TV',
            'BC:60:A7': 'Sony TV',
            'E4:11:5B': 'Sony TV',
            'FC:F1:52': 'Sony TV',
        }

    def get_name(self) -> str:
        return "Sony Android"

    def _is_tv_device(self, desc: str) -> bool:
        """Check if description indicates a Sony Android TV"""
        keywords = ['sony', 'bravia', 'android tv']
        desc_lower = desc.lower()
        return any(keyword in desc_lower for keyword in keywords)

    def _enrich_device_info(self, device: Dict):
        """Add Android TV specific information to device info"""
        device['platform'] = 'android'
        device['adb_port'] = 5555
        device['pairing_port'] = 6466

    async def _discover_mdns(self):
        """Discover Android TVs using mDNS"""
        discovered = []
        
        class AndroidTVListener:
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    discovered.append({
                        'ip': socket.inet_ntoa(info.addresses[0]),
                        'name': info.name,
                        'port': info.port
                    })

        zc = zeroconf.Zeroconf()
        listener = AndroidTVListener()
        browser = zeroconf.ServiceBrowser(zc, "_androidtvremote._tcp.local.", listener)
        
        # Wait a bit for discovery
        await asyncio.sleep(3)
        zc.close()
        
        return discovered

    async def test_connection(self, ip: str) -> bool:
        """Test if TV is reachable using multiple methods"""
        logger.info(f"Testing connection to TV at {ip}")

        try:
            # First try netcat for ADB port
            result = await self._test_connection_nc(ip)
            if result:
                return True

            # Then try socket connections
            android_ports = [5555, 5037, 6466]  # ADB and pairing ports
            for port in android_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    sock.close()

                    if result == 0:
                        logger.info(f"Successfully connected to port {port}")
                        return True
                except Exception as e:
                    logger.debug(f"Socket connection to port {port} failed: {str(e)}")
                    continue

            # Try ADB connection as final check
            try:
                device = adb_shell.adb_device.AdbDeviceTcp(ip, 5555, default_transport_timeout_s=3)
                device.connect()
                logger.info(f"Successfully connected via ADB to {ip}")
                device.close()
                return True
            except Exception as e:
                logger.debug(f"ADB connection failed: {str(e)}")

            return False

        except Exception as e:
            logger.error(f"Error testing TV connection: {str(e)}")
            return False

    async def _test_connection_nc(self, ip: str) -> bool:
        """Test TV connection using netcat"""
        logger.info(f"Testing connection to {ip} using netcat")
        try:
            ports = ['5555', '5037', '6466']  # ADB and pairing ports
            for port in ports:
                process = await asyncio.create_subprocess_exec(
                    'nc', '-zv', '-w1', ip, port,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                
                if process.returncode == 0:
                    logger.info(f"Netcat successfully connected to {ip}:{port}")
                    return True

            logger.info(f"No open ports found on {ip}")
            return False
        except Exception as e:
            logger.info(f"Netcat test failed: {str(e)}")
            return False

    def get_warning_message(self) -> Optional[str]:
        return ("Android TV implementation is currently not working. "
                "I am searching for ontributors and testers. "
                "If you're interested in helping, please open a GitHub issue at "
                "https://github.com/sahara101/Movie-Roulette.")

    async def scan_network_mdns(self):
        """Additional scan using mDNS for Android TV discovery"""
        try:
            mdns_devices = await self._discover_mdns()
            devices = []
            
            for device in mdns_devices:
                ip = device['ip']
                try:
                    # Get MAC address using ARP
                    result = await asyncio.create_subprocess_exec(
                        'arp', '-n', ip,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await result.communicate()
                    
                    mac = None
                    for line in stdout.decode().splitlines():
                        if ip in line:
                            parts = line.split()
                            if len(parts) >= 3:
                                mac = parts[2].upper()
                    
                    if mac:
                        device_info = {
                            'ip': ip,
                            'mac': mac,
                            'description': f"Sony Android TV ({device['name']})",
                            'device_type': 'Android TV',
                            'manufacturer': self.get_name()
                        }
                        self._enrich_device_info(device_info)
                        devices.append(device_info)
                        
                except Exception as e:
                    logger.error(f"Error processing mDNS device {ip}: {e}")
                    
            return devices
            
        except Exception as e:
            logger.error(f"Error in mDNS scan: {e}")
            return []

# Register the discoverer
TVDiscoveryFactory.register('android', AndroidDiscovery())
