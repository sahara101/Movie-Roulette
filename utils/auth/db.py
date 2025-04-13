import os
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta
import logging
from utils.settings import settings # Import settings to read lifetime

logger = logging.getLogger(__name__)

class AuthDB:
    """Database for user authentication"""
    
    def __init__(self, db_path='/app/data/auth.json'):
        self.db_path = db_path
        self.users = {}
        self.sessions = {}
        self.load_db()
    
    def load_db(self):
        """Load the auth database from disk"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.users = data.get('users', {})
                    self.sessions = data.get('sessions', {})
                    # Clean expired sessions on load
                    self._clean_expired_sessions()
                    logger.info(f"Loaded auth database with {len(self.users)} users")
            except Exception as e:
                logger.error(f"Error loading auth database: {e}")
                self.users = {}
                self.sessions = {}
        else:
            logger.info("Auth database does not exist, starting with empty database")
            self.users = {}
            self.sessions = {}
    
    def save_db(self):
        """Save the auth database to disk"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, 'w') as f:
                json.dump({
                    'users': self.users,
                    'sessions': self.sessions
                }, f, indent=2)
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

        # Hash the password only if one is provided (service accounts might not have one)
        pw_data = self._hash_password(password) if password else None

        # Create base user entry
        user_entry = {
            'password': pw_data, # Can be None for service accounts
            'is_admin': is_admin,
            'service_type': service_type,
            'created_at': datetime.now().isoformat(),
            'last_login': None,
            # Initialize known service fields to None
            'plex_token': None,
            'plex_email': None,
            'jellyfin_token': None,
            'jellyfin_user_id': None,
            'service_user_id': None, # Generic service ID (used by Emby)
            'service_token': None,   # Generic service token (used by Emby)
            'service_server_id': None, # Generic service server ID (used by Emby Connect)
            # Trakt specific fields
            'trakt_access_token': None,
            'trakt_refresh_token': None,
            'trakt_enabled': False
        }

        # Add any provided service-specific data from kwargs
        # This allows flexibility for future services too
        allowed_service_keys = ['service_user_id', 'service_token', 'service_server_id',
                                'plex_token', 'plex_email', 'jellyfin_token', 'jellyfin_user_id',
                                'is_plex_owner', 'is_jellyfin_owner', 'is_emby_owner',
                                'trakt_access_token', 'trakt_refresh_token', 'trakt_enabled'] # Added owner and Trakt flags
        for key, value in kwargs.items():
            if key in allowed_service_keys:
                user_entry[key] = value
            else:
                logger.warning(f"Ignoring unexpected keyword argument '{key}' during add_user for '{username}'")


        self.users[username] = user_entry
        
        self.save_db()
        logger.info(f"Added user: {username}")
        return True, "User created successfully"
    
    def update_password(self, username, new_password):
        """Update a user's password"""
        if username not in self.users:
            return False, "User not found"
        
        # Hash the new password
        pw_data = self._hash_password(new_password)
        
        # Update password
        self.users[username]['password'] = pw_data
        self.save_db()
        logger.info(f"Updated password for user: {username}")
        return True, "Password updated successfully"
    
    def delete_user(self, username):
        """Delete a user from the database"""
        if username not in self.users:
            return False, "User not found"
        
        # Remove user
        del self.users[username]
        
        # Remove any active sessions for this user
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
        
        # Hash the provided password with the stored salt
        verify_data = self._hash_password(password, pw_data['salt'])
        
        # Compare hashes
        if verify_data['hash'] == pw_data['hash']:
            # Update last login
            self.users[username]['last_login'] = datetime.now().isoformat()
            self.save_db()
            return True, "Authentication successful"
        
        return False, "Invalid username or password"
    
    def create_session(self, username):
        """Create a new session for a user using configured lifetime"""
        if username not in self.users:
            return None
        
        # Get session lifetime from settings (default to 86400 if not set or invalid)
        try:
            expires_in = int(settings.get('auth', {}).get('session_lifetime', 86400))
            logger.debug(f"Creating session for {username} with lifetime: {expires_in} seconds")
        except (ValueError, TypeError):
            expires_in = 86400 # Fallback to 1 day
            logger.warning(f"Invalid session_lifetime setting found, defaulting to {expires_in} seconds")
        
        # Generate a secure token
        token = secrets.token_hex(32)
        
        # Calculate expiration time
        expires = time.time() + expires_in
        
        # Create session
        self.sessions[token] = {
            'username': username,
            'created_at': time.time(),
            'expires': expires,
            'is_admin': self.users[username]['is_admin'],
            'service_type': self.users[username].get('service_type', 'local') # Copy service type, default to local if missing
        }
        
        self.save_db()
        return token
    
    def verify_session(self, token):
        """Verify if a session is valid"""
        self._clean_expired_sessions()
        
        if token not in self.sessions:
            return None
        
        session = self.sessions[token]
        
        # Check if the user still exists
        if session['username'] not in self.users:
            del self.sessions[token]
            self.save_db()
            return None

        # Get full user data to include service details
        user_data = self.users.get(session['username'], {})

        return {
            'username': session['username'],
            'is_admin': session['is_admin'],
            'service_type': session.get('service_type', 'local'), # Return service type, default to local if missing
            'expires': session['expires'],
            # Include service-specific details if they exist
            'plex_token': user_data.get('plex_token'),
            'plex_email': user_data.get('plex_email'),
            'jellyfin_token': user_data.get('jellyfin_token'),
            'jellyfin_user_id': user_data.get('jellyfin_user_id'),
            # Include Trakt details if they exist
            'trakt_access_token': user_data.get('trakt_access_token'),
            'trakt_refresh_token': user_data.get('trakt_refresh_token'),
            'trakt_enabled': user_data.get('trakt_enabled', False)
        }
    
    def extend_session(self, token):
        """Extend an existing session using configured lifetime"""
        if token not in self.sessions:
            return False
        
        # Get session lifetime from settings (default to 86400 if not set or invalid)
        try:
            expires_in = int(settings.get('auth', {}).get('session_lifetime', 86400))
        except (ValueError, TypeError):
            expires_in = 86400 # Fallback to 1 day
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
        """Get a list of all users (without password data)"""
        return {
            username: {
                'is_admin': data.get('is_admin', False), # Use .get for safety
                'service_type': data.get('service_type', 'local'),
                'created_at': data.get('created_at'),
                'last_login': data.get('last_login'),
                # Include owner flags if they exist
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
        allowed_keys = ['trakt_access_token', 'trakt_refresh_token', 'trakt_enabled'] # Define keys that can be updated this way
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
