import os
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta
import logging
import os
from utils.settings import settings
from utils.settings.manager import SETTINGS_FILE

logger = logging.getLogger(__name__)

class AuthDB:
    """Database for user authentication"""
    
    def __init__(self):
        settings_dir = os.path.dirname(SETTINGS_FILE)
        self.db_path = os.path.join(settings_dir, 'auth.json')
        logger.info(f"Using auth database path: {self.db_path}")
        self.users = {}
        self.managed_users = {}
        self.sessions = {}
        self.last_load_time = 0
        self.load_db()

    def load_db(self):
        """Load the auth database from disk if it has changed."""
        if not os.path.exists(self.db_path):
            if self.users or self.managed_users or self.sessions:
                 logger.warning("Auth database file disappeared. Resetting state.")
                 self.users = {}
                 self.managed_users = {}
                 self.sessions = {}
                 self.last_load_time = 0
            # else:
            return

        try:
            current_mtime = os.path.getmtime(self.db_path)
            if (current_mtime - self.last_load_time > 1) or not self.users:
                logger.info(f"Auth database file changed (mtime: {current_mtime} > last_load: {self.last_load_time}) or initial load. Reloading.")
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.users = data.get('users', {})
                    self.managed_users = data.get('managed_users', {})
                    self.sessions = data.get('sessions', {})
                    self._clean_expired_sessions()
                    self.last_load_time = current_mtime
                    logger.info(f"Loaded auth database with {len(self.users)} users and {len(self.managed_users)} managed users")

        except FileNotFoundError:
             logger.warning("Auth database file not found during load check. Resetting state.")
             self.users = {}
             self.managed_users = {}
             self.sessions = {}
             self.last_load_time = 0
        except Exception as e:
            logger.error(f"Error loading auth database: {e}")
            self.users = {}
            self.managed_users = {}
            self.sessions = {}
            self.last_load_time = 0

    def save_db(self):
        """Save the auth database to disk"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, 'w') as f:
                json.dump({
                    'users': self.users,
                    'managed_users': self.managed_users,
                    'sessions': self.sessions
                }, f, indent=2)
            try:
                 time.sleep(0.1)
                 self.last_load_time = os.path.getmtime(self.db_path)
            except OSError:
                 self.last_load_time = time.time()
            logger.info("Auth database saved successfully")
        except Exception as e:
            logger.error(f"Error saving auth database: {e}")

    def _hash_password(self, password, salt=None):
        """Hash a password with a salt using SHA-256"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        pw_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return {
            'hash': pw_hash,
            'salt': salt
        }
    
    def _clean_expired_sessions(self):
        """Remove expired sessions"""
        now = time.time()
        expired = [token for token, session in self.sessions.items() 
                  if session.get('expires', 0) < now]
        
        for token in expired:
            del self.sessions[token]
        
        if expired:
            logger.info(f"Cleaned {len(expired)} expired sessions")
    
    def add_user(self, username, password, is_admin=False, service_type='local', **kwargs):
        """
        Add a new user to the database.
        Accepts additional keyword arguments for service-specific data.
        """
        if username in self.users:
            return False, "Username already exists"

        pw_data = self._hash_password(password) if password else None

        user_entry = {
            'password': pw_data,
            'is_admin': is_admin,
            'service_type': service_type,
            'created_at': datetime.now().isoformat(),
            'last_login': None,
            'plex_token': None,
            'plex_email': None,
            'jellyfin_token': None,
            'jellyfin_user_id': None,
            'service_user_id': None,
            'service_token': None,
            'service_server_id': None,
            'trakt_access_token': None,
            'trakt_refresh_token': None,
            'trakt_enabled': False,
            'passkeys': []  # New field for passkey credentials
        }

        allowed_service_keys = ['service_user_id', 'service_token', 'service_server_id',
                                'plex_token', 'plex_email', 'jellyfin_token', 'jellyfin_user_id',
                                'is_plex_owner', 'is_jellyfin_owner', 'is_emby_owner',
                                'trakt_access_token', 'trakt_refresh_token', 'trakt_enabled']
        # passkeys is managed by specific methods, not generic kwargs
        for key, value in kwargs.items():
            if key in allowed_service_keys:
                user_entry[key] = value
            else:
                logger.warning(f"Ignoring unexpected keyword argument '{key}' during add_user for '{username}'")


        self.users[username] = user_entry
        
        self.save_db()
        logger.info(f"Added user: {username}")
        return True, "User created successfully"

    def add_passkey_credential(self, username, credential_data):
        """Adds a new passkey credential to the user's record."""
        if username not in self.users:
            return False, "User not found"
        
        user = self.users[username]
        if user.get('service_type') != 'local':
            logger.warning(f"Attempted to add passkey to non-local user: {username}")
            return False, "Passkeys can only be added to local accounts"

        if 'passkeys' not in user:
            user['passkeys'] = []
        
        # Ensure no duplicate credential ID for this user (or globally if desired)
        existing_ids = [cred.get('id') for cred in user['passkeys']]
        if credential_data.get('id') in existing_ids:
            logger.warning(f"Passkey credential ID {credential_data.get('id')} already exists for user {username}")
            return False, "Passkey credential already exists for this user"

        user['passkeys'].append(credential_data)
        self.save_db()
        logger.info(f"Added passkey credential for user: {username}, ID: {credential_data.get('id')}")
        return True, "Passkey credential added successfully"

    def get_passkey_credentials_for_user(self, username):
        """Retrieves all passkey credentials for a given user."""
        if username not in self.users:
            return []
        user = self.users[username]
        if user.get('service_type') != 'local':
            return [] # Only local users have passkeys
        return user.get('passkeys', [])

    def get_passkey_credential_by_id(self, credential_id_bytes):
        """
        Retrieves a specific passkey credential by its ID (bytes).
        Returns the credential and the username it belongs to.
        """
        # In this simple JSON DB, we have to iterate. For a larger system, this would be indexed.
        # Credential ID is stored as base64url-encoded string in JSON, but passed as bytes here.
        # For comparison, we might need to encode credential_id_bytes or decode stored IDs.
        # For now, let's assume credential_id_bytes is the raw bytes and stored ID is base64url string.
        # The webauthn library typically handles bytes for credential IDs.
        # We'll store it as base64url string in JSON for simplicity.
        # The library will give us bytes, so we'll need to encode it before searching.
        from webauthn.helpers import bytes_to_base64url # Use consistent helper
        credential_id_str = bytes_to_base64url(credential_id_bytes)


        for username, user_data in self.users.items():
            if user_data.get('service_type') == 'local':
                for cred in user_data.get('passkeys', []):
                    if cred.get('id') == credential_id_str:
                        # The webauthn library expects the credential's public_key and sign_count
                        # to be in specific formats (bytes for public_key).
                        # We need to ensure they are stored and retrieved correctly.
                        # For now, returning the whole dict. Conversion might be needed in AuthManager.
                        return cred, username
        return None, None

    def update_passkey_sign_count(self, credential_id_bytes, new_sign_count):
        """Updates the sign count for a given passkey credential ID (bytes)."""
        from webauthn.helpers import bytes_to_base64url # Use consistent helper
        credential_id_str = bytes_to_base64url(credential_id_bytes)


        for username, user_data in self.users.items():
            if user_data.get('service_type') == 'local':
                for cred in user_data.get('passkeys', []):
                    if cred.get('id') == credential_id_str:
                        cred['sign_count'] = new_sign_count
                        self.save_db()
                        logger.info(f"Updated sign count for passkey ID {credential_id_str} for user {username}")
                        return True
        logger.warning(f"Could not find passkey ID {credential_id_str} to update sign count.")
        return False

    def delete_passkey_credential(self, username, credential_id_str_b64):
        """Deletes a passkey credential from a user's record by its base64url ID string."""
        if username not in self.users:
            return False, "User not found"
        
        user = self.users[username]
        if user.get('service_type') != 'local':
            logger.warning(f"Attempted to delete passkey from non-local user: {username}")
            return False, "Passkeys can only be managed for local accounts"

        original_passkey_count = len(user.get('passkeys', []))
        user['passkeys'] = [cred for cred in user.get('passkeys', []) if cred.get('id') != credential_id_str_b64]

        if len(user['passkeys']) < original_passkey_count:
            self.save_db()
            logger.info(f"Deleted passkey credential ID {credential_id_str_b64} for user: {username}")
            return True, "Passkey credential deleted successfully"
        
        logger.warning(f"Passkey credential ID {credential_id_str_b64} not found for user {username}")
        return False, "Passkey credential not found"

    def update_password(self, username, new_password):
        """Update a user's password"""
        if username not in self.users:
            return False, "User not found"
        
        pw_data = self._hash_password(new_password)
        
        self.users[username]['password'] = pw_data
        self.save_db()
        logger.info(f"Updated password for user: {username}")
        return True, "Password updated successfully"
    
    def delete_user(self, username):
        """Delete a user from the database"""
        if username not in self.users:
            return False, "User not found"
        
        del self.users[username]
        
        self.sessions = {token: session for token, session in self.sessions.items()
                        if session.get('username') != username}
        
        self.save_db()
        logger.info(f"Deleted user: {username}")
        return True, "User deleted successfully"
    
    def verify_user(self, username, password):
        """Verify user credentials"""
        if username not in self.users:
            return False, "Invalid username or password"
        
        user = self.users[username]
        pw_data = user['password']
        
        verify_data = self._hash_password(password, pw_data['salt'])
        
        if verify_data['hash'] == pw_data['hash']:
            self.users[username]['last_login'] = datetime.now().isoformat()
            self.save_db()
            return True, "Authentication successful"
        
        return False, "Invalid username or password"

    def add_managed_user(self, username, password, plex_user_id):
        """Add a new managed user."""
        if username in self.managed_users:
            return False, "Managed username already exists"
        if not isinstance(password, str) or len(password) < 6:
            return False, "Password must be at least 6 characters long"
        if not plex_user_id:
             return False, "Plex User ID is required"

        if self.is_plex_user_added(plex_user_id):
            return False, f"Plex User ID {plex_user_id} is already associated with another managed user."

        password_data = self._hash_password(password)

        self.managed_users[username] = {
            'password': password_data,
            'plex_user_id': plex_user_id,
            'created_at': datetime.now().isoformat(),
            'last_login': None,
            'trakt_access_token': None,
            'trakt_refresh_token': None,
            'trakt_enabled': False
        }
        self.save_db()
        logger.info(f"Added managed user: {username} (Plex ID: {plex_user_id})")
        return True, "Managed user created successfully"

    def get_all_managed_users(self):
        """Get a list of all managed users (without password data)."""
        return {
            username: {
                'plex_user_id': data.get('plex_user_id'),
                'created_at': data.get('created_at'),
                'last_login': data.get('last_login'),
                'trakt_enabled': data.get('trakt_enabled', False)
            }
            for username, data in self.managed_users.items()
        }

    def get_managed_user_by_username(self, username):
        """Get full data for a specific managed user."""
        return self.managed_users.get(username)

    def is_plex_user_added(self, plex_user_id):
        """Check if a Plex User ID is already associated with a managed user."""
        return any(user.get('plex_user_id') == plex_user_id for user in self.managed_users.values())

    def delete_managed_user(self, username):
        """Delete a managed user by username."""
        if username not in self.managed_users:
            return False, "Managed user not found"

        del self.managed_users[username]

        self.sessions = {token: session for token, session in self.sessions.items()
                        if session.get('username') != username or session.get('user_type') != 'plex_managed'}

        self.save_db()
        logger.info(f"Deleted managed user: {username}")
        return True, "Managed user deleted successfully"

    def verify_managed_user_password(self, username, password):
        """Verify managed user password."""
        if username not in self.managed_users:
            return False, "Invalid username or password", None

        user = self.managed_users[username]
        
        if 'password' not in user:
            logger.warning(f"Attempt to login with password for managed user '{username}' who has no password record (likely old PIN user).")
            return False, "Account not configured for password login. Please update user via settings.", None

        password_data = user['password']

        verify_data = self._hash_password(password, password_data['salt'])

        if verify_data['hash'] == password_data['hash']:
            self.managed_users[username]['last_login'] = datetime.now().isoformat()
            self.save_db()
            logger.info(f"Managed user {username} authenticated successfully.")
            return True, "Authentication successful", user.get('plex_user_id')

        logger.warning(f"Failed password authentication attempt for managed user: {username}")
        return False, "Invalid username or password", None

    def update_managed_user_password(self, username, new_password):
        """Update a managed user's password."""
        if username not in self.managed_users:
            return False, "Managed user not found"
        if not isinstance(new_password, str) or len(new_password) < 6:
            return False, "Password must be at least 6 characters long"

        password_data = self._hash_password(new_password)
        self.managed_users[username]['password'] = password_data
        self.save_db()
        logger.info(f"Updated password for managed user: {username}")
        return True, "Password updated successfully"

    def update_managed_user_data(self, username, data_to_update):
        """Update specific fields for a managed user (e.g., Trakt settings)."""
        if username not in self.managed_users:
            return False, "Managed user not found"

        user = self.managed_users[username]
        allowed_keys = ['trakt_access_token', 'trakt_refresh_token', 'trakt_enabled']
        updated = False

        for key, value in data_to_update.items():
            if key in allowed_keys:
                user[key] = value
                updated = True
                logger.debug(f"Updating managed user '{username}': set '{key}' to '{value}'")
            else:
                logger.warning(f"Attempted to update disallowed key '{key}' for managed user '{username}' via update_managed_user_data")

        if updated:
            self.save_db()
            logger.info(f"Updated data for managed user: {username}")
            return True, "Managed user data updated successfully"
        else:
            return False, "No valid fields provided for update"

    def create_session(self, username, user_type='local', plex_user_id=None):
        """Create a new session for a user (regular or managed) using configured lifetime"""
        is_admin = False
        service_type = 'local'

        if user_type == 'plex_managed':
            if username not in self.managed_users:
                logger.error(f"Attempted to create session for non-existent managed user: {username}")
                return None
            is_admin = False
            service_type = 'plex_managed'
            if not plex_user_id:
                 logger.error(f"Missing plex_user_id when creating session for managed user: {username}")
                 return None
        elif user_type == 'local':
            if username not in self.users:
                logger.error(f"Attempted to create session for non-existent regular user: {username}")
                return None
            user_data = self.users[username]
            is_admin = user_data.get('is_admin', False)
            service_type = user_data.get('service_type', 'local')

        else:
            if username in self.users and self.users[username].get('service_type') == user_type:
                 user_data = self.users[username]
                 is_admin = user_data.get('is_admin', False)
                 service_type = user_type
                 logger.debug(f"Creating session for known service user type: {user_type}")
            else:
                 logger.error(f"Invalid or unhandled user_type '{user_type}' provided to create_session for user '{username}'")
                 return None

        try:
            expires_in = int(settings.get('auth', {}).get('session_lifetime', 86400))
            logger.debug(f"Creating session for {username} with lifetime: {expires_in} seconds")
        except (ValueError, TypeError):
            expires_in = 86400
            logger.warning(f"Invalid session_lifetime setting found, defaulting to {expires_in} seconds")
        
        token = secrets.token_hex(32)
        
        expires = time.time() + expires_in
        
        self.sessions[token] = {
            'username': username,
            'created_at': time.time(),
            'expires': expires,
            'username': username,
            'user_type': user_type,
            'is_admin': is_admin,
            'service_type': service_type,
            'plex_user_id': plex_user_id if user_type == 'plex_managed' else None
        }

        self.save_db()
        return token
    
    def verify_session(self, token):
        """Verify if a session is valid"""
        self._clean_expired_sessions()

        if token not in self.sessions:
            return None

        session = self.sessions[token]
        username = session['username']
        user_type = session.get('user_type', 'local')

        user_exists = False
        user_data = {}
        if user_type == 'plex_managed':
            if username in self.managed_users:
                user_exists = True
                user_data = self.managed_users[username]
            else:
                 logger.warning(f"Session token {token} references non-existent managed user {username}. Deleting session.")
        elif user_type == 'local':
             if username in self.users:
                 user_exists = True
                 user_data = self.users[username]
             else:
                 logger.warning(f"Session token {token} references non-existent regular user {username}. Deleting session.")

        else:
             if username in self.users and self.users[username].get('service_type') == user_type:
                 user_exists = True
                 user_data = self.users[username]
                 logger.debug(f"Verifying session for service user type: {user_type}")
             else:
                 logger.error(f"Session token {token} has invalid or unknown user_type '{user_type}' for user '{username}'. Deleting session.")


        if not user_exists:
            del self.sessions[token]
            self.save_db()
            return None

        session_info = {
            'username': username,
            'user_type': user_type,
            'is_admin': session.get('is_admin', False),
            'service_type': session.get('service_type', 'local'),
            'expires': session['expires'],
            'plex_user_id': session.get('plex_user_id')
        }

        if user_type == 'local':
            session_info.update({
                'plex_token': user_data.get('plex_token'),
                'plex_email': user_data.get('plex_email'),
                'jellyfin_token': user_data.get('jellyfin_token'),
                'jellyfin_user_id': user_data.get('jellyfin_user_id'),
                'service_user_id': user_data.get('service_user_id'),
                'service_token': user_data.get('service_token'),
                'service_server_id': user_data.get('service_server_id'),
                'trakt_access_token': user_data.get('trakt_access_token'),
                'trakt_refresh_token': user_data.get('trakt_refresh_token'),
                'trakt_enabled': user_data.get('trakt_enabled', False)
            })

        return session_info

    def extend_session(self, token):
        """Extend an existing session using configured lifetime"""
        if token not in self.sessions:
            return False
        
        try:
            expires_in = int(settings.get('auth', {}).get('session_lifetime', 86400))
        except (ValueError, TypeError):
            expires_in = 86400
            logger.warning(f"Invalid session_lifetime setting found, defaulting to {expires_in} seconds.")
        
        self.sessions[token]['expires'] = time.time() + expires_in
        self.save_db()
        return True
    
    def delete_session(self, token):
        """Delete a session"""
        if token in self.sessions:
            del self.sessions[token]
            self.save_db()
            return True
        return False
    
    def get_users(self):
        """Get a list of all regular users (without password data)"""
        return {
            username: {
                'is_admin': data.get('is_admin', False),
                'service_type': data.get('service_type', 'local'),
                'created_at': data.get('created_at'),
                'last_login': data.get('last_login'),
                'is_plex_owner': data.get('is_plex_owner', False),
                'is_jellyfin_owner': data.get('is_jellyfin_owner', False),
                'is_emby_owner': data.get('is_emby_owner', False)
            }
            for username, data in self.users.items()
        }

    def get_user(self, username):
        """Get the full data for a specific user."""
        return self.users.get(username)
    
    def has_users(self):
        """Check if there are any users in the database"""
        return len(self.users) > 0
    
    def has_admin(self):
        """Check if there are any admin users"""
        return any(user.get('is_admin', False) for user in self.users.values())

    def update_user_data(self, username, data_to_update):
        """Update specific fields for a user."""
        if username not in self.users:
            return False, "User not found"

        user = self.users[username]
        allowed_keys = ['trakt_access_token', 'trakt_refresh_token', 'trakt_enabled']
        updated = False

        for key, value in data_to_update.items():
            if key in allowed_keys:
                user[key] = value
                updated = True
            else:
                logger.warning(f"Attempted to update disallowed key '{key}' for user '{username}' via update_user_data")

        if updated:
            self.save_db()
            logger.info(f"Updated data for user: {username}")
            return True, "User data updated successfully"
        else:
            return False, "No valid fields provided for update"
