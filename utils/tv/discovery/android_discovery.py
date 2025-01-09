import logging
import asyncio
import socket
import re
import subprocess
from typing import Dict, List, Optional
import adb_shell.adb_device
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
import zeroconf

from ..base.tv_discovery import TVDiscoveryBase, TVDiscoveryFactory

logger = logging.getLogger(__name__)

class AndroidDiscovery(TVDiscoveryBase):
   def get_mac_prefixes(self) -> Dict[str, str]:
       return {
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

   def scan_network(self) -> List[Dict[str, str]]:
       devices = super().scan_network()
       ssdp_devices = self._ssdp_scan()
       mdns_devices = asyncio.run(self._discover_mdns())
       
       device_map = {device['ip']: device for device in devices}
       
       for ssdp_device in ssdp_devices:
           if ssdp_device['ip'] in device_map:
               device_map[ssdp_device['ip']].update(ssdp_device)
           else:
               device_map[ssdp_device['ip']] = ssdp_device
               
       for mdns_device in mdns_devices:
           if mdns_device['ip'] in device_map:
               device_map[mdns_device['ip']].update(mdns_device)
           else:
               device_map[mdns_device['ip']] = mdns_device
       
       return list(device_map.values())

   def _ssdp_scan(self) -> List[Dict[str, str]]:
       devices = {}
       try:
           sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
           sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
           sock.settimeout(3)

           msg = '\r\n'.join([
               'M-SEARCH * HTTP/1.1',
               'HOST: 239.255.255.250:1900',
               'MAN: "ssdp:discover"',
               'MX: 2',
               'ST: urn:dial-multiscreen-org:service:dial:1',
               '', ''
           ])

           sock.sendto(msg.encode(), ('239.255.255.250', 1900))

           while True:
               try:
                   data, addr = sock.recvfrom(4096)
                   response = data.decode('utf-8')
                   if 'BRAVIA' in response or 'Sony' in response:
                       mac = self._get_mac_address(addr[0])
                       device = {
                           'ip': addr[0],
                           'mac': mac,
                           'description': 'Sony Android TV',
                           'device_type': 'Android TV',
                           'warning': self.get_warning_message(),
                           'untested': True
                       }
                       devices[addr[0]] = device
               except socket.timeout:
                   break

       except Exception as e:
           logger.error(f"SSDP scan error: {e}")
       finally:
           sock.close()

       return list(devices.values())

   def _get_mac_address(self, ip: str) -> str:
       try:
           subprocess.run(['ping', '-c', '1', ip], 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
           
           output = subprocess.check_output(['arp', '-n', ip]).decode()
           mac = re.search(r'(([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2}))', output)
           if mac:
               return mac.group(1)
       except:
           pass
       return "Unknown"

   def _is_tv_device(self, desc: str) -> bool:
       if not desc:
           return False
       keywords = ['sony', 'bravia', 'android tv']
       desc_lower = desc.lower()
       return any(keyword in desc_lower for keyword in keywords)

   def _enrich_device_info(self, device: Dict):
       device['platform'] = 'android'
       device['adb_port'] = 5555
       device['pairing_port'] = 6466

   async def _discover_mdns(self):
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

       await asyncio.sleep(3)
       zc.close()

       return discovered

   async def test_connection(self, ip: str) -> bool:
       logger.info(f"Testing connection to TV at {ip}")

       try:
           result = await self._test_connection_nc(ip)
           if result:
               return True

           android_ports = [5555, 5037, 6466]
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
       logger.info(f"Testing connection to {ip} using netcat")
       try:
           ports = ['5555', '5037', '6466']
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
               "I am searching for contributors and testers. "
               "If you're interested in helping, please open a GitHub issue at "
               "https://github.com/sahara101/Movie-Roulette.")

TVDiscoveryFactory.register('android', AndroidDiscovery())
