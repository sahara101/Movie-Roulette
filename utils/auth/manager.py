import os
import logging
import traceback
from flask import request, session, redirect, url_for
from functools import wraps
import requests
import uuid
import time
import secrets
import json
from pathlib import Path
from datetime import datetime, timedelta
from .db import AuthDB
from utils.settings import settings

logger = logging.getLogger(__name__)

class AuthManager:
    """Manager for authentication operations"""

    def __init__(self):
        self.db = AuthDB()
        self._auth_enabled = None
        self._plex_pins = {}  # Store PIN data in memory during auth flow
        # Add a path for persistent storage of PIN data
        self._pins_file = Path('/tmp/movie_roulette_pins.json')
        # Load any saved PINs from disk
        self._load_pins_from_disk()

    @property
    def auth_enabled(self):
        """Check if authentication is enabled in settings"""
        if self._auth_enabled is not None:
            return self._auth_enabled

        # Get from settings or environment variable
        env_enabled = os.environ.get('AUTH_ENABLED', '').lower() in ('true', '1', 'yes')
        settings_enabled = settings.get('auth', {}).get('enabled', False)

        self._auth_enabled = env_enabled or settings_enabled
        return self._auth_enabled

    def update_auth_enabled(self, enabled):
        """Update the auth enabled setting"""
        # Record the previous state to detect state changes
        previous_state = self._auth_enabled
        # Update the state
        self._auth_enabled = enabled

        # Log the state change
        logger.info(f"Authentication state changed: {previous_state} -> {enabled}")

        # If auth was disabled and is now enabled, we need to ensure setup is triggered
        # if no admin user exists
        if not previous_state and enabled and self.needs_admin():
            logger.info("Auth enabled with no admin account - setup will be triggered")

    def is_first_run(self):
        """Check if this is the first run (no users configured)"""
        return self.auth_enabled and not self.db.has_users()

    def needs_admin(self):
        """Check if an admin user needs to be created"""
        # Look specifically for a local admin user (not service account)
        admin_users = self.db.get_users()
        # Check if any user has the is_admin flag set to True
        has_any_admin = any(user_data.get('is_admin', False) for user_data in admin_users.values())

        return self.auth_enabled and not has_any_admin

    def login(self, username, password):
        """Login a user"""
        success, message = self.db.verify_user(username, password)

        if not success:
            return False, message

        # Create a session using configured lifetime
        token = self.db.create_session(username)

        return True, token

    def logout(self, token):
        """Logout a user"""
        return self.db.delete_session(token)

    def verify_auth(self, token):
        """Verify authentication token"""
        if not self.auth_enabled:
            # If auth is disabled, allow all requests
            return {'username': 'admin', 'is_admin': True}

        return self.db.verify_session(token)

    def require_auth(self, f):
        """Decorator to require authentication for a route"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if not self.auth_enabled:
                # If auth is disabled, allow all requests
                return f(*args, **kwargs)

            # Get the auth token from cookie
            token = request.cookies.get('auth_token')

            if not token:
                # Redirect to login page
                return redirect(url_for('auth.login', next=request.path))

            # Verify the token
            user_data = self.db.verify_session(token)

            if not user_data:
                # Invalid or expired token
                return redirect(url_for('auth.login', next=request.path))

            # Store internal username and admin status in Flask session
            internal_username = user_data['username']
            session['username'] = internal_username # Store internal name in session
            session['is_admin'] = user_data['is_admin']
            session['service_type'] = user_data.get('service_type', 'local')

            # Calculate and store display username in Flask 'g' context for this request
            display_username = internal_username
            if internal_username.startswith('plex_'):
                display_username = internal_username[len('plex_'):]
            elif internal_username.startswith('emby_'):
                display_username = internal_username[len('emby_'):]
            elif internal_username.startswith('jellyfin_'):
                display_username = internal_username[len('jellyfin_'):]

            from flask import g as request_context # Use alias to avoid confusion
            request_context.user = {
                'internal_username': internal_username,
                'display_username': display_username,
                'is_admin': user_data['is_admin'],
                'service_type': user_data.get('service_type', 'local')
            }
            logger.debug(f"Set request context user: {request_context.user}")


            return f(*args, **kwargs)

        return decorated

    def require_admin(self, f):
        """Decorator to require admin privileges for a route"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if not self.auth_enabled:
                # If auth is disabled, allow all requests
                return f(*args, **kwargs)

            # Get the auth token from cookie
            token = request.cookies.get('auth_token')

            if not token:
                # Redirect to login page
                return redirect(url_for('auth.login', next=request.url))

            # Verify the token
            user_data = self.db.verify_session(token)

            if not user_data:
                # Invalid or expired token
                return redirect(url_for('auth.login', next=request.url))

            if not user_data['is_admin']:
                # User is not an admin
                return {"error": "Admin privileges required"}, 403

            # Store user data in Flask session for the request
            session['username'] = user_data['username']
            session['is_admin'] = user_data['is_admin']
            session['service_type'] = user_data.get('service_type', 'local') # Store service type

            return f(*args, **kwargs)

        return decorated

    def create_user(self, username, password, is_admin=False):
        """Create a new user"""
        # Check if we're creating a local account (not through a service)
        is_service_account = False
        stack = traceback.extract_stack()
        for frame in stack:
            if 'process_plex_auth' in frame.name:
                is_service_account = True
                break

        # Removed restriction: Allow any username for local accounts

        # Determine service type based on context
        service_type = 'plex' if is_service_account else 'local'

        return self.db.add_user(username, password, is_admin, service_type=service_type)

    def update_password(self, username, new_password):
        """Update a user's password"""
        return self.db.update_password(username, new_password)

    def delete_user(self, username):
        """Delete a user"""
        return self.db.delete_user(username)

    def get_users(self):
        """Get a list of all users"""
        return self.db.get_users()

    # Persist PINs to disk methods
    def _save_pins_to_disk(self):
        """Save PIN data to disk to persist between requests"""
        try:
            # Convert all datetime values to strings for JSON serialization
            pins_data = {}
            for pin_id, pin_data in self._plex_pins.items():
                pins_data[str(pin_id)] = {
                    **pin_data,
                    'created_at': pin_data['created_at'],
                    'expires_at': pin_data['expires_at']
                }

            with open(self._pins_file, 'w') as f:
                json.dump(pins_data, f)

            logger.info(f"Saved {len(pins_data)} PINs to disk")
        except Exception as e:
            logger.error(f"Error saving PINs to disk: {e}")

    def _load_pins_from_disk(self):
        """Load PIN data from disk"""
        try:
            if self._pins_file.exists():
                with open(self._pins_file, 'r') as f:
                    pins_data = json.load(f)

                # Convert to internal format
                for pin_id, pin_data in pins_data.items():
                    self._plex_pins[int(pin_id)] = pin_data

                # Clean up expired PINs
                current_time = time.time()
                expired_pins = [
                    pin_id for pin_id, data in self._plex_pins.items()
                    if data.get('expires_at', 0) < current_time
                ]

                for pin_id in expired_pins:
                    del self._plex_pins[pin_id]

                logger.info(f"Loaded {len(self._plex_pins)} valid PINs from disk")

                # Save back cleaned up PINs
                if expired_pins:
                    self._save_pins_to_disk()
        except Exception as e:
            logger.error(f"Error loading PINs from disk: {e}")
            self._plex_pins = {}

    # Plex Authentication Methods
    def generate_plex_auth_url(self):
        """Generate URL for Plex authentication"""
        try:
            # Get client ID from request headers if provided
            client_id = request.headers.get('X-Plex-Client-Identifier')

            # If no client ID provided, generate one
            if not client_id:
                client_id = str(uuid.uuid4())

            # Build headers with client information
            browser = request.user_agent.browser
            platform = request.user_agent.platform
            version = request.user_agent.version

            headers = {
                'X-Plex-Client-Identifier': client_id,
                'X-Plex-Product': 'Movie Roulette',
                'X-Plex-Version': '1.0',
                'X-Plex-Platform': platform or 'Web',
                'X-Plex-Platform-Version': version or '1.0',
                'X-Plex-Device': browser or 'Web Browser',
                'X-Plex-Device-Name': f"{browser or 'Browser'} (Movie Roulette)",
                'X-Plex-Model': 'Plex OAuth',
                'X-Plex-Language': 'en',
                'Accept': 'application/json'
            }

            # Request a PIN from Plex
            response = requests.post(
                'https://plex.tv/api/v2/pins?strong=true',
                headers=headers
            )

            # 201 Created is the expected success response
            if response.status_code not in (200, 201):
                logger.error(f"Failed to get PIN: {response.status_code}")
                return False, f"Failed to get PIN: {response.status_code}"

            data = response.json()
            pin_id = data.get('id')
            pin_code = data.get('code')

            # Initialize _plex_pins if it doesn't exist
            if not hasattr(self, '_plex_pins'):
                self._plex_pins = {}

            # Store PIN data in memory with expiration
            self._plex_pins[pin_id] = {
                'client_id': client_id,
                'code': pin_code,
                'created_at': time.time(),
                'expires_at': time.time() + 900,  # 15 minutes
                'authenticated': False,
                'session_token': None,
                'auth_success': False,
                'auth_token': None
            }

            # Save PINs to disk after adding a new one
            self._save_pins_to_disk()

            # Log for debugging
            logger.info(f"Stored PIN {pin_id} in memory. Current pins: {list(self._plex_pins.keys())}")

            # Construct proper Plex auth URL with all parameters
            params = {
                'clientID': client_id,
                'code': pin_code,
                'context[device][product]': 'Movie Roulette',
                'context[device][version]': '1.0',
                'context[device][platform]': platform or 'Web',
                'context[device][platformVersion]': version or '1.0',
                'context[device][device]': browser or 'Web Browser',
                'context[device][deviceName]': f"{browser or 'Browser'} (Movie Roulette)",
                'context[device][model]': 'Plex OAuth',
                'context[device][layout]': 'desktop',
                'forwardUrl': request.host_url.rstrip('/') + url_for('auth.plex_auth_success'),
                'pinID': pin_id
            }

            # Build the auth URL with parameters
            auth_url = "https://app.plex.tv/auth/#!" + "?" + "&".join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])

            logger.info(f"Generated Plex auth URL with PIN ID: {pin_id}")
            return True, {'auth_url': auth_url, 'pin_id': pin_id}
        except Exception as e:
            logger.error(f"Failed to generate Plex auth URL: {e}")
            return False, str(e)

    def validate_plex_pin(self, pin_id):
        """Validate a Plex PIN to complete authentication"""
        try:
            # Try to convert pin_id to integer if it's a string
            if isinstance(pin_id, str) and pin_id.isdigit():
                pin_id = int(pin_id)

            # Initialize _plex_pins if it doesn't exist
            if not hasattr(self, '_plex_pins'):
                self._plex_pins = {}
                # Try to load from disk
                self._load_pins_from_disk()

                if not self._plex_pins:
                    logger.warning("_plex_pins was not initialized and none loaded from disk!")
                    return False, "Authentication state lost"

            # Debug logging
            logger.info(f"Validating PIN {pin_id}. Available pins: {list(self._plex_pins.keys())}")

            # Check if we have this PIN in memory
            if pin_id not in self._plex_pins:
                logger.error(f"PIN ID {pin_id} not found in memory")
                # Try to load from disk one more time
                self._load_pins_from_disk()

                if pin_id not in self._plex_pins:
                    logger.error(f"PIN ID {pin_id} not found after reloading from disk")
                    return False, "Invalid PIN"

            pin_data = self._plex_pins[pin_id]

            # Check if PIN is already authenticated (shortcut for repeated checks)
            if pin_data.get('authenticated') and pin_data.get('auth_success'):
                logger.info(f"PIN {pin_id} already authenticated, returning session token")
                return True, pin_data.get('session_token')

            # Check if PIN is expired
            if pin_data.get('expires_at', 0) < time.time():
                logger.error(f"PIN ID {pin_id} has expired")
                return False, "PIN has expired"

            # Request headers for Plex API
            headers = {
                'X-Plex-Client-Identifier': pin_data['client_id'],
                'X-Plex-Product': 'Movie Roulette',
                'X-Plex-Version': '1.0',
                'Accept': 'application/json'
            }

            # Check the PIN status
            response = requests.get(
                f'https://plex.tv/api/v2/pins/{pin_id}',
                headers=headers
            )

            if response.status_code != 200:
                logger.error(f"Failed to validate PIN: {response.status_code}")
                return False, f"Failed to validate PIN: {response.status_code}"

            data = response.json()
            auth_token = data.get('authToken')

            if not auth_token:
                # PIN not claimed yet
                return False, "PIN not claimed yet"

            # Store the auth token in our pin data
            pin_data['auth_token'] = auth_token
            # Save to disk immediately after getting auth token
            self._save_pins_to_disk()

            # PIN claimed, process the authentication
            logger.info(f"PIN {pin_id} claimed, processing Plex authentication")
            success, result = self.process_plex_auth(auth_token, pin_id)

            # Save PIN state to disk after processing
            self._save_pins_to_disk()

            return success, result
        except Exception as e:
            logger.error(f"Error validating PIN: {e}")
            return False, str(e)

    def process_plex_auth(self, plex_token, pin_id=None):
        """Process Plex authentication and create/update user"""
        try:
            # Import here to avoid circular imports
            from plexapi.myplex import MyPlexAccount
            from plexapi.server import PlexServer

            # Get Plex account info
            account = MyPlexAccount(token=plex_token)

            # Get user details
            username = account.username
            email = account.email

            logger.info(f"Processing Plex auth for user: {username}")

            # Check if this is a server owner by connecting to our Plex server
            from utils.settings import settings

            plex_url = settings.get('plex', {}).get('url')
            plex_token_server = settings.get('plex', {}).get('token')

            is_admin_for_db = False # Always False for service users
            is_plex_server_owner = False # Flag to store in user data
            has_access = False

            if plex_url and plex_token_server:
                try:
                    # Connect to our Plex server with admin token
                    server = PlexServer(plex_url, plex_token_server)

                    # Check if user is server owner
                    server_owner_username = server.myPlexAccount().username
                    if username.lower() == server_owner_username.lower():
                        is_plex_server_owner = True # Set the flag
                        has_access = True
                        logger.info(f"User {username} is the Plex server owner.")
                    else:
                        # Check if user has access to the server
                        for user in server.myPlexAccount().users():
                            if user.username.lower() == username.lower():
                                has_access = True
                                logger.info(f"User {username} has access to Plex server")
                                break

                        # If not found in users list, check if it's a home user
                        if not has_access:
                            try:
                                home_users = server.myPlexAccount().users(home=True)
                                for user in home_users:
                                    if user.username.lower() == username.lower():
                                        has_access = True
                                        logger.info(f"User {username} is a Plex home user")
                                        break
                            except:
                                logger.warning("Failed to check Plex home users")
                except Exception as e:
                    logger.error(f"Error checking Plex server access: {e}")
                    # For safety, we'll allow login if we can't check server access
                    has_access = True
            else:
                # If no Plex server configured, allow login and default to non-admin
                has_access = True
                logger.warning("No Plex server configured, allowing login without access verification")

            if not has_access:
                logger.warning(f"User {username} doesn't have access to the Plex server")
                return False, "You don't have access to this Plex server"

            # --- Use prefixed username for internal storage/lookup ---
            internal_username = f"plex_{username}" # Prefix username for internal storage
            logger.info(f"Using internal username: '{internal_username}'")

            # Check if this specific internal user exists
            existing_user_data = self.db.get_user(internal_username)

            if existing_user_data:
                # Plex user already exists, update token/details but NEVER set is_admin=True
                logger.info(f"Found existing internal Plex user '{internal_username}'. Updating details.")
                # Update relevant fields
                self.db.users[internal_username]['plex_token'] = plex_token
                self.db.users[internal_username]['plex_email'] = email
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                self.db.users[internal_username]['is_plex_owner'] = is_plex_server_owner # Store owner status
                # Ensure is_admin remains False
                if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                     self.db.users[internal_username]['is_admin'] = False
                self.db.save_db()
            else:
                # No existing internal user found for plex_username, create a new one
                logger.info(f"Creating new internal user '{internal_username}' for Plex user '{username}'")
                # Generate a random password for local storage (not used for login)
                local_password = secrets.token_hex(16)
                success, message = self.db.add_user(
                    username=internal_username, # Use prefixed name
                    password=local_password,
                    is_admin=False, # Explicitly set False when adding
                    service_type='plex',
                    # Pass kwargs for service details
                    plex_token=plex_token,
                    plex_email=email,
                    is_plex_owner=is_plex_server_owner # Store owner status on creation
                )
                if not success:
                    # If creation failed (e.g., unexpected DB issue), return error
                    logger.error(f"Failed to add internal Plex user '{internal_username}' to local DB: {message}")
                    return False, f"Failed to create local user record: {message}"
                # Update last login after successful creation
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                self.db.save_db()

            # Create a session token (expires in 30 days) using the internal username
            session_token = self.db.create_session(internal_username)

            if not session_token:
                 logger.error(f"Failed to create session token for internal user '{internal_username}'")
                 # Update PIN data if applicable, even on session error
                 if pin_id and pin_id in self._plex_pins:
                     self._plex_pins[pin_id]['authenticated'] = True # Mark as checked
                     self._plex_pins[pin_id]['auth_success'] = False # Indicate failure
                 return False, "Failed to create session after login."

            # Update PIN data if applicable
            if pin_id and pin_id in self._plex_pins:
                self._plex_pins[pin_id]['authenticated'] = True
                self._plex_pins[pin_id]['session_token'] = session_token
                self._plex_pins[pin_id]['auth_success'] = True
                logger.info(f"Marked PIN {pin_id} as authenticated with session token for '{internal_username}'")
                # Save the updated pin data to disk
                self._save_pins_to_disk()
            else:
                 # Log even if pin_id wasn't provided or found, for clarity
                 logger.info(f"PIN update skipped for Plex auth of '{internal_username}' (PIN ID: {pin_id})")


            logger.info(f"Session created for internal Plex user: '{internal_username}'")
            return True, session_token
        except Exception as e:
            logger.error(f"Error processing Plex auth: {e}", exc_info=True)
            # Update PIN data if applicable, even on error
            if pin_id and pin_id in self._plex_pins:
                self._plex_pins[pin_id]['authenticated'] = True # Mark as checked
                self._plex_pins[pin_id]['auth_success'] = False # Indicate failure
                # Save the updated pin data to disk on error too
                self._save_pins_to_disk()
            return False, "An error occurred while processing Plex authentication"

    # Jellyfin Authentication Method
    def login_with_jellyfin(self, username, password):
        """Authenticate user against Jellyfin and create/update local user"""
        try:
            # Get Jellyfin server URL from settings
            jellyfin_url = settings.get('jellyfin', {}).get('url')
            if not jellyfin_url:
                logger.error("Jellyfin server URL is not configured in settings.")
                return False, "Jellyfin integration is not configured."

            # Prepare Jellyfin authentication request
            auth_url = f"{jellyfin_url.rstrip('/')}/Users/AuthenticateByName"
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                # Add X-Emby-Authorization header as recommended by Jellyfin docs
                'X-Emby-Authorization': f'Emby Client="Movie Roulette", Device="Web Browser", DeviceId="{str(uuid.uuid4())}", Version="1.0"'
            }
            payload = {
                'Username': username,
                'Pw': password  # Jellyfin API uses 'Pw' for password
            }

            logger.info(f"Attempting Jellyfin authentication for user: {username} at {auth_url}")

            # Make the authentication request to Jellyfin
            response = requests.post(auth_url, headers=headers, json=payload, timeout=10) # Add timeout

            # Check response status
            if response.status_code == 200:
                # Authentication successful
                jellyfin_data = response.json()
                jellyfin_user = jellyfin_data.get('User', {})
                jellyfin_token = jellyfin_data.get('AccessToken')
                jellyfin_user_id = jellyfin_user.get('Id')
                jellyfin_username = jellyfin_user.get('Name') # Use username from Jellyfin response

                if not jellyfin_token or not jellyfin_user_id or not jellyfin_username:
                    logger.error("Jellyfin authentication response missing required data (Token, UserID, UserName).")
                    return False, "Jellyfin authentication failed (invalid response)."

                logger.info(f"Jellyfin authentication successful for user: {jellyfin_username} (ID: {jellyfin_user_id})")

                # --- Use prefixed username for internal storage/lookup ---
                internal_username = f"jellyfin_{jellyfin_username}"
                logger.info(f"Using internal username: '{internal_username}'")

                # Check if this specific internal user exists
                existing_user_data = self.db.get_user(internal_username)

                is_admin_for_db = False # Always False for service users
                jellyfin_admin_userid = settings.get('jellyfin', {}).get('user_id')
                is_jellyfin_owner = (jellyfin_user_id == jellyfin_admin_userid) # Flag to store
                logger.info(f"Jellyfin user {jellyfin_username} (ID: {jellyfin_user_id}) is configured owner: {is_jellyfin_owner}")

                if existing_user_data:
                    # Jellyfin user already exists, update token/details
                    logger.info(f"Found existing internal Jellyfin user '{internal_username}'. Updating token.")
                    self.db.users[internal_username]['jellyfin_token'] = jellyfin_token
                    self.db.users[internal_username]['jellyfin_user_id'] = jellyfin_user_id # Ensure ID is stored/updated
                    self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                    self.db.users[internal_username]['is_jellyfin_owner'] = is_jellyfin_owner # Store owner status
                    # Ensure is_admin remains False
                    if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                         self.db.users[internal_username]['is_admin'] = False
                    self.db.save_db()
                else:
                    # No existing internal user found for jellyfin_username, create a new one
                    logger.info(f"Creating new internal user '{internal_username}' for Jellyfin user '{jellyfin_username}'")
                    # Generate a random password for local storage (not used for login)
                    local_password = secrets.token_hex(16)
                    success, message = self.db.add_user(
                        username=internal_username, # Use prefixed name
                        password=local_password,
                        is_admin=False, # Explicitly set False when adding
                        service_type='jellyfin',
                        # Pass kwargs for service details
                        jellyfin_token=jellyfin_token,
                        jellyfin_user_id=jellyfin_user_id,
                        is_jellyfin_owner=is_jellyfin_owner # Store owner status on creation
                    )
                    if not success:
                        # If creation failed (e.g., unexpected DB issue), return error
                        logger.error(f"Failed to add internal Jellyfin user '{internal_username}' to local DB: {message}")
                        return False, f"Failed to create local user record: {message}"
                    # Update last login after successful creation
                    self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                    self.db.save_db()


                # Create a local session token (valid for 30 days) using the internal username
                session_token = self.db.create_session(internal_username)

                if not session_token:
                     logger.error(f"Failed to create session token for internal user '{internal_username}'")
                     return False, "Failed to create session after login."

                logger.info(f"Session created for internal Jellyfin user: '{internal_username}'")
                return True, session_token

            elif response.status_code in [401, 403]:
                logger.warning(f"Jellyfin authentication failed for user {username}: Invalid credentials.")
                return False, "Invalid username or password."
            else:
                logger.error(f"Jellyfin authentication failed. Status code: {response.status_code}, Response: {response.text}")
                return False, f"Jellyfin server error (Status: {response.status_code}). Please check server logs."

        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Jellyfin server at {jellyfin_url}: {e}")
            return False, "Could not connect to Jellyfin server. Please check the URL and network."
        except Exception as e:
            logger.error(f"An unexpected error occurred during Jellyfin authentication: {e}", exc_info=True)
            return False, "An internal error occurred during authentication."

    def login_with_emby(self, username, password):
        """Login a user via Emby authentication"""
        try:
            # Import Emby service module
            from utils import emby_service # Changed import style

            # Authenticate with Emby server
            success, auth_result = emby_service.authenticate_emby_user(username, password) # Use module name

            if not success:
                logger.warning(f"Emby authentication failed for user '{username}': {auth_result}")
                return False, auth_result # Return the error message from Emby service

            # Authentication successful, get user details and API key
            emby_user_id = auth_result.get('UserId')
            emby_api_key = auth_result.get('AccessToken')
            # Use the username returned by Emby if available, otherwise the one provided
            emby_username = auth_result.get('UserName', username)

            if not emby_user_id or not emby_api_key:
                 logger.error(f"Emby authentication succeeded for '{emby_username}' but missing UserId or AccessToken in response.")
                 return False, "Emby authentication succeeded but failed to retrieve necessary user details."

            logger.info(f"Emby authentication successful for user: '{emby_username}' (ID: {emby_user_id})")

            # --- Use prefixed username for internal storage/lookup ---
            internal_username = f"emby_{emby_username}"
            logger.info(f"Using internal username: '{internal_username}'")

            # Check if this specific internal user exists
            existing_user_data = self.db.get_user(internal_username)

            if existing_user_data:
                # Emby user already exists, update token/details
                logger.info(f"Found existing internal Emby user '{internal_username}'. Updating token.")
                # Update relevant fields (ensure password isn't overwritten if it was None)
                self.db.users[internal_username]['service_token'] = emby_api_key
                self.db.users[internal_username]['service_user_id'] = emby_user_id # Ensure ID is stored/updated
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                # Determine and store owner status
                emby_admin_userid = settings.get('emby', {}).get('user_id')
                is_emby_owner = (emby_user_id == emby_admin_userid)
                self.db.users[internal_username]['is_emby_owner'] = is_emby_owner # Store owner status
                # Ensure is_admin remains False
                if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                     self.db.users[internal_username]['is_admin'] = False
                self.db.save_db()
            else:
                # No existing internal user found for emby_username, create a new one
                logger.info(f"Creating new internal user '{internal_username}' for Emby user '{emby_username}'")
                # IMPORTANT: is_admin flag in the DB should ONLY be true for the local 'admin' user.
                # Service owner status is determined dynamically for display purposes.
                is_admin_for_db = False # Always False for service users
                emby_admin_userid = settings.get('emby', {}).get('user_id')
                is_emby_owner = (emby_user_id == emby_admin_userid) # Rename variable for clarity
                logger.info(f"Emby user {emby_username} (ID: {emby_user_id}) is configured owner: {is_emby_owner}")

                success, message = self.db.add_user(
                    username=internal_username, # Use prefixed name
                    password=None, # Don't store Emby password
                    is_admin=False, # Explicitly set False when adding
                    service_type='emby',
                    # Pass kwargs for service details
                    service_user_id=emby_user_id,
                    service_token=emby_api_key,
                    is_emby_owner=is_emby_owner # Store owner status on creation
                )
                if not success:
                    # If creation failed (e.g., unexpected DB issue), return error
                    logger.error(f"Failed to add internal Emby user '{internal_username}' to local DB: {message}")
                    return False, f"Failed to create local user record: {message}"

            # Create a session token (expires in 30 days) using the internal username
            session_token = self.db.create_session(internal_username)

            if not session_token:
                 logger.error(f"Failed to create session token for internal user '{internal_username}'")
                 return False, "Failed to create session after login."


            logger.info(f"Session created for internal Emby user: '{internal_username}'")
            return True, session_token

        except ImportError:
             logger.error("Emby service utility (utils/emby_service.py) not found or 'authenticate_emby_user' function is missing.")
             return False, "Emby authentication is not properly configured (Import Error)."
        except Exception as e:
            logger.error(f"Error during Emby login for user {username}: {e}", exc_info=True)
            return False, "An internal error occurred during Emby authentication"

    # Removed start_emby_connect_auth and complete_emby_connect_auth methods


# Create a singleton instance
auth_manager = AuthManager()
