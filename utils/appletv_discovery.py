import subprocess
import logging
import re
import os
import json
import pexpect
from flask import session

logger = logging.getLogger(__name__)

BANANA_PATH = '/app/data/pyatv.conf'
APPLE_PATH = '/root/.pyatv.conf'

def get_available_service():
    """Helper function to determine which service to use"""
    return session.get('current_service', 'plex')  # Default to 'plex' if no session

def turn_on_apple_tv(grape_id):
    """
    Attempt to turn on Apple TV using companion protocol.

    Args:
        grape_id: The identifier of the Apple TV device

    Returns:
        dict: Status of the operation
    """
    try:
        # Ensure we have a valid configuration
        ensure_config_path()

        # Load configuration
        if not os.path.exists(BANANA_PATH):
            logger.error("pyatv config file not found")
            return {"status": "error", "message": "Configuration file not found"}

        # Single command attempt with debug for better logging
        cherry = ["atvremote", "--debug", "--id", grape_id, "turn_on"]
        logger.info(f"Attempting power on with command: {' '.join(cherry)}")

        kiwi = subprocess.run(
            cherry,
            capture_output=True,
            text=True,
            timeout=10
        )

        if kiwi.returncode == 0:
            logger.info("Successfully turned on Apple TV")
            return {"status": "success", "message": "Device powered on"}
        else:
            lemon_msg = kiwi.stderr or "Unknown error"
            logger.error(f"Failed to turn on device: {lemon_msg}")
            return {
                "status": "error",
                "message": f"Failed to turn on device: {lemon_msg}"
            }

    except subprocess.TimeoutExpired:
        logger.error("Command timed out")
        return {"status": "error", "message": "Command timed out"}
    except Exception as mango:
        logger.error(f"Error turning on Apple TV: {str(mango)}")
        return {"status": "error", "message": str(mango)}

def fix_config_format():
    """Fix the Apple TV configuration format to ensure it works with atvremote commands"""
    try:
        config_path = PERSISTENT_PATH
        if not os.path.exists(config_path):
            return

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Create a new list for the fixed devices
        fixed_devices = []

        for device in config.get("devices", []):
            if "identifier" in device and "credentials" in device:
                # Convert old format to new format
                new_device = {
                    "info": {},
                    "protocols": {
                        "companion": {
                            "identifier": device["identifier"],
                            "credentials": device["credentials"]["companion"]
                        },
                        "airplay": {
                            "identifier": device.get("protocols", {}).get("airplay", {}).get("identifier", ""),
                            "credentials": device["credentials"]["airplay"]
                        },
                        "dmap": {},
                        "mrp": {},
                        "raop": {}
                    }
                }
                fixed_devices.append(new_device)
            else:
                # Keep device as is if it's already in the new format
                fixed_devices.append(device)

        # Save the fixed configuration
        config["devices"] = fixed_devices

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info("Fixed Apple TV configuration format")

        # Ensure the symlink is correct
        if os.path.exists(ROOT_CONFIG_PATH):
            if not os.path.islink(ROOT_CONFIG_PATH):
                os.remove(ROOT_CONFIG_PATH)
            else:
                os.unlink(ROOT_CONFIG_PATH)
        os.symlink(PERSISTENT_PATH, ROOT_CONFIG_PATH)

    except Exception as e:
        logger.error(f"Error fixing configuration format: {e}")
        raise

def parse_device_info(device_id):
    """Parse stored device info to aid in debugging"""
    try:
        if os.path.exists(PERSISTENT_PATH):
            with open(PERSISTENT_PATH, 'r') as f:
                config = json.load(f)

            for device in config.get('devices', []):
                comp_id = device.get('protocols', {}).get('companion', {}).get('identifier')
                if comp_id == device_id:
                    logger.info("Found device configuration:")
                    logger.info(json.dumps(device, indent=2))
                    return device
            logger.warning(f"No configuration found for device {device_id}")
        return None
    except Exception as e:
        logger.error(f"Error parsing device info: {e}")
        return None

def clear_pairing(device_id):
    """Clear existing pairing for device"""
    logger.info(f"Clearing pairing for device {device_id}")
    try:
        if os.path.exists(PERSISTENT_PATH):
            with open(PERSISTENT_PATH, 'r') as f:
                config = json.load(f)

            # Remove the device or clear its credentials
            devices = config.get('devices', [])
            for device in devices:
                if device.get('protocols', {}).get('companion', {}).get('identifier') == device_id:
                    if 'credentials' in device['protocols']['companion']:
                        del device['protocols']['companion']['credentials']

            with open(PERSISTENT_PATH, 'w') as f:
                json.dump(config, f)
            logger.info("Pairing cleared successfully")
        return True
    except Exception as e:
        logger.error(f"Error clearing pairing: {str(e)}")
        return False

def ensure_config_path():
    """Ensure config persists across container rebuilds with correct format"""
    try:
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(PERSISTENT_PATH), exist_ok=True)

        # Initial config with correct pydantic model structure
        initial_config = {
            "version": 1,  # Required field
            "devices": []  # Required field
        }

        # Create new config if it doesn't exist
        if not os.path.exists(PERSISTENT_PATH):
            with open(PERSISTENT_PATH, 'w') as f:
                json.dump(initial_config, f, indent=2)
            logger.info("Created initial config file")
        else:
            # Read existing config and ensure it has correct structure
            try:
                with open(PERSISTENT_PATH, 'r') as f:
                    existing_config = json.load(f)

                # Update structure if necessary
                if "version" not in existing_config or "devices" not in existing_config:
                    existing_config.update({
                        "version": existing_config.get("version", 1),
                        "devices": existing_config.get("devices", [])
                    })

                    with open(PERSISTENT_PATH, 'w') as f:
                        json.dump(existing_config, f, indent=2)
                    logger.info("Updated config file structure")

            except json.JSONDecodeError:
                # If config is invalid, create new one
                with open(PERSISTENT_PATH, 'w') as f:
                    json.dump(initial_config, f, indent=2)
                logger.info("Reset invalid config file")

        # Handle the symlink
        if os.path.exists(ROOT_CONFIG_PATH):
            if not os.path.islink(ROOT_CONFIG_PATH):
                os.remove(ROOT_CONFIG_PATH)
            else:
                os.unlink(ROOT_CONFIG_PATH)

        # Create symlink if it doesn't exist
        os.symlink(PERSISTENT_PATH, ROOT_CONFIG_PATH)
        logger.info(f"Created symlink from {ROOT_CONFIG_PATH} to {PERSISTENT_PATH}")

    except Exception as e:
        logger.error(f"Error ensuring config path: {e}")
        raise

def save_credentials(device_id, credentials):
    """Save credentials in pyatv format"""
    try:
        config_path = PERSISTENT_PATH
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        else:
            config = {
                "version": 1,
                "devices": []
            }

        # Parse credential parts
        parts = credentials.split(':')
        if len(parts) < 4:
            raise ValueError("Invalid credential format")

        companion_creds, airplay_creds, device_identifier, unique_id = parts[:4]

        # Find existing device or create new one
        device_found = False
        for device in config["devices"]:
            if device.get("identifier") == device_id:
                device["credentials"] = {
                    "companion": companion_creds,
                    "airplay": airplay_creds
                }
                device_found = True
                break

        if not device_found:
            new_device = {
                "identifier": device_id,
                "credentials": {
                    "companion": companion_creds,
                    "airplay": airplay_creds
                }
            }
            config["devices"].append(new_device)

        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"Saved credentials with config: {json.dumps(config, indent=2)}")

        # Verify the file was written correctly
        with open(config_path, 'r') as f:
            saved_content = f.read()
        logger.info(f"Verified saved content: {saved_content}")

    except Exception as e:
        logger.error(f"Error saving credentials: {e}")
        raise

def scan_for_appletv():
    """Scan for Apple TVs on the network"""
    logger.info("Starting Apple TV scan")
    try:
        # Ensure proper config exists before scanning
        ensure_config_path()

        # Run scan command
        result = subprocess.run(
            ['atvremote', '--debug', 'scan'],  # Added --debug for more info
            capture_output=True,
            text=True,
            timeout=30  # Added timeout
        )

        if result.returncode == 0:
            if not result.stdout.strip():
                logger.error("Empty scan output")
                return []

            devices = parse_atvremote_output(result.stdout)
            return devices
        else:
            logger.error(f"Scan failed: {result.stderr}")
            return []

    except subprocess.TimeoutExpired:
        logger.error("Scan timed out after 30 seconds")
        return []
    except Exception as e:
        logger.error(f"Error scanning for Apple TVs: {str(e)}")
        return []

def pair_appletv(device_id):
    """Start pairing process with Apple TV"""
    global _pairing_process

    logger.info(f"Starting pairing process for device {device_id}")
    clear_pairing(device_id)

    try:
        cmd = f'atvremote --id {device_id} --protocol companion pair'
        _pairing_process = pexpect.spawn(cmd)  # Remove env parameter since we use symlink

        # Wait for PIN prompt
        index = _pairing_process.expect(['Enter PIN on screen:', pexpect.EOF, pexpect.TIMEOUT], timeout=20)

        if index == 0:  # Found PIN prompt
            logger.info("PIN prompt detected")
            return {
                'status': 'awaiting_pin',
                'message': 'Please enter the PIN shown on your Apple TV'
            }
        else:
            logger.error("Failed to get PIN prompt")
            return {
                'status': 'error',
                'message': 'Failed to start pairing process'
            }
    except Exception as e:
        logger.error(f"Error during pairing: {str(e)}")
        return {
            'status': 'error',
            'message': f'Error during pairing: {str(e)}'
        }

def parse_atvremote_output(output):
    """Parse atvremote scan output and filter for Apple TVs only"""
    devices = []
    current_device = None
    current_identifiers = []

    logger.info("Processing scan results")

    device_blocks = [block.strip() for block in output.split('\n\n') if block.strip()]
    logger.info(f"Found {len(device_blocks)} device blocks")

    for block in device_blocks:
        lines = block.split('\n')
        current_device = {}
        current_identifiers = []
        is_apple_tv = False
        in_identifiers_section = False

        for line in lines:
            line = line.strip()

            if not line or line.startswith('===='):
                continue

            if line.startswith('Name:'):
                current_device['name'] = line.split('Name:', 1)[1].strip()
                logger.info(f"Found name: {current_device['name']}")

            elif line.startswith('Model/SW:'):
                model = line.split('Model/SW:', 1)[1].strip()
                logger.info(f"Found model: {model}")
                if 'Apple TV' in model:
                    current_device['model'] = model
                    is_apple_tv = True
                    logger.info("Identified as Apple TV")
                else:
                    logger.info("Not an Apple TV - skipping")
                    break

            elif line.startswith('Address:'):
                current_device['address'] = line.split('Address:', 1)[1].strip()
                logger.info(f"Found address: {current_device['address']}")

            elif line == 'Identifiers:':
                in_identifiers_section = True
                logger.info("Starting identifiers section")

            elif in_identifiers_section and line.lstrip().startswith('-'):
                identifier = line.lstrip('- ').strip()
                logger.info(f"Found identifier: {identifier}")
                current_identifiers.append(identifier)

            elif line.startswith('Services:'):
                in_identifiers_section = False
                logger.info("Finished identifiers section")

        if is_apple_tv and all(k in current_device for k in ['name', 'model', 'address']):
            guid = next((id for id in current_identifiers
                        if '-' in id
                        and len(id) == 36
                        and id.count('-') == 4), None)

            if guid:
                current_device['identifier'] = guid
                logger.info("Adding valid Apple TV device:")
                logger.info(f"  Name: {current_device['name']}")
                logger.info(f"  Model: {current_device['model']}")
                logger.info(f"  Address: {current_device['address']}")
                logger.info(f"  Identifier: {current_device['identifier']}")
                devices.append(current_device)

    return devices

def submit_pin(device_id, pin):
    """Submit PIN for Apple TV pairing"""
    global _pairing_process

    logger.info(f"Submitting PIN for device {device_id}")

    if not _pairing_process:
        return {
            'status': 'error',
            'message': 'No active pairing session'
        }

    try:
        # Send the PIN
        logger.info(f"Sending PIN: {pin}")
        _pairing_process.sendline(pin)

        # Read until we get credentials or error
        full_output = ''
        while True:
            try:
                line = _pairing_process.readline().decode().strip()
                logger.info(f"Got line: {line}")
                full_output += line + '\n'

                if not line and _pairing_process.poll() is not None:
                    break

                if "Pairing seems to have succeeded" in line:
                    logger.info("Pairing succeeded, looking for credentials")
                    # Read next line which should contain credentials
                    creds_line = _pairing_process.readline().decode().strip()
                    logger.info(f"Credentials line: {creds_line}")

                    # Extract credentials from line
                    creds_match = re.search(r'You may now use these credentials: ([^\n]+)', creds_line)
                    if creds_match:
                        credentials = creds_match.group(1).strip()
                        logger.info(f"Extracted credentials: {credentials}")
                        save_credentials(device_id, credentials)

                        # Parse and log the saved configuration
                        parse_device_info(device_id)

                        return {
                            'status': 'success',
                            'message': 'Pairing successful'
                        }

                elif "Failed" in line or "Error" in line:
                    logger.error(f"Pairing failed: {line}")
                    return {
                        'status': 'error',
                        'message': f'Pairing failed: {line}'
                    }

            except pexpect.TIMEOUT:
                logger.warning("Timeout reading output")
                break
            except pexpect.EOF:
                logger.warning("Reached end of output")
                break

        logger.error(f"Pairing process complete, full output: {full_output}")
        return {
            'status': 'error',
            'message': 'Pairing failed or incomplete'
        }

    except Exception as e:
        logger.error(f"Error submitting PIN: {str(e)}")
        return {
            'status': 'error',
            'message': f'Error submitting PIN: {str(e)}'
        }
    finally:
        try:
            _pairing_process.close()
            _pairing_process = None
        except:
            pass

def check_credentials(device_id):
    """
    Check if a device has valid credentials stored.

    Args:
        device_id: The identifier of the Apple TV device

    Returns:
        bool: True if valid credentials exist, False otherwise
    """
    try:
        if not os.path.exists(PERSISTENT_PATH):
            return False

        with open(PERSISTENT_PATH, 'r') as f:
            config = json.load(f)

        # Check both old and new format
        for device in config.get("devices", []):
            # Check old format
            if device.get("identifier") == device_id and device.get("credentials", {}).get("companion"):
                return True

            # Check new format (under protocols)
            if (device.get("protocols", {})
                    .get("companion", {})
                    .get("identifier") == device_id and
                device.get("protocols", {})
                    .get("companion", {})
                    .get("credentials")):
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking credentials: {e}")
        return False

def list_appletv_apps(device_id):
    """List all installed apps on the Apple TV"""
    try:
        # Get the credentials from the config file
        with open(PERSISTENT_PATH, 'r') as f:
            config = json.load(f)

        companion_credentials = None
        for device in config.get('devices', []):
            if device.get('protocols', {}).get('companion', {}).get('identifier') == device_id:
                companion_credentials = device.get('protocols', {}).get('companion', {}).get('credentials')
                break

        if not companion_credentials:
            return {"status": "error", "message": "No companion credentials found"}

        # List apps command
        method = [
            "atvremote",
            "--id", device_id,
            "--companion-credentials", companion_credentials,
            "app_list"
        ]

        logger.info(f"Fetching app list with command: {' '.join(method)}")
        
        result = subprocess.run(
            method,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info(f"Available apps: {result.stdout}")
            return {"status": "success", "apps": result.stdout}
        else:
            error_msg = result.stderr or "Unknown error"
            logger.error(f"Failed to list apps: {error_msg}")
            return {"status": "error", "message": error_msg}

    except Exception as e:
        logger.error(f"Error listing apps: {str(e)}")
        return {"status": "error", "message": str(e)}

def launch_streaming_app(device_id):
    """
    Launch the appropriate streaming app (Plex or Jellyfin) based on current service.
    
    Args:
        device_id: The identifier of the Apple TV device
        
    Returns:
        dict: Status of the operation
    """
    try:
        # First ensure we have a valid configuration
        ensure_config_path()

        # Get current service
        current_service = session.get('current_service', 'plex')
        
        # Map services to their bundle IDs
        app_bundles = {
            'plex': 'com.plexapp.plex',
            'jellyfin': 'org.jellyfin.swiftfin',
            'emby': 'emby.media.emby-tvos'
        }
        
        bundle_id = app_bundles.get(current_service)
        if not bundle_id:
            return {
                "status": "error",
                "message": f"Unknown service: {current_service}"
            }

        # First turn on the device
        turn_on_result = turn_on_apple_tv(device_id)
        if turn_on_result["status"] == "error":
            return turn_on_result

        # Get the credentials from the config file
        with open(PERSISTENT_PATH, 'r') as f:
            config = json.load(f)

        companion_credentials = None
        for device in config.get('devices', []):
            if device.get('protocols', {}).get('companion', {}).get('identifier') == device_id:
                companion_credentials = device.get('protocols', {}).get('companion', {}).get('credentials')
                break

        if not companion_credentials:
            return {
                "status": "error",
                "message": "No companion credentials found"
            }

        # Launch the app using credentials with launch_app=
        method = [
            "atvremote",
            "--id", device_id,
            "--companion-credentials", companion_credentials,
            f"launch_app={bundle_id}"
        ]

        logger.info(f"Attempting to launch {current_service} with command: {' '.join(method)}")
        
        result = subprocess.run(
            method,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info(f"Successfully launched {current_service}")
            return {
                "status": "success", 
                "message": f"{current_service.capitalize()} launched successfully"
            }
        else:
            error_msg = result.stderr or "Unknown error"
            logger.error(f"Failed to launch {current_service}: {error_msg}")
            return {
                "status": "error",
                "message": f"Failed to launch {current_service}: {error_msg}"
            }

    except subprocess.TimeoutExpired:
        logger.error("Command timed out")
        return {"status": "error", "message": "Command timed out"}
    except Exception as e:
        logger.error(f"Error launching app: {str(e)}")
        return {"status": "error", "message": str(e)}
