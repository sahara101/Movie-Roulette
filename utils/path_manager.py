import os
import appdirs
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class PathManager:
    def __init__(self):
        # Set up application directories
        self.app_name = "MovieRoulette"
        self.app_author = "MovieRoulette"
        
        # Get the base data directory in user's home
        self.base_dir = Path(appdirs.user_data_dir(self.app_name, self.app_author))
        
        # Create all required directories
        self.create_directories()
        
        # Define all file paths
        self.paths = {
            'plex_unwatched': self.base_dir / 'plex_unwatched_movies.json',
            'plex_all_movies': self.base_dir / 'plex_all_movies.json',
            'plex_metadata': self.base_dir / 'plex_metadata_cache.json',
            'jellyfin_movies': self.base_dir / 'jellyfin_all_movies.json',
            'emby_movies': self.base_dir / 'emby_all_movies.json',
            'trakt_tokens': self.base_dir / 'trakt_tokens.json',
            'trakt_watched': self.base_dir / 'trakt_watched_movies.json',
            'settings': self.base_dir / 'settings.json',
            'current_movie': self.base_dir / 'current_movie.json',
            'lgtv_store': self.base_dir / 'lgtv_store.json',
            'adbkey': self.base_dir / 'adbkey',
            'pyatv_config': self.base_dir / 'pyatv.conf',
            'version_info': self.base_dir / 'version_info.json',
            'update_check': self.base_dir / 'last_update_check.json',
            'jellyseerr_state': self.base_dir / 'jellyseerr_state.json',
            'ombi_state': self.base_dir / 'ombi_state.json',
            'overseerr_state': self.base_dir / 'overseerr_state.json'
        }

    def create_directories(self):
        """Create necessary directories if they don't exist"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created data directory at {self.base_dir}")
        except Exception as e:
            logger.error(f"Error creating directories: {e}")
            raise

    def get_path(self, key):
        """Get the full path for a given key"""
        if key not in self.paths:
            raise KeyError(f"Unknown path key: {key}")
        return str(self.paths[key])

    def migrate_from_docker(self, docker_data_path='/app/data'):
        """Migrate existing data from Docker paths to new locations"""
        for key, new_path in self.paths.items():
            old_path = Path(docker_data_path) / new_path.name
            if old_path.exists():
                try:
                    import shutil
                    shutil.copy2(old_path, new_path)
                    logger.info(f"Migrated {old_path} to {new_path}")
                except Exception as e:
                    logger.error(f"Error migrating {old_path}: {e}")

# Create a singleton instance
path_manager = PathManager()
