import socket
import struct
import time
import json
from pywebostv.connection import WebOSClient
from pywebostv.controls import ApplicationControl
import os
import sys
from utils.settings import settings

STORE_PATH = '/app/data/lgtv_store.json'

def get_tv_config():
    """Get TV configuration from ENV or settings"""
    # First check ENV variables
    tv_mac = os.getenv('LGTV_MAC')
    tv_ip = os.getenv('LGTV_IP')
    
    # If not in ENV, check settings
    if not tv_mac or not tv_ip:
        lg_settings = settings.get('clients', {}).get('lg_tv', {})
        tv_mac = lg_settings.get('mac')
        tv_ip = lg_settings.get('ip')
    
    return tv_ip, tv_mac

def send_wol(mac_address):
    try:
        mac_address = mac_address.replace(':', '').replace('-', '')
        if len(mac_address) != 12:
            raise ValueError("Invalid MAC address format")
        data = bytes.fromhex('FF' * 6 + mac_address * 16)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(data, ('<broadcast>', 9))
        print("Wake-on-LAN magic packet sent successfully.")
        return True
    except Exception as e:
        print(f"Failed to send Wake-on-LAN magic packet: {e}")
        return False

def load_store():
    try:
        with open(STORE_PATH, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_store(store):
    with open(STORE_PATH, 'w') as file:
        json.dump(store, file)

def connect_to_tv(ip=None):
    store = load_store()
    ip = ip or get_tv_config()[0]  # Use provided IP or get from config
    
    if not ip:
        raise ValueError("No TV IP configured")
        
    client = WebOSClient(ip)
    while True:
        try:
            client.connect()
            for status in client.register(store):
                if status == WebOSClient.PROMPTED:
                    print("Please accept the connection on the TV.")
                elif status == WebOSClient.REGISTERED:
                    print("Registration successful!")
                    save_store(store)
                    return client
        except Exception as e:
            print(f"Failed to connect to the TV: {e}. Retrying in 3 seconds...")
            time.sleep(3)

def launch_app(client, app_name):
    app_control = ApplicationControl(client)
    apps = app_control.list_apps()
    target_app = next((app for app in apps if app_name.lower() in app["title"].lower()), None)
    if target_app:
        app_control.launch(target_app)
        print(f"{app_name} app launched successfully.")
        return True
    else:
        print(f"{app_name} app not found.")
        return False

def main(app_name='plex'):
    tv_ip, tv_mac = get_tv_config()
    
    if not tv_mac or not tv_ip:
        print("No TV configuration found in environment variables or settings.")
        return False
        
    if not send_wol(tv_mac):
        print("Failed to send wake-on-LAN packet")
        return False
        
    # Give the TV some time to wake up
    time.sleep(5)
    
    try:
        client = connect_to_tv(tv_ip)
        if client:
            return launch_app(client, app_name)
    except Exception as e:
        print(f"Error controlling TV: {e}")
        return False
    
    return False

if __name__ == "__main__":
    app_to_launch = sys.argv[1] if len(sys.argv) > 1 else 'plex'
    main(app_to_launch)
