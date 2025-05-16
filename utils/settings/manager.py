import os
import json
import re
from copy import deepcopy
from .config import DEFAULT_SETTINGS, ENV_MAPPINGS, AUTH_ENV_MAPPINGS, AUTH_SETTINGS

SETTINGS_FILE = '/app/data/settings.json'

class Settings:
    def __init__(self):
        self._pattern_cache = {}
        self.settings = self.load_settings()

    def get(self, category, default=None):
        """Get a category of settings with an optional default"""
        return self.settings.get(category, default if default is not None else {})

    def get_all(self):
        """Get all settings"""
        return self.settings

    def load_settings(self):
        """Load settings with priority: ENV > file > defaults"""
        current_settings = deepcopy(DEFAULT_SETTINGS)
        self._deep_update(current_settings, deepcopy(AUTH_SETTINGS))

        file_values_on_disk = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    file_values_on_disk = json.load(f)
            except Exception as e:
                print(f"Error loading settings file {SETTINGS_FILE}: {e}. Using defaults.")
        
        self._deep_update(current_settings, file_values_on_disk)

        save_needed = False
        if not os.path.exists(SETTINGS_FILE):
            save_needed = True
        else:
            if self._is_structurally_different(current_settings, file_values_on_disk):
                save_needed = True
        
        if save_needed:
            try:
                print(f"Updating {SETTINGS_FILE} to ensure all default keys are present.")
                os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
                with open(SETTINGS_FILE, 'w') as f_write:
                    json.dump(self._clean_settings(deepcopy(current_settings)), f_write, indent=2)
                print(f"Settings file updated at {SETTINGS_FILE}")
            except Exception as e:
                print(f"Error saving updated settings to {SETTINGS_FILE}: {e}")

        runtime_settings = self._apply_env_variables(deepcopy(current_settings)) 
        
        return runtime_settings

    def _is_structurally_different(self, base_struct, comparison_struct):
        """
        Checks if base_struct contains keys or nested structures that comparison_struct is missing.
        Returns True if base_struct has more/different structure, False otherwise.
        """
        for key, value in base_struct.items():
            if key not in comparison_struct:
                return True
            if isinstance(value, dict):
                if not isinstance(comparison_struct.get(key), dict):
                    return True
                if self._is_structurally_different(value, comparison_struct[key]):
                    return True
        return False

    def _deep_update(self, target, source):
        """
        Recursively update nested dictionaries. Values from source overwrite values in target.
        Keys in target that are not in source remain untouched.
        """
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            elif isinstance(value, dict):
                target[key] = deepcopy(value)
            else:
                if isinstance(value, list):
                    target[key] = value[:]
                else:
                    target[key] = value

        return target

    def _apply_env_variables(self, settings):
        """Apply environment variables to settings, including pattern matching"""
        result = deepcopy(settings)

        for env_var in os.environ:
            value = os.environ[env_var]
            if not value.strip():
                continue

            if env_var in ENV_MAPPINGS:
                path, key, converter = ENV_MAPPINGS[env_var]
                self._apply_single_env(result, path, key, value, converter)
                continue

            for pattern, (path_template, key, converter) in ENV_MAPPINGS.items():
                if not pattern.startswith('TV_'):  
                    continue
                    
                if pattern not in self._pattern_cache:
                    self._pattern_cache[pattern] = re.compile(pattern)
                
                match = self._pattern_cache[pattern].match(env_var)
                if match:
                    tv_name = match.group(1)
                    tv_name = tv_name.lower()
                    actual_path = path_template.replace('$1', tv_name)
                    self._apply_single_env(result, actual_path, key, value, converter)
 
        for env_var, (path, key, converter) in AUTH_ENV_MAPPINGS.items():
            if env_var in os.environ:
                value = os.environ[env_var]
                if value.strip():
                    self._apply_single_env(result, path, key, value, converter)
 
        return result

    def _apply_single_env(self, settings, path, key, value, converter):
        """Apply a single environment variable to settings"""
        try:
            parts = path.split('.')
            target = settings

            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]

            last_part = parts[-1]
            if last_part not in target:
                target[last_part] = {}

            if 'poster_users' in path:
                if not isinstance(target[last_part], dict):
                    target[last_part] = {}
                target[last_part][key] = converter(value)
            else:
                if 'clients.tvs.instances' in path:
                    target[last_part] = target.get(last_part, {})
                    target[last_part][key] = converter(value)
                    target[last_part]['enabled'] = True
                else:
                    target[last_part][key] = converter(value)

            if any(path.startswith(service) for service in ['plex', 'jellyfin', 'emby', 'overseerr', 'jellyseerr', 'ombi', 'trakt']):
                target['enabled'] = True

        except Exception as e:
            print(f"Error processing environment variable {path}.{key}: {e}")

    def is_field_env_controlled(self, field_path):
        """Check if a field is controlled by environment variable."""
        parts = field_path.split('.')
        if not parts:
            return False
 
        if parts[0] == 'clients':
            if len(parts) >= 2:
                if parts[1] == 'apple_tv':
                    if len(parts) >= 3:
                        if parts[2] == 'enabled' or parts[2] == 'id':
                            return bool(os.getenv('APPLE_TV_ID'))
                elif parts[1] == 'tvs' and len(parts) >= 4:
                    instance_name = parts[2]
                    field = parts[3]
                    return bool(os.getenv(f'TV_{instance_name.upper()}_{field.upper()}'))
            return False

        if parts[0] == 'overseerr':
            has_overseerr_env = bool(os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY'))
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_overseerr_env
                return has_overseerr_env
            return False

        elif parts[0] == 'jellyseerr':
            has_jellyseerr_env = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_jellyseerr_env
                return has_jellyseerr_env
            return False

        elif parts[0] == 'ombi':
            has_ombi_env = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_ombi_env
                return has_ombi_env
            return False

        elif parts[0] == 'request_services':
            has_request_service_env = bool(
                os.getenv('REQUEST_SERVICE_DEFAULT') or
                os.getenv('REQUEST_SERVICE_PLEX') or
                os.getenv('REQUEST_SERVICE_JELLYFIN') or
                os.getenv('REQUEST_SERVICE_EMBY')
            )
            if len(parts) > 1:
                if parts[1] == 'default':
                    return bool(os.getenv('REQUEST_SERVICE_DEFAULT'))
                elif parts[1] == 'plex_override':
                    return bool(os.getenv('REQUEST_SERVICE_PLEX'))
                elif parts[1] == 'jellyfin_override':
                    return bool(os.getenv('REQUEST_SERVICE_JELLYFIN'))
                elif parts[1] == 'emby_override':
                    return bool(os.getenv('REQUEST_SERVICE_EMBY'))
            return has_request_service_env

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

        elif parts[0] == 'emby':
            has_emby_env = bool(
                os.getenv('EMBY_URL') and
                os.getenv('EMBY_API_KEY') and
                os.getenv('EMBY_USER_ID')
            )
            if len(parts) > 1:
                if parts[1] == 'enabled':
                    return has_emby_env
                return has_emby_env
            return False
 
        elif parts[0] == 'auth':
            for env_var, (path, key, _) in AUTH_ENV_MAPPINGS.items():
                if os.getenv(env_var, '').strip():
                    env_path_parts = path.split('.')
                    if len(parts) == len(env_path_parts) + 1 and \
                       all(p1 == p2 for p1, p2 in zip(parts[:len(env_path_parts)], env_path_parts)) and \
                       parts[-1] == key:
                        return True
            return False
 
        for env_var, (path, key, _) in ENV_MAPPINGS.items():
            if os.getenv(env_var, '').strip():
                env_path_parts = path.split('.')
                if len(parts) >= len(env_path_parts):
                    if all(p1 == p2 for p1, p2 in zip(parts[:len(env_path_parts)], env_path_parts)):
                        if len(parts) > len(env_path_parts):
                            return parts[len(env_path_parts)] == key
                        return True

        return False

    def update(self, category, data):
        """Update settings for a given category."""
        try:
            if category not in self.settings:
                self.settings[category] = {}

            def update_nested(target, source, base_path=''):
                for key, value in source.items():
                    current_path = f"{base_path}.{key}" if base_path else key
                    if value is None or value == "undefined":
                        if key in target:
                            del target[key]
                    elif isinstance(value, dict):
                        if key not in target:
                            target[key] = {}
                        if not self.is_field_env_controlled(f"{category}.{current_path}"):
                            update_nested(target[key], value, current_path)
                    else:
                        field_path = f"{category}.{current_path}"
                        if not self.is_field_env_controlled(field_path):
                            if 'poster_users' in current_path and isinstance(value, str):
                                value = [v.strip() for v in value.split(',') if v.strip()]
                            target[key] = value

                if isinstance(target, dict):
                    empty_keys = [k for k, v in target.items() if isinstance(v, dict) and not v]
                    for k in empty_keys:
                        del target[k]

            update_nested(self.settings[category], data)
            self.save_settings()
            return True

        except Exception as e:
            print(f"Error updating settings: {e}")
            raise e

    def save_settings(self):
        """Save current settings to file"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            settings_to_save = deepcopy(self.settings)
            self._clean_settings(settings_to_save)
            
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings_to_save, f, indent=2)
                
            print(f"Settings successfully saved to {SETTINGS_FILE}")
            
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

    def get_env_overrides(self):
        """Get a map of environment variable overrides"""
        overrides = {}
        for env_var, (path, key, _) in ENV_MAPPINGS.items():
            if not env_var.startswith('TV_'):  
                env_value = os.getenv(env_var)
                if env_value and env_value.strip():
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
            else:  
                pattern = re.compile(env_var)
                for env_name in os.environ:
                    match = pattern.match(env_name)
                    if match:
                        tv_name = match.group(1).lower()  
                        target = overrides.setdefault('clients', {}).setdefault('tvs', {}).setdefault('instances', {}).setdefault(tv_name, {})
                        target[key] = True
 
        for env_var, (path, key, _) in AUTH_ENV_MAPPINGS.items():
            env_value = os.getenv(env_var)
            if env_value and env_value.strip():
                parts = path.split('.')
                target = overrides
                for part in parts:
                    target = target.setdefault(part, {})
                target[key] = True
 
        return overrides
