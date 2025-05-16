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
import base64

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationFormat,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
    PublicKeyCredentialParameters,
    RegistrationCredential,
    AuthenticationCredential,
    UserVerificationRequirement,
    AuthenticatorAttestationResponse,
    AuthenticatorAssertionResponse,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException

from .db import AuthDB
from utils.settings import settings

logger = logging.getLogger(__name__)

class AuthManager:
    """Manager for authentication operations"""

    def __init__(self):
        self.db = AuthDB()
        self._auth_enabled = None
        self._plex_pins = {}
        self._pins_file = Path('/tmp/movie_roulette_pins.json')
        self._load_pins_from_disk()

    @property
    def auth_enabled(self):
        """Check if authentication is enabled in settings"""
        if self._auth_enabled is not None:
            return self._auth_enabled

        env_enabled = os.environ.get('AUTH_ENABLED', '').lower() in ('true', '1', 'yes')
        settings_enabled = settings.get('auth', {}).get('enabled', False)

        self._auth_enabled = env_enabled or settings_enabled
        return self._auth_enabled

    def update_auth_enabled(self, enabled):
        """Update the auth enabled setting"""
        previous_state = self._auth_enabled
        self._auth_enabled = enabled

        logger.info(f"Authentication state changed: {previous_state} -> {enabled}")

        if not previous_state and enabled and self.needs_admin():
            logger.info("Auth enabled with no admin account - setup will be triggered")

    def is_first_run(self):
        """Check if this is the first run (no users configured)"""
        return self.auth_enabled and not self.db.has_users()

    def needs_admin(self):
        """Check if an admin user needs to be created"""
        admin_users = self.db.get_users()
        has_any_admin = any(user_data.get('is_admin', False) for user_data in admin_users.values())

        return self.auth_enabled and not has_any_admin

    def login(self, username, password):
        """Login a user"""
        success, message = self.db.verify_user(username, password)

        if not success:
            return False, message

        token = self.db.create_session(username)

        return True, token

    def logout(self, token):
        """Logout a user"""
        return self.db.delete_session(token)

    def verify_auth(self, token):
        """Verify authentication token"""
        self.db.load_db()

        if not self.auth_enabled:
            return {'username': 'admin', 'is_admin': True}

        return self.db.verify_session(token)

    def require_auth(self, f):
        """Decorator to require authentication for a route"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if not self.auth_enabled:
                return f(*args, **kwargs)

            token = request.cookies.get('auth_token')

            if not token:
                return redirect(url_for('auth.login', next=request.path))

            user_data = self.db.verify_session(token)

            if not user_data:
                return redirect(url_for('auth.login', next=request.path))

            internal_username = user_data['username']
            session['username'] = internal_username
            session['is_admin'] = user_data['is_admin']
            session['service_type'] = user_data.get('service_type', 'local')

            display_username = internal_username
            if internal_username.startswith('plex_'):
                display_username = internal_username[len('plex_'):]
            elif internal_username.startswith('emby_'):
                display_username = internal_username[len('emby_'):]
            elif internal_username.startswith('jellyfin_'):
                display_username = internal_username[len('jellyfin_'):]

            from flask import g as request_context
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
                return f(*args, **kwargs)

            token = request.cookies.get('auth_token')

            if not token:
                return redirect(url_for('auth.login', next=request.url))

            user_data = self.db.verify_session(token)

            if not user_data:
                return redirect(url_for('auth.login', next=request.url))

            if not user_data['is_admin']:
                return {"error": "Admin privileges required"}, 403

            session['username'] = user_data['username']
            session['is_admin'] = user_data['is_admin']
            session['service_type'] = user_data.get('service_type', 'local')

            return f(*args, **kwargs)

        return decorated

    def create_user(self, username, password, is_admin=False):
        """Create a new user"""
        is_service_account = False
        stack = traceback.extract_stack()
        for frame in stack:
            if 'process_plex_auth' in frame.name:
                is_service_account = True
                break

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

    def _save_pins_to_disk(self):
        """Save PIN data to disk to persist between requests"""
        try:
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

                for pin_id, pin_data in pins_data.items():
                    self._plex_pins[int(pin_id)] = pin_data

                current_time = time.time()
                expired_pins = [
                    pin_id for pin_id, data in self._plex_pins.items()
                    if data.get('expires_at', 0) < current_time
                ]

                for pin_id in expired_pins:
                    del self._plex_pins[pin_id]

                logger.info(f"Loaded {len(self._plex_pins)} valid PINs from disk")

                if expired_pins:
                    self._save_pins_to_disk()
        except Exception as e:
            logger.error(f"Error loading PINs from disk: {e}")
            self._plex_pins = {}

    def generate_plex_auth_url(self):
        """Generate URL for Plex authentication"""
        try:
            client_id = request.headers.get('X-Plex-Client-Identifier')

            if not client_id:
                client_id = str(uuid.uuid4())

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

            response = requests.post(
                'https://plex.tv/api/v2/pins?strong=true',
                headers=headers
            )

            if response.status_code not in (200, 201):
                logger.error(f"Failed to get PIN: {response.status_code}")
                return False, f"Failed to get PIN: {response.status_code}"

            data = response.json()
            pin_id = data.get('id')
            pin_code = data.get('code')

            if not hasattr(self, '_plex_pins'):
                self._plex_pins = {}

            self._plex_pins[pin_id] = {
                'client_id': client_id,
                'code': pin_code,
                'created_at': time.time(),
                'expires_at': time.time() + 900,
                'authenticated': False,
                'session_token': None,
                'auth_success': False,
                'auth_token': None
            }

            self._save_pins_to_disk()

            logger.info(f"Stored PIN {pin_id} in memory. Current pins: {list(self._plex_pins.keys())}")

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

            auth_url = "https://app.plex.tv/auth/#!" + "?" + "&".join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])

            logger.info(f"Generated Plex auth URL with PIN ID: {pin_id}")
            return True, {'auth_url': auth_url, 'pin_id': pin_id}
        except Exception as e:
            logger.error(f"Failed to generate Plex auth URL: {e}")
            return False, str(e)

    def validate_plex_pin(self, pin_id):
        """Validate a Plex PIN to complete authentication"""
        try:
            if isinstance(pin_id, str) and pin_id.isdigit():
                pin_id = int(pin_id)

            if not hasattr(self, '_plex_pins'):
                self._plex_pins = {}
                self._load_pins_from_disk()

                if not self._plex_pins:
                    logger.warning("_plex_pins was not initialized and none loaded from disk!")
                    return False, "Authentication state lost"

            logger.info(f"Validating PIN {pin_id}. Available pins: {list(self._plex_pins.keys())}")

            if pin_id not in self._plex_pins:
                logger.error(f"PIN ID {pin_id} not found in memory")
                self._load_pins_from_disk()

                if pin_id not in self._plex_pins:
                    logger.error(f"PIN ID {pin_id} not found after reloading from disk")
                    return False, "Invalid PIN"

            pin_data = self._plex_pins[pin_id]

            if pin_data.get('authenticated') and pin_data.get('auth_success'):
                logger.info(f"PIN {pin_id} already authenticated, returning session token")
                return True, pin_data.get('session_token')

            if pin_data.get('expires_at', 0) < time.time():
                logger.error(f"PIN ID {pin_id} has expired")
                return False, "PIN has expired"

            headers = {
                'X-Plex-Client-Identifier': pin_data['client_id'],
                'X-Plex-Product': 'Movie Roulette',
                'X-Plex-Version': '1.0',
                'Accept': 'application/json'
            }

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
                return False, "PIN not claimed yet"

            pin_data['auth_token'] = auth_token
            self._save_pins_to_disk()

            logger.info(f"PIN {pin_id} claimed, processing Plex authentication")
            success, result = self.process_plex_auth(auth_token, pin_id)

            self._save_pins_to_disk()

            return success, result
        except Exception as e:
            logger.error(f"Error validating PIN: {e}")
            return False, str(e)

    def process_plex_auth(self, plex_token, pin_id=None):
        """Process Plex authentication and create/update user"""
        try:
            from plexapi.myplex import MyPlexAccount
            from plexapi.server import PlexServer

            account = MyPlexAccount(token=plex_token)

            username = account.username
            email = account.email

            logger.info(f"Processing Plex auth for user: {username}")

            from utils.settings import settings

            plex_url = settings.get('plex', {}).get('url')
            plex_token_server = settings.get('plex', {}).get('token')

            is_admin_for_db = False
            is_plex_server_owner = False
            has_access = False

            if plex_url and plex_token_server:
                try:
                    server = PlexServer(plex_url, plex_token_server)

                    server_owner_username = server.myPlexAccount().username
                    if username.lower() == server_owner_username.lower():
                        is_plex_server_owner = True
                        has_access = True
                        logger.info(f"User {username} is the Plex server owner.")
                    else:
                        for user in server.myPlexAccount().users():
                            if user.username.lower() == username.lower():
                                has_access = True
                                logger.info(f"User {username} has access to Plex server")
                                break

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
                    has_access = True
            else:
                has_access = True
                logger.warning("No Plex server configured, allowing login without access verification")

            if not has_access:
                logger.warning(f"User {username} doesn't have access to the Plex server")
                return False, "You don't have access to this Plex server"

            internal_username = f"plex_{username}"
            logger.info(f"Using internal username: '{internal_username}'")

            existing_user_data = self.db.get_user(internal_username)

            if existing_user_data:
                logger.info(f"Found existing internal Plex user '{internal_username}'. Updating details.")
                self.db.users[internal_username]['plex_token'] = plex_token
                self.db.users[internal_username]['plex_email'] = email
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                self.db.users[internal_username]['is_plex_owner'] = is_plex_server_owner
                if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                     self.db.users[internal_username]['is_admin'] = False
                self.db.save_db()
            else:
                logger.info(f"Creating new internal user '{internal_username}' for Plex user '{username}'")
                local_password = secrets.token_hex(16)
                success, message = self.db.add_user(
                    username=internal_username,
                    password=local_password,
                    is_admin=False,
                    service_type='plex',
                    plex_token=plex_token,
                    plex_email=email,
                    is_plex_owner=is_plex_server_owner
                )
                if not success:
                    logger.error(f"Failed to add internal Plex user '{internal_username}' to local DB: {message}")
                    return False, f"Failed to create local user record: {message}"
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                self.db.save_db()

            session_token = self.db.create_session(internal_username, user_type='plex')

            if not session_token:
                 logger.error(f"Failed to create session token for internal user '{internal_username}'")
                 if pin_id and pin_id in self._plex_pins:
                     self._plex_pins[pin_id]['authenticated'] = True
                     self._plex_pins[pin_id]['auth_success'] = False
                 return False, "Failed to create session after login."

            if pin_id and pin_id in self._plex_pins:
                self._plex_pins[pin_id]['authenticated'] = True
                self._plex_pins[pin_id]['session_token'] = session_token
                self._plex_pins[pin_id]['auth_success'] = True
                logger.info(f"Marked PIN {pin_id} as authenticated with session token for '{internal_username}'")
                self._save_pins_to_disk()
            else:
                 logger.info(f"PIN update skipped for Plex auth of '{internal_username}' (PIN ID: {pin_id})")


            logger.info(f"Session created for internal Plex user: '{internal_username}'")
            return True, session_token
        except Exception as e:
            logger.error(f"Error processing Plex auth: {e}", exc_info=True)
            if pin_id and pin_id in self._plex_pins:
                self._plex_pins[pin_id]['authenticated'] = True
                self._plex_pins[pin_id]['auth_success'] = False
                self._save_pins_to_disk()
            return False, "An error occurred while processing Plex authentication"

    def login_with_jellyfin(self, username, password):
        """Authenticate user against Jellyfin and create/update local user"""
        try:
            jellyfin_url = settings.get('jellyfin', {}).get('url')
            if not jellyfin_url:
                logger.error("Jellyfin server URL is not configured in settings.")
                return False, "Jellyfin integration is not configured."

            auth_url = f"{jellyfin_url.rstrip('/')}/Users/AuthenticateByName"
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Emby-Authorization': f'Emby Client="Movie Roulette", Device="Web Browser", DeviceId="{str(uuid.uuid4())}", Version="1.0"'
            }
            payload = {
                'Username': username,
                'Pw': password
            }

            logger.info(f"Attempting Jellyfin authentication for user: {username} at {auth_url}")

            response = requests.post(auth_url, headers=headers, json=payload, timeout=10)

            if response.status_code == 200:
                jellyfin_data = response.json()
                jellyfin_user = jellyfin_data.get('User', {})
                jellyfin_token = jellyfin_data.get('AccessToken')
                jellyfin_user_id = jellyfin_user.get('Id')
                jellyfin_username = jellyfin_user.get('Name')

                if not jellyfin_token or not jellyfin_user_id or not jellyfin_username:
                    logger.error("Jellyfin authentication response missing required data (Token, UserID, UserName).")
                    return False, "Jellyfin authentication failed (invalid response)."

                logger.info(f"Jellyfin authentication successful for user: {jellyfin_username} (ID: {jellyfin_user_id})")

                internal_username = f"jellyfin_{jellyfin_username}"
                logger.info(f"Using internal username: '{internal_username}'")

                existing_user_data = self.db.get_user(internal_username)

                is_admin_for_db = False
                jellyfin_admin_userid = settings.get('jellyfin', {}).get('user_id')
                is_jellyfin_owner = (jellyfin_user_id == jellyfin_admin_userid)
                logger.info(f"Jellyfin user {jellyfin_username} (ID: {jellyfin_user_id}) is configured owner: {is_jellyfin_owner}")

                if existing_user_data:
                    logger.info(f"Found existing internal Jellyfin user '{internal_username}'. Updating token.")
                    self.db.users[internal_username]['jellyfin_token'] = jellyfin_token
                    self.db.users[internal_username]['jellyfin_user_id'] = jellyfin_user_id
                    self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                    self.db.users[internal_username]['is_jellyfin_owner'] = is_jellyfin_owner
                    if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                         self.db.users[internal_username]['is_admin'] = False
                    self.db.save_db()
                else:
                    logger.info(f"Creating new internal user '{internal_username}' for Jellyfin user '{jellyfin_username}'")
                    local_password = secrets.token_hex(16)
                    success, message = self.db.add_user(
                        username=internal_username,
                        password=local_password,
                        is_admin=False,
                        service_type='jellyfin',
                        jellyfin_token=jellyfin_token,
                        jellyfin_user_id=jellyfin_user_id,
                        is_jellyfin_owner=is_jellyfin_owner
                    )
                    if not success:
                        logger.error(f"Failed to add internal Jellyfin user '{internal_username}' to local DB: {message}")
                        return False, f"Failed to create local user record: {message}"
                    self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                    self.db.save_db()


                session_token = self.db.create_session(internal_username, user_type='jellyfin')

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
            from utils import emby_service

            success, auth_result = emby_service.authenticate_emby_user(username, password)

            if not success:
                logger.warning(f"Emby authentication failed for user '{username}': {auth_result}")
                return False, auth_result

            emby_user_id = auth_result.get('UserId')
            emby_api_key = auth_result.get('AccessToken')
            emby_username = auth_result.get('UserName', username)

            if not emby_user_id or not emby_api_key:
                 logger.error(f"Emby authentication succeeded for '{emby_username}' but missing UserId or AccessToken in response.")
                 return False, "Emby authentication succeeded but failed to retrieve necessary user details."

            logger.info(f"Emby authentication successful for user: '{emby_username}' (ID: {emby_user_id})")

            internal_username = f"emby_{emby_username}"
            logger.info(f"Using internal username: '{internal_username}'")

            existing_user_data = self.db.get_user(internal_username)

            if existing_user_data:
                logger.info(f"Found existing internal Emby user '{internal_username}'. Updating token.")
                self.db.users[internal_username]['service_token'] = emby_api_key
                self.db.users[internal_username]['service_user_id'] = emby_user_id
                self.db.users[internal_username]['last_login'] = datetime.now().isoformat()
                emby_admin_userid = settings.get('emby', {}).get('user_id')
                is_emby_owner = (emby_user_id == emby_admin_userid)
                self.db.users[internal_username]['is_emby_owner'] = is_emby_owner
                if 'is_admin' not in self.db.users[internal_username] or self.db.users[internal_username]['is_admin']:
                     self.db.users[internal_username]['is_admin'] = False
                self.db.save_db()
            else:
                logger.info(f"Creating new internal user '{internal_username}' for Emby user '{emby_username}'")
                is_admin_for_db = False
                emby_admin_userid = settings.get('emby', {}).get('user_id')
                is_emby_owner = (emby_user_id == emby_admin_userid)
                logger.info(f"Emby user {emby_username} (ID: {emby_user_id}) is configured owner: {is_emby_owner}")

                success, message = self.db.add_user(
                    username=internal_username,
                    password=None,
                    is_admin=False,
                    service_type='emby',
                    service_user_id=emby_user_id,
                    service_token=emby_api_key,
                    is_emby_owner=is_emby_owner
                )
                if not success:
                    logger.error(f"Failed to add internal Emby user '{internal_username}' to local DB: {message}")
                    return False, f"Failed to create local user record: {message}"

            session_token = self.db.create_session(internal_username, user_type='emby')

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

    def _get_rp_config(self):
        """Helper to get Relying Party configuration from settings."""
        auth_settings = settings.get('auth', {})
        rp_id = auth_settings.get('relying_party_id')
        rp_name = 'Movie Roulette'
        origin = auth_settings.get('relying_party_origin')

        if not rp_id:
            logger.error("Passkey Relying Party ID (relying_party_id) is not configured in settings.")
            raise ValueError("Passkey Relying Party ID (rp_id) must be configured.")
        
        if not origin:
            if request and hasattr(request, 'url_root'):
                origin = request.url_root.rstrip('/')
                logger.warning(
                    f"Passkey Relying Party Origin (relying_party_origin) not explicitly configured. "
                    f"Derived as '{origin}' from request. This is not recommended for production. "
                    f"Please set AUTH_RELYING_PARTY_ORIGIN or configure in settings.json."
                )
            else:
                logger.error("Passkey Relying Party Origin (relying_party_origin) is not configured and cannot be derived (not in request context).")
                raise ValueError("Passkey Relying Party Origin must be configured or derivable from request.")
        
        if not origin.startswith("http://") and not origin.startswith("https://"):
            logger.error(f"Invalid Relying Party Origin configured: '{origin}'. Must start with http:// or https://.")
            raise ValueError("Invalid Relying Party Origin format.")

        return rp_id, rp_name, origin

    def generate_registration_options(self, username):
        """Generate options for passkey registration."""
        user = self.db.get_user(username)
        if not user or user.get('service_type') != 'local':
            logger.warning(f"Passkey registration attempted for non-local or non-existent user: {username}")
            return None, "Passkeys can only be registered for local accounts."

        try:
            rp_id, rp_name, _ = self._get_rp_config()
        except ValueError as e:
            return None, str(e)

        existing_credentials_db = self.db.get_passkey_credentials_for_user(username)
        exclude_credentials = []
        for cred_db in existing_credentials_db:
            try:
                exclude_credentials.append(
                    PublicKeyCredentialDescriptor(
                        id=base64url_to_bytes(cred_db["id"]),
                        type=PublicKeyCredentialType.PUBLIC_KEY,
                    )
                )
            except Exception as e:
                logger.warning(f"Could not parse existing credential for exclusion for user {username}, ID {cred_db.get('id')}: {e}")


        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_id=username.encode('utf-8'),
            user_name=username,
            user_display_name=username,
            attestation=AttestationFormat.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=None,
                user_verification=UserVerificationRequirement.PREFERRED,
                resident_key=None # Or .REQUIRED
            ),
            exclude_credentials=exclude_credentials,
            timeout=30000
        )
        
        session['passkey_registration_challenge'] = bytes_to_base64url(options.challenge)
        logger.debug(f"Generated passkey registration options for user {username}, challenge_b64url: {session['passkey_registration_challenge'][:10]}...")
        return options_to_json(options), None

    def verify_registration_response(self, username, registration_response_json, passkey_name=None):
        """Verify the passkey registration response and store the credential."""
        user = self.db.get_user(username)
        if not user or user.get('service_type') != 'local':
            return False, "Passkeys can only be registered for local accounts."

        challenge = session.pop('passkey_registration_challenge', None)
        if not challenge:
            return False, "Registration challenge not found or expired."

        try:
            rp_id, _, expected_origin = self._get_rp_config()
        except ValueError as e:
            return False, str(e)
        
        try:
            registration_data = json.loads(registration_response_json)
            
            if 'name' in registration_data:
                registration_data.pop('name') 

            if 'rawId' in registration_data:
                try:
                    registration_data['raw_id'] = base64url_to_bytes(registration_data.pop('rawId'))
                except Exception as e:
                    logger.error(f"Failed to decode rawId for user {username}: {e}")
                    return False, "Invalid rawId format."

            if 'response' in registration_data and isinstance(registration_data['response'], dict):
                response_data = registration_data['response']
                if 'clientDataJSON' in response_data and isinstance(response_data['clientDataJSON'], str):
                    try:
                        response_data['client_data_json'] = base64url_to_bytes(response_data.pop('clientDataJSON'))
                    except Exception as e:
                        logger.error(f"Failed to decode clientDataJSON for user {username}: {e}")
                        return False, "Invalid clientDataJSON format."
                elif 'client_data_json' in response_data and isinstance(response_data['client_data_json'], str):
                     try:
                        response_data['client_data_json'] = base64url_to_bytes(response_data['client_data_json'])
                     except Exception as e:
                        logger.error(f"Failed to decode client_data_json (snake_case) for user {username}: {e}")
                        return False, "Invalid client_data_json format."


                if 'attestationObject' in response_data and isinstance(response_data['attestationObject'], str):
                    try:
                        response_data['attestation_object'] = base64url_to_bytes(response_data.pop('attestationObject'))
                    except Exception as e:
                        logger.error(f"Failed to decode attestationObject for user {username}: {e}")
                        return False, "Invalid attestationObject format."
                elif 'attestation_object' in response_data and isinstance(response_data['attestation_object'], str):
                    try:
                        response_data['attestation_object'] = base64url_to_bytes(response_data['attestation_object'])
                    except Exception as e:
                        logger.error(f"Failed to decode attestation_object (snake_case) for user {username}: {e}")
                        return False, "Invalid attestation_object format."

            if 'response' in registration_data and isinstance(registration_data['response'], dict):
                if 'name' in registration_data['response']:
                    registration_data['response'].pop('name')
                try:
                    instantiated_auth_response = AuthenticatorAttestationResponse(**registration_data['response'])
                    registration_data['response'] = instantiated_auth_response
                except Exception as e:
                    logger.error(f"Error creating AuthenticatorAttestationResponse from response data for user {username}: {e}")
                    return False, "Invalid format in authenticator response."
            
            parsed_response = RegistrationCredential(**registration_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse registration_response_json for user {username}")
            return False, "Invalid registration response format."
        except Exception as e:
            logger.error(f"Error instantiating RegistrationCredential for user {username}: {e}")
            return False, "Malformed registration data."

        try:
            verified_credential = verify_registration_response(
                credential=parsed_response,
                expected_challenge=base64url_to_bytes(challenge),
                expected_origin=expected_origin,
                expected_rp_id=rp_id,
                require_user_verification=False
            )
            
            credential_data_to_store = {
                "id": bytes_to_base64url(verified_credential.credential_id),
                "public_key": bytes_to_base64url(verified_credential.credential_public_key),
                "sign_count": verified_credential.sign_count,
                "transports": [t for t in parsed_response.response.transports or []],
                "created_at": datetime.now().isoformat(),
                "device_type": verified_credential.credential_device_type.value, # e.g. 'single_device' or 'multi_device'
                "backed_up": verified_credential.credential_backed_up,
                "name": passkey_name
            }

            success, msg = self.db.add_passkey_credential(username, credential_data_to_store)
            if success:
                logger.info(f"Successfully verified and stored passkey for user {username}, credential ID: {credential_data_to_store['id']}, name: {passkey_name}")
            return success, msg
        except WebAuthnException as e:
            logger.error(f"Passkey registration verification failed for user {username}: {e}")
            return False, f"Registration verification failed: {e}"
        except Exception as e:
            logger.error(f"Unexpected error during passkey registration verification for {username}: {e}", exc_info=True)
            return False, "An unexpected error occurred during registration."


    def generate_login_options(self, username=None):
        """Generate options for passkey login."""
        try:
            rp_id, _, _ = self._get_rp_config()
        except ValueError as e:
            return None, str(e)

        allow_credentials = []
        if username:
            user = self.db.get_user(username)
            if not user or user.get('service_type') != 'local':
                logger.debug(f"Passkey login options requested for non-local/unknown user {username}, allowing discoverable.")
            else:
                user_creds_db = self.db.get_passkey_credentials_for_user(username)
                for cred_db in user_creds_db:
                    try:
                        allow_credentials.append(
                            PublicKeyCredentialDescriptor(
                                id=base64url_to_bytes(cred_db["id"]),
                                type=PublicKeyCredentialType.PUBLIC_KEY,
                                transports=[AuthenticatorTransport(t) for t in cred_db.get("transports", []) if t] or None,
                            )
                        )
                    except Exception as e:
                         logger.warning(f"Could not parse credential for login options for user {username}, ID {cred_db.get('id')}: {e}")
                
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_credentials if allow_credentials else None,
            user_verification=UserVerificationRequirement.PREFERRED, # Or REQUIRED for discoverable
            timeout=30000
        )
        
        session['passkey_login_challenge'] = bytes_to_base64url(options.challenge)
        logger.debug(f"Generated passkey login options, challenge_b64url: {session['passkey_login_challenge'][:10]}...")
        return options_to_json(options), None

    def verify_login_response(self, login_response_json):
        """Verify the passkey login response and create a session."""
        challenge = session.pop('passkey_login_challenge', None)
        if not challenge:
            return False, "Login challenge not found or expired.", None

        try:
            rp_id, _, expected_origin = self._get_rp_config()
        except ValueError as e:
            return False, str(e), None
        
        try:
            login_data = json.loads(login_response_json)
            if 'rawId' in login_data:
                try:
                    login_data['raw_id'] = base64url_to_bytes(login_data.pop('rawId'))
                except Exception as e:
                    logger.error(f"Failed to decode rawId for login: {e}")
                    return False, "Invalid rawId format for login.", None

            if 'response' in login_data and isinstance(login_data['response'], dict):
                response_data = login_data['response']
                if 'clientDataJSON' in response_data and isinstance(response_data['clientDataJSON'], str):
                    try:
                        response_data['client_data_json'] = base64url_to_bytes(response_data.pop('clientDataJSON'))
                    except Exception as e:
                        logger.error(f"Failed to decode clientDataJSON for login: {e}")
                        return False, "Invalid clientDataJSON format for login.", None
                elif 'client_data_json' in response_data and isinstance(response_data['client_data_json'], str):
                     try:
                        response_data['client_data_json'] = base64url_to_bytes(response_data['client_data_json'])
                     except Exception as e:
                        logger.error(f"Failed to decode client_data_json (snake_case) for login: {e}")
                        return False, "Invalid client_data_json format for login.", None

                if 'authenticatorData' in response_data and isinstance(response_data['authenticatorData'], str):
                    try:
                        response_data['authenticator_data'] = base64url_to_bytes(response_data.pop('authenticatorData'))
                    except Exception as e:
                        logger.error(f"Failed to decode authenticatorData for login: {e}")
                        return False, "Invalid authenticatorData format for login.", None
                elif 'authenticator_data' in response_data and isinstance(response_data['authenticator_data'], str):
                    try:
                        response_data['authenticator_data'] = base64url_to_bytes(response_data['authenticator_data'])
                    except Exception as e:
                        logger.error(f"Failed to decode authenticator_data (snake_case) for login: {e}")
                        return False, "Invalid authenticator_data format for login.", None


                if 'signature' in response_data and isinstance(response_data['signature'], str):
                    try:
                        response_data['signature'] = base64url_to_bytes(response_data.pop('signature'))
                    except Exception as e:
                        logger.error(f"Failed to decode signature for login: {e}")
                        return False, "Invalid signature format for login.", None
                elif 'signature' in response_data and isinstance(response_data['signature'], str):
                    try:
                        response_data['signature'] = base64url_to_bytes(response_data['signature'])
                    except Exception as e:
                        logger.error(f"Failed to decode signature (snake_case) for login: {e}")
                        return False, "Invalid signature format for login.", None


                if 'userHandle' in response_data and response_data['userHandle'] is not None and isinstance(response_data['userHandle'], str):
                    try:
                        response_data['user_handle'] = base64url_to_bytes(response_data.pop('userHandle'))
                    except Exception as e:
                        logger.error(f"Failed to decode userHandle for login: {e}")
                        return False, "Invalid userHandle format for login.", None
                elif 'user_handle' in response_data and response_data['user_handle'] is not None and isinstance(response_data['user_handle'], str):
                    try:
                        response_data['user_handle'] = base64url_to_bytes(response_data['user_handle'])
                    except Exception as e:
                        logger.error(f"Failed to decode user_handle (snake_case) for login: {e}")
                        return False, "Invalid user_handle format for login.", None

            if 'response' in login_data and isinstance(login_data['response'], dict):
                try:
                    instantiated_auth_response = AuthenticatorAssertionResponse(**login_data['response'])
                    login_data['response'] = instantiated_auth_response
                except Exception as e:
                    logger.error(f"Error creating AuthenticatorAssertionResponse from response data for login: {e}")
                    return False, "Invalid format in authenticator assertion response.", None
            
            parsed_response = AuthenticationCredential(**login_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse login_response_json.")
            return False, "Invalid login response format.", None
        except Exception as e:
            logger.error(f"Error instantiating AuthenticationCredential: {e}")
            return False, "Malformed login data.", None

        credential_id_bytes = base64url_to_bytes(parsed_response.id)

        db_credential, username = self.db.get_passkey_credential_by_id(credential_id_bytes)

        if not db_credential or not username:
            return False, "Passkey not recognized.", None
        
        user_record = self.db.get_user(username)
        if not user_record or user_record.get('service_type') != 'local':
            logger.warning(f"Passkey login attempt for non-local user {username} via credential ID {parsed_response.id}")
            return False, "Passkey login is only for local accounts.", None

        try:
            public_key_bytes = base64url_to_bytes(db_credential["public_key"])

            verified_auth = verify_authentication_response(
                credential=parsed_response,
                expected_challenge=base64url_to_bytes(challenge),
                expected_rp_id=rp_id,
                expected_origin=expected_origin,
                credential_public_key=public_key_bytes,
                credential_current_sign_count=db_credential["sign_count"],
                require_user_verification=False
            )
            
            self.db.update_passkey_sign_count(credential_id_bytes, verified_auth.new_sign_count)
            
            session_token = self.db.create_session(username, user_type='local')
            if not session_token:
                logger.error(f"Failed to create session for user {username} after passkey login.")
                return False, "Session creation failed.", None
            
            logger.info(f"User {username} successfully logged in with passkey ID {parsed_response.id}")
            return True, "Login successful", session_token
            
        except WebAuthnException as e:
            logger.error(f"Passkey login verification failed for user {username}: {e}")
            return False, f"Login verification failed: {e}", None
        except Exception as e:
            logger.error(f"Unexpected error during passkey login for {username}: {e}", exc_info=True)
            return False, "An unexpected error occurred during login.", None

    def list_user_passkeys(self, username):
        """List passkeys for a given local user (simplified info)."""
        user = self.db.get_user(username)
        if not user or user.get('service_type') != 'local':
            return []

        credentials_db = self.db.get_passkey_credentials_for_user(username)
        passkey_list = []
        for cred in credentials_db:
            passkey_list.append({
                "id": cred["id"],
                "created_at": cred.get("created_at"),
                "device_type": cred.get("device_type", "unknown"),
                "transports": cred.get("transports", []),
                "name": cred.get("name")
            })
        return passkey_list

    def remove_user_passkey(self, username, credential_id_b64_str):
        """Remove a passkey for a local user by its base64url ID string."""
        user = self.db.get_user(username)
        if not user or user.get('service_type') != 'local':
            return False, "Passkeys can only be managed for local accounts."
        
        return self.db.delete_passkey_credential(username, credential_id_b64_str)

auth_manager = AuthManager()
