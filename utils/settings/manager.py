import os
import json
from copy import deepcopy
from .config import DEFAULT_SETTINGS, ENV_MAPPINGS

from utils.path_manager import path_manager
SETTINGS_FILE = path_manager.get_path('settings')

class Settings:
    def __init__(self):
        self.settings = self.load_settings()

    def load_settings(self):
        """Load settings with priority: ENV > file > defaults"""
        # Start with a deep copy of defaults
        settings = deepcopy(DEFAULT_SETTINGS)

        # Load from file if exists
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    file_settings = json.load(f)
                    self._deep_update(settings, file_settings)
            except Exception as e:
                print(f"Error loading settings file: {e}")

        # Apply environment variables
        settings = self._apply_env_variables(settings)
        return settings

    def _deep_update(self, target, source):
        """Recursively update nested dictionaries"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                # Handle arrays properly
                if isinstance(value, list):
                    # If it's a list, store it directly
                    target[key] = value[:]  # Make a copy of the list
                elif isinstance(value, str) and any(key == k for k in ['plex', 'jellyfin']
                                                for p in target.values()
                                                if isinstance(p, dict) and 'poster_users' in p):
                    # Handle poster users conversion
                    target[key] = [v.strip() for v in value.split(',') if v.strip()]
                else:
                    # For all other values, store directly
                    target[key] = value

        return target

    def _apply_env_variables(self, settings):
        """Apply environment variables to settings"""
        result = deepcopy(settings)

        for env_var, (path, key, converter) in ENV_MAPPINGS.items():
            value = os.getenv(env_var)
            if value is not None and value.strip():
                try:
                    parts = path.split('.')
                    target = result

                    # Navigate to the correct nested dictionary
                    for i, part in enumerate(parts[:-1]):
                        if part not in target:
                            target[part] = {}
                        target = target[part]

                    last_part = parts[-1]
                    if last_part not in target:
                        target[last_part] = {}

                    # Handle the special case of poster users
                    if 'poster_users' in path:
                        if not isinstance(target[last_part], dict):
                            target[last_part] = {}
                        target[last_part][key] = converter(value)
                    else:
                        target[last_part][key] = converter(value)

                except Exception as e:
                    print(f"Error processing environment variable {env_var}: {e}")

        return result

    def update(self, category, data):
        """
        Update settings for a given category.
        
        Args:
            category (str): The category to update (e.g., 'homepage', 'plex')
            data (dict): Dictionary of settings to update
        """
        try:

            if category not in self.settings:
                self.settings[category] = {}

            # Handle nested updates recursively
            def update_nested(target, source, base_path=''):
                for key, value in source.items():
                    current_path = f"{base_path}.{key}" if base_path else key
                    if isinstance(value, dict):
                        if key not in target:
                            target[key] = {}
                        if not self.is_field_env_controlled(f"{category}.{current_path}"):
                            update_nested(target[key], value, current_path)
                    else:
                        field_path = f"{category}.{current_path}"
                        if not self.is_field_env_controlled(field_path):
                            # Handle poster users conversion
                            if 'poster_users' in current_path and isinstance(value, str):
                                value = [v.strip() for v in value.split(',') if v.strip()]
                            target[key] = value

            update_nested(self.settings[category], data)
            
            # Special handling for service enabling/disabling
            if category in ['plex', 'jellyfin', 'overseerr', 'trakt']:
                if 'enabled' in data and not self.is_field_env_controlled(f"{category}.enabled"):
                    self.settings[category]['enabled'] = data['enabled']

            self.save_settings()
            return True

        except Exception as e:
            print(f"Error updating settings: {e}")
            raise e

    def is_field_env_controlled(self, field_path):
        """Check if a field is controlled by environment variable."""
        parts = field_path.split('.')
    
        # Handle clients category specially
        if parts[0] == 'clients':
            # If we have a compound path like "clients.apple_tv"
            if len(parts) >= 2:
                client_type = parts[1]  # apple_tv or lg_tv
            
                # If we have a field like "clients.apple_tv.enabled"
                if len(parts) >= 3:
                    if client_type == 'apple_tv':
                        if parts[2] == 'enabled' or parts[2] == 'id':
                            return bool(os.getenv('APPLE_TV_ID'))
                    elif client_type == 'lg_tv':
                        if parts[2] == 'enabled':
                            return bool(os.getenv('LGTV_IP') and os.getenv('LGTV_MAC'))
                        elif parts[2] == 'ip':
                            return bool(os.getenv('LGTV_IP'))
                        elif parts[2] == 'mac':
                            return bool(os.getenv('LGTV_MAC'))
            return False

        # Handle integrations
        if parts[0] == 'overseerr':
            has_overseerr_env = bool(os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY'))
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_overseerr_env
                return has_overseerr_env
            return False

        elif parts[0] == 'trakt':
            has_trakt_env = bool(
                os.getenv('TRAKT_CLIENT_ID') and
                os.getenv('TRAKT_CLIENT_SECRET') and
                os.getenv('TRAKT_ACCESS_TOKEN') and
                os.getenv('TRAKT_REFRESH_TOKEN')
            )
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_trakt_env
                return has_trakt_env
            return False

        elif parts[0] == 'tmdb':
            has_tmdb_env = bool(os.getenv('TMDB_API_KEY'))
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_tmdb_env
                return has_tmdb_env
            return False

        # Handle media services
        elif parts[0] == 'plex':
            has_plex_env = bool(
                os.getenv('PLEX_URL') and
                os.getenv('PLEX_TOKEN') and
                os.getenv('PLEX_MOVIE_LIBRARIES')
            )
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_plex_env
                return has_plex_env
            return False

        elif parts[0] == 'jellyfin':
            has_jellyfin_env = bool(
                os.getenv('JELLYFIN_URL') and
                os.getenv('JELLYFIN_API_KEY') and
                os.getenv('JELLYFIN_USER_ID')
            )
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_jellyfin_env
                return has_jellyfin_env
            return False

        # Check against ENV_MAPPINGS for other fields
        for env_var, (path, key, _) in ENV_MAPPINGS.items():
            if os.getenv(env_var, '').strip():
                env_path_parts = path.split('.')
                if len(parts) >= len(env_path_parts):
                    # Check if the path matches up to the length of env_path
                    if all(p1 == p2 for p1, p2 in zip(parts[:len(env_path_parts)], env_path_parts)):
                        # Check if we're looking at the key part
                        if len(parts) > len(env_path_parts):
                            return parts[len(env_path_parts)] == key
                        return True

        return False

    def get_env_overrides(self):
        """Get a map of environment variable overrides"""
        overrides = {}
        
        for env_var, (path, key, _) in ENV_MAPPINGS.items():
            env_value = os.getenv(env_var)
            if env_value and env_value.strip():  # Check both existence and non-empty
                parts = path.split('.')
                target = overrides
                
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                
                last_part = parts[-1]
                if 'poster_users' in path:
                    if last_part not in target:
                        target[last_part] = {}
                    target[last_part][key] = True
                else:
                    if last_part not in target:
                        target[last_part] = {}
                    target[last_part][key] = True

        # Special handling for integration services
        if 'overseerr' in overrides:
            if not (os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY')):
                print("Removing overseerr from overrides - missing required ENVs")
                del overrides['overseerr']

        if 'trakt' in overrides:
            if not (os.getenv('TRAKT_CLIENT_ID') and 
                   os.getenv('TRAKT_CLIENT_SECRET') and 
                   os.getenv('TRAKT_ACCESS_TOKEN') and 
                   os.getenv('TRAKT_REFRESH_TOKEN')):
                print("Removing trakt from overrides - missing required ENVs")
                del overrides['trakt']

        if 'tmdb' in overrides:
            if not os.getenv('TMDB_API_KEY'):
                print("Removing tmdb from overrides - missing required ENVs")
                del overrides['tmdb']

        print(f"Final overrides: {overrides}")
        return overrides

    def save_settings(self):
        """Save current settings to file"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            
            # Create a copy of settings to save
            settings_to_save = deepcopy(self.settings)
            
            # Clean up any None values or empty dictionaries
            self._clean_settings(settings_to_save)
            
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings_to_save, f, indent=2)
            
            print(f"Settings successfully saved to {SETTINGS_FILE}")
            
            # Verify the file was written
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    saved_content = json.load(f)
            
        except Exception as e:
            print(f"Error saving settings to {SETTINGS_FILE}: {e}")
            raise e

    def _clean_settings(self, settings):
        """Remove None values and empty dictionaries from settings"""
        if isinstance(settings, dict):
            for key in list(settings.keys()):
                if settings[key] is None:
                    del settings[key]
                elif isinstance(settings[key], dict):
                    self._clean_settings(settings[key])
                    if not settings[key]:
                        del settings[key]
        return settings

    def get(self, category, default=None):
        """Get a category of settings with an optional default"""
        return self.settings.get(category, default if default is not None else {})

    def get_all(self):
        """Get all settings"""
        return self.settings

    def is_client_env_controlled(client_type):
        if client_type == 'apple_tv':
            return bool(os.getenv('APPLE_TV_ID'))
        elif client_type == 'lg_tv':
            return bool(os.getenv('LGTV_IP') and os.getenv('LGTV_MAC'))
        return False
