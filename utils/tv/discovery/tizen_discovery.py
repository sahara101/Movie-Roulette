import logging
import asyncio
import socket
from typing import Optional
from typing import Dict

from ..base.tv_discovery import TVDiscoveryBase, TVDiscoveryFactory

logger = logging.getLogger(__name__)

class TizenDiscovery(TVDiscoveryBase):
    """Discovery implementation for Samsung Tizen TVs"""

    def get_mac_prefixes(self) -> Dict[str, str]:
        return {
            # Samsung TV/Display Specific
            '00:07:AB': 'Samsung Tizen TV',
            '00:12:47': 'Samsung Tizen TV',
            '00:15:B9': 'Samsung Tizen TV',
            '00:17:C9': 'Samsung Tizen TV',
            '00:1C:43': 'Samsung Tizen TV',
            '00:21:19': 'Samsung Tizen TV',
            '00:23:39': 'Samsung Tizen TV',
            '00:24:54': 'Samsung Tizen TV',
            '00:26:37': 'Samsung Tizen TV',
            '08:08:C2': 'Samsung Tizen TV',
            '08:D4:2B': 'Samsung Tizen TV',
            '0C:B3:19': 'Samsung Tizen TV',
            '0C:F3:61': 'Samsung Tizen TV',
            '10:1D:C0': 'Samsung Tizen TV',
            '10:3D:B4': 'Samsung Tizen TV',
            '18:3F:47': 'Samsung Tizen TV',
            '2C:0B:E9': 'Samsung Tizen TV',
            '2C:44:01': 'Samsung Tizen TV',
            '34:31:11': 'Samsung Tizen TV',
            '38:01:95': 'Samsung Tizen TV',
            '38:16:D7': 'Samsung Tizen TV',
            '40:0E:85': 'Samsung Tizen TV',
            '40:16:3B': 'Samsung Tizen TV',
            '48:27:EA': 'Samsung Tizen TV',
            '48:44:F7': 'Samsung Tizen TV',
            '4C:BC:98': 'Samsung Tizen TV',
            '50:85:69': 'Samsung Tizen TV',
            '50:B7:C3': 'Samsung Tizen TV',
            '54:92:BE': 'Samsung Tizen TV',
            '54:BD:79': 'Samsung Tizen TV',
            '5C:49:7D': 'Samsung Tizen TV',
            '5C:E8:EB': 'Samsung Tizen TV',
            '64:1C:AE': 'Samsung Tizen TV',
            '68:05:71': 'Samsung Tizen TV',
            '68:27:37': 'Samsung Tizen TV',
            '70:2A:D5': 'Samsung Tizen TV',
            '78:47:1D': 'Samsung Tizen TV',
            '78:9E:D0': 'Samsung Tizen TV',
            '80:4E:81': 'Samsung Tizen TV',
            '84:25:DB': 'Samsung Tizen TV',
            '8C:71:F8': 'Samsung Tizen TV',
            '8C:77:12': 'Samsung Tizen TV',
            '90:F1:AA': 'Samsung Tizen TV',
            '94:35:0A': 'Samsung Tizen TV',
            '94:63:72': 'Samsung Tizen TV',
            '98:1D:FA': 'Samsung Tizen TV',
            '98:83:89': 'Samsung Tizen TV',
            'A0:07:98': 'Samsung Tizen TV',
            'A4:6C:F1': 'Samsung Tizen TV',
            'A8:F2:A3': 'Samsung Tizen TV',
            'AC:5A:14': 'Samsung Tizen TV',
            'B0:72:BF': 'Samsung Tizen TV',
            'B0:C5:59': 'Samsung Tizen TV',
            'B4:79:A7': 'Samsung Tizen TV',
            'B8:BB:AF': 'Samsung Tizen TV',
            'BC:20:A4': 'Samsung Tizen TV',
            'BC:44:86': 'Samsung Tizen TV',
            'BC:72:B1': 'Samsung Tizen TV',
            'BC:8C:CD': 'Samsung Tizen TV',
            'C0:48:E6': 'Samsung Tizen TV',
            'C0:97:27': 'Samsung Tizen TV',
            'C4:57:6E': 'Samsung Tizen TV',
            'CC:6E:A4': 'Samsung Tizen TV',
            'D0:59:E4': 'Samsung Tizen TV',
            'D4:40:F0': 'Samsung Tizen TV',
            'D8:57:EF': 'Samsung Tizen TV',
            'D8:90:E8': 'Samsung Tizen TV',
            'E4:7C:F9': 'Samsung Tizen TV',
            'E8:3A:12': 'Samsung Tizen TV',
            'EC:E0:9B': 'Samsung Tizen TV',
            'F4:7B:5E': 'Samsung Tizen TV',
            'F4:9F:54': 'Samsung Tizen TV',
            'F8:3F:51': 'Samsung Tizen TV',
            'FC:03:9F': 'Samsung Tizen TV',
        }

    def get_name(self) -> str:
        return "Samsung Tizen"

    def _is_tv_device(self, desc: str) -> bool:
        """Check if description indicates a Samsung TV"""
        keywords = ['samsung', 'tizen', 'smart tv']
        desc_lower = desc.lower()
        return any(keyword in desc_lower for keyword in keywords)

    def _enrich_device_info(self, device: Dict):
        """Add Tizen-specific information to device info"""
        device['platform'] = 'tizen'
        # Default Tizen ports
        device['ws_port'] = 8001
        device['api_port'] = 8002

    def get_warning_message(self) -> Optional[str]:
        return ("Samsung TV (Tizen) implementation is currently not working. "
                "I am searching for contributors and testers. "
                "If you're interested in helping, please open a GitHub issue at "
                "https://github.com/sahara101/Movie-Roulette.")

    async def test_connection(self, ip: str) -> bool:
        """Test if TV is reachable using multiple methods"""
        logger.info(f"Testing connection to TV at {ip}")

        try:
            # Try netcat first for common Tizen TV ports
            result = await self._test_connection_nc(ip)
            if result:
                return True

            # Then try socket connections to known Tizen ports
            tizen_ports = [8001, 8002, 8080]
            for port in tizen_ports:
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

            # Try REST API endpoint as final check
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((ip, 8002))
                
                # Try to get TV info
                request = (
                    b'GET /api/v2/information HTTP/1.1\r\n'
                    b'Host: ' + ip.encode() + b'\r\n'
                    b'Connection: close\r\n\r\n'
                )
                sock.send(request)
                
                # Any response indicates TV is available
                if sock.recv(4096):
                    logger.info(f"Successfully got TV info response from {ip}")
                    return True
                    
            except Exception as e:
                logger.debug(f"REST API check failed: {str(e)}")
            finally:
                sock.close()

            logger.info(f"TV at {ip} is not reachable")
            return False

        except Exception as e:
            logger.error(f"Error testing TV connection: {str(e)}")
            return False

    async def _test_connection_nc(self, ip: str) -> bool:
        """Test TV connection using netcat"""
        logger.info(f"Testing connection to {ip} using netcat")
        try:
            ports = ['8001', '8002', '8080']
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

# Register the discoverer
TVDiscoveryFactory.register('tizen', TizenDiscovery())
