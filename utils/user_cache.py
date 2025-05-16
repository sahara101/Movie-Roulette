import os
import logging
import json
from flask import session, g

logger = logging.getLogger(__name__)

class UserCacheManager:
    """Manages the relationship between users and their cache files"""

    def __init__(self, app):
        self.app = app
        self.users_data_dir = '/app/data/user_data'
        os.makedirs(self.users_data_dir, exist_ok=True)

    def get_user_cache_path(self, username, service='plex', cache_type='unwatched'):
        """Get the path to a user's cache file"""
        if not username:
            if service == 'plex':
                if cache_type == 'unwatched':
                    return '/app/data/plex_unwatched_movies.json'
                else:
                    return '/app/data/plex_all_movies.json'
            elif service == 'jellyfin':
                return '/app/data/jellyfin_all_movies.json'
            elif service == 'emby':
                return '/app/data/emby_all_movies.json'

        user_dir = os.path.join(self.users_data_dir, username)
        os.makedirs(user_dir, exist_ok=True)

        if service == 'plex':
            if cache_type == 'unwatched':
                return os.path.join(user_dir, 'plex_unwatched_movies.json')
            else:
                return os.path.join(user_dir, 'plex_all_movies.json')
        elif service == 'jellyfin':
            return os.path.join(user_dir, 'jellyfin_all_movies.json')
        elif service == 'emby':
            return os.path.join(user_dir, 'emby_all_movies.json')

        return os.path.join(user_dir, f'{service}_{cache_type}_movies.json')

    def get_user_stats(self, username):
        """Get statistics about a user's caches"""
        stats = {
            'username': username,
            'plex': {
                'unwatched_count': 0,
                'all_count': 0,
                'cache_exists': False
            },
            'jellyfin': {
                'all_count': 0,
                'cache_exists': False
            },
            'emby': {
                'all_count': 0,
                'cache_exists': False
            }
        }

        if username.startswith('plex_') or username.startswith('plex_managed_'):
            plex_unwatched_user_path = self.get_user_cache_path(username, 'plex', 'unwatched')
            
            if os.path.exists(plex_unwatched_user_path):
                stats['plex']['cache_exists'] = True
                try:
                    with open(plex_unwatched_user_path, 'r') as f:
                        data = json.load(f)
                        stats['plex']['unwatched_count'] = len(data)
                except Exception as e:
                    logger.error(f"Error reading Plex unwatched cache for {username}: {e}")
                    stats['plex']['unwatched_count'] = 0 
                    stats['plex']['cache_exists'] = False 
            else:
                stats['plex']['cache_exists'] = False
                stats['plex']['unwatched_count'] = 0

            global_plex_all_path = self.get_user_cache_path(None, 'plex', 'all')
            if os.path.exists(global_plex_all_path):
                try:
                    with open(global_plex_all_path, 'r') as f:
                        data = json.load(f)
                        stats['plex']['all_count'] = len(data)
                except Exception as e:
                    logger.error(f"Error reading global Plex all_movies cache for user-stat {username}: {e}")
                    stats['plex']['all_count'] = 0 
            else:
                stats['plex']['all_count'] = 0

        jellyfin_path = self.get_user_cache_path(username, 'jellyfin')
        if os.path.exists(jellyfin_path):
            stats['jellyfin']['cache_exists'] = True
            try:
                with open(jellyfin_path, 'r') as f:
                    data = json.load(f)
                    stats['jellyfin']['all_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading Jellyfin cache for {username}: {e}")

        emby_path = self.get_user_cache_path(username, 'emby')
        if os.path.exists(emby_path):
            stats['emby']['cache_exists'] = True
            try:
                with open(emby_path, 'r') as f:
                    data = json.load(f)
                    stats['emby']['all_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading Emby cache for {username}: {e}")

        return stats

    def list_cached_users(self):
        """List all users who have cache files"""
        try:
            if not os.path.exists(self.users_data_dir):
                return []

            return [
                dir_name for dir_name in os.listdir(self.users_data_dir)
                if os.path.isdir(os.path.join(self.users_data_dir, dir_name))
            ]
        except Exception as e:
            logger.error(f"Error listing cached users: {e}")
            return []

    def clear_user_cache(self, username, service=None):
        """Clear a user's cache files"""
        if not username:
            return False

        user_dir = os.path.join(self.users_data_dir, username)
        if not os.path.exists(user_dir):
            return False

        try:
            if service:
                if service == 'plex':
                    cache_files = [
                        self.get_user_cache_path(username, 'plex', 'unwatched'),
                        self.get_user_cache_path(username, 'plex', 'all')
                    ]
                elif service in ['jellyfin', 'emby']:
                    cache_files = [self.get_user_cache_path(username, service)]

                for cache_file in cache_files:
                    if os.path.exists(cache_file):
                        os.remove(cache_file)
                        logger.info(f"Removed cache file {cache_file} for user {username}")
            else:
                for file_name in os.listdir(user_dir):
                    if file_name.endswith('.json'):
                        file_path = os.path.join(user_dir, file_name)
                        os.remove(file_path)
                        logger.info(f"Removed cache file {file_path} for user {username}")

            return True
        except Exception as e:
            logger.error(f"Error clearing cache for user {username}: {e}")
            return False
