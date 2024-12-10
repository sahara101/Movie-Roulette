import subprocess
import socket
import logging
import re

logger = logging.getLogger(__name__)

# Keep your existing comprehensive MAC prefixes
LG_MAC_PREFIXES = {
    # LG Electronics Main
    '00:E0:70': 'LG Electronics',
    '00:1C:62': 'LG Electronics',
    '00:1E:75': 'LG Electronics',
    '00:1F:6B': 'LG Electronics',
    '00:1F:E3': 'LG Electronics',
    '00:22:A9': 'LG Electronics',
    '00:24:83': 'LG Electronics',
    '00:25:E5': 'LG Electronics',
    '00:26:E2': 'LG Electronics',
    '00:34:DA': 'LG Electronics',
    '00:3A:AF': 'LG Electronics',
    '00:50:BA': 'LG Electronics',
    '00:52:A1': 'LG Electronics',
    '00:AA:70': 'LG Electronics',

    # LG TV/Display Specific
    '00:5A:13': 'LG WebOS TV',
    '00:C0:38': 'LG TV',
    '04:4E:5A': 'LG WebOS TV',
    '08:D4:6A': 'LG TV',
    '10:68:3F': 'LG Electronics TV',
    '10:F1:F2': 'LG TV',
    '10:F9:6F': 'LG Electronics TV',
    '2C:54:CF': 'LG Electronics TV',
    '2C:59:8A': 'LG Electronics TV',
    '34:4D:F7': 'LG Electronics TV',
    '38:8C:50': 'LG Electronics TV',
    '3C:BD:D8': 'LG Electronics TV',
    '40:B0:FA': 'LG Electronics TV',
    '48:59:29': 'LG Electronics TV',
    '50:55:27': 'LG Electronics TV',
    '58:A2:B5': 'LG Electronics TV',
    '60:E3:AC': 'LG Electronics TV',
    '64:99:5D': 'LG Electronics TV',
    '6C:DD:BC': 'LG Electronics TV',
    '70:91:8F': 'LG Electronics TV',
    '74:A5:28': 'LG Electronics TV',
    '78:5D:C8': 'LG Electronics TV',
    '7C:1C:4E': 'LG Electronics TV',
    '7C:AB:25': 'LG WebOS TV',
    '88:36:6C': 'LG Electronics TV',
    '8C:3C:4A': 'LG Electronics TV',
    '98:93:CC': 'LG Electronics TV',
    '98:D6:F7': 'LG Electronics TV',
    'A0:39:F7': 'LG Electronics TV',
    'A8:16:B2': 'LG Electronics TV',
    'A8:23:FE': 'LG Electronics TV',
    'AC:0D:1B': 'LG Electronics TV',
    'B4:0E:DC': 'LG Smart TV',
    'B4:E6:2A': 'LG Electronics TV',
    'B8:1D:AA': 'LG Electronics TV',
    'B8:AD:3E': 'LG Electronics TV',
    'BC:8C:CD': 'LG Smart TV',
    'BC:F5:AC': 'LG Electronics TV',
    'C4:36:6C': 'LG Electronics TV',
    'C4:9A:02': 'LG Smart TV',
    'C8:02:8F': 'LG Electronics TV',
    'C8:08:E9': 'LG Electronics TV',
    'CC:2D:8C': 'LG Electronics TV',
    'CC:FA:00': 'LG Electronics TV',
    'D0:13:FD': 'LG Electronics TV',
    'D8:4D:2C': 'LG Electronics TV',
    'DC:0B:34': 'LG Electronics TV',
    'E8:5B:5B': 'LG Electronics TV',
    'E8:F2:E2': 'LG Electronics TV',
    'F0:1C:13': 'LG Electronics TV',
    'F8:0C:F3': 'LG Electronics TV',
    'FC:4D:8C': 'LG WebOS TV',
}

def scan_network():
    """Scan for LG TVs using SSDP discovery"""
    logger.info("Starting LG TV network scan")
    
    devices = {}  # Use dict to track unique IPs
    SSDP_ADDR = '239.255.255.250'  # This is the standard multicast address for SSDP/UPnP
    SSDP_PORT = 1900
    
    # SSDP M-SEARCH message targeting LG TV services
    msearch_msg = '\r\n'.join([
        'M-SEARCH * HTTP/1.1',
        f'HOST: {SSDP_ADDR}:{SSDP_PORT}',
        'MAN: "ssdp:discover"',
        'MX: 2',
        'ST: urn:schemas-upnp-org:device:MediaRenderer:1',
        '', ''
    ])

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(3)
        
        logger.info("Sending SSDP discovery message")
        sock.sendto(msearch_msg.encode(), (SSDP_ADDR, SSDP_PORT))
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                response = data.decode('utf-8')
                
                # Check if it's an LG TV and we haven't seen this IP
                if ('LG' in response or 'WebOS' in response) and addr[0] not in devices:
                    logger.info(f"Found potential LG device at {addr[0]}")
                    
                    # Test if it's really a TV
                    if test_tv_connection(addr[0]):
                        device = {
                            'ip': addr[0],
                            'mac': 'Unknown',
                            'name': 'LG TV',
                            'device_type': 'LG Device'
                        }

                        # Get MAC address
                        mac = get_mac_from_ip(addr[0])
                        if mac:
                            device['mac'] = mac
                        
                        # Try to extract friendly name
                        name_match = re.search(r'friendlyName.?:.*?([^\r\n]+)', response)
                        if name_match:
                            device['name'] = name_match.group(1).strip()
                        
                        devices[addr[0]] = device  # Store by IP to ensure uniqueness
                        logger.info(f"Added device: {device}")
                    
            except socket.timeout:
                break
                
    except Exception as e:
        logger.error(f"Error during SSDP scan: {e}")
    finally:
        try:
            sock.close()
        except:
            pass
    
    # Convert dict values to list for return
    unique_devices = list(devices.values())
    logger.info(f"Scan complete. Found {len(unique_devices)} LG devices")
    return unique_devices

def get_mac_from_ip(ip):
    """Get MAC address for a known IP using arp"""
    logger.info(f"Getting MAC address for IP {ip}")
    try:
        # First ping the IP to ensure it's in the ARP table
        subprocess.run(['ping', '-c', '1', ip], 
                     stdout=subprocess.DEVNULL, 
                     stderr=subprocess.DEVNULL)
                     
        # Now check the ARP table
        arp_result = subprocess.run(['arp', '-n', ip], capture_output=True, text=True)
        mac_matches = re.findall(r'(([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2}))', arp_result.stdout)
        
        if mac_matches:
            mac = mac_matches[0][0].upper()
            # Verify it's an LG MAC
            if any(mac.startswith(prefix) for prefix in LG_MAC_PREFIXES):
                logger.info(f"Found LG MAC address: {mac}")
                return mac
                
        logger.info(f"No valid LG MAC address found for {ip}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting MAC address: {e}")
        return None

def is_valid_mac(mac):
    """Validate MAC address format"""
    return bool(re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', mac))

def is_valid_ip(ip):
    """Validate IP address format"""
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False

def test_tv_connection_nc(ip):
    """Test TV connection using netcat"""
    logger.info(f"Testing connection to {ip} using netcat")
    try:
        # Test using netcat for common WebOS ports
        ports = ['3000', '3001', '8080', '8001', '8002']
        for port in ports:
            nc_result = subprocess.run(
                ['nc', '-zv', '-w1', ip, port],
                capture_output=True,
                text=True
            )
            if nc_result.returncode == 0:
                logger.info(f"Netcat successfully connected to {ip}:{port}")
                return True

        logger.info(f"No open ports found on {ip}")
        return False
    except Exception as e:
        logger.info(f"Netcat test failed: {str(e)}")
        return False

def test_tv_connection(ip):
    """Test if TV is reachable using multiple methods"""
    logger.info(f"Testing connection to TV at {ip}")

    try:
        # Try netcat first as it's more reliable
        if test_tv_connection_nc(ip):
            return True

        # Then try a simple socket connection to common ports
        webos_ports = [3000, 3001, 8080, 8001, 8002]
        for port in webos_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip, int(port)))
                sock.close()

                if result == 0:
                    logger.info(f"Successfully connected to port {port}")
                    return True
            except Exception as e:
                logger.debug(f"Socket connection to port {port} failed: {str(e)}")
                continue

        # Even if we can't connect to ports, if we can resolve the IP, consider it reachable
        try:
            socket.gethostbyaddr(ip)
            logger.info(f"IP {ip} is resolvable, considering TV reachable")
            return True
        except socket.herror:
            pass

        logger.info(f"TV at {ip} is not reachable")
        return False

    except Exception as e:
        logger.error(f"Error testing TV connection: {str(e)}")
        return False
