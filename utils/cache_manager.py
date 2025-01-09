import time
import json
import os
import logging
from threading import Thread, Lock
from functools import lru_cache

from utils.path_manager import path_manager
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, plex_service, cache_file_path, socketio, app, update_interval=600):
        self.plex_service = plex_service
        self.cache_file_path = cache_file_path
        self.all_movies_cache_path = path_manager.get_path('plex_all_movies')
        self.socketio = socketio
        self.app = app
        self.update_interval = update_interval
        self.running = False
        self.is_updating = False
        self.last_update = 0
        self._cache_lock = Lock()
        self._movies_memory_cache = []
        self._initializing = False

        # Don't initialize if PlexService is building cache
        if os.path.exists(self.cache_file_path):
            logger.info("Loading existing cache into memory")
            self._init_memory_cache()
            self.last_update = time.time()  # Set last update to now
        else:
            logger.info("Cache file doesn't exist, memory cache will stay empty until built")
            self._movies_memory_cache = []

        # Build all movies cache if missing
        if not os.path.exists(self.all_movies_cache_path):
            logger.info("All movies cache missing - building at startup...")
            Thread(target=self.cache_all_plex_movies, daemon=True).start()

    def start_cache_build(self):
        """Start the cache building process with progress updates"""
        if self._initializing:
            return

        self._initializing = True
        try:
            all_movies = []
            for library in self.plex_service.libraries:
                all_movies.extend(library.search(unwatched=True))

            total_movies = len(all_movies)
            self._movies_memory_cache = []

            for i, movie in enumerate(all_movies, 1):
                metadata = self.plex_service._fetch_metadata(movie.ratingKey)
                movie_data = self.plex_service._basic_movie_data(movie)
                if metadata:
                    self.plex_service._enrich_with_metadata(movie_data, metadata)
                self._movies_memory_cache.append(movie_data)

                progress = (i / total_movies) * 0.90
                self.socketio.emit('loading_progress', {
                    'progress': progress,
                    'current': i,
                    'total': total_movies,
                    'status': 'Building cache'
                }, namespace='/')

            # Save cache before final progress updates
            self._save_cache_to_disk()
            time.sleep(1)

            self.socketio.emit('loading_progress', {
                'progress': 0.95,
                'current': total_movies,
                'total': total_movies,
                'status': 'Building cache'
            }, namespace='/')

            self._initializing = False
            time.sleep(1)

            self.socketio.emit('loading_progress', {
                'progress': 1.0,
                'current': total_movies,
                'total': total_movies,
                'status': 'Finished cache'
            }, namespace='/')

            self.socketio.emit('loading_complete', namespace='/')

        except Exception as e:
            logger.error(f"Error building cache: {e}")
            self._initializing = False

    def _init_memory_cache(self):
        """Initialize in-memory cache from disk cache"""
        try:
            if os.path.exists(self.cache_file_path):
                with open(self.cache_file_path, 'r') as f:
                    self._movies_memory_cache = json.load(f)
                    logger.info(f"Loaded {len(self._movies_memory_cache)} movies into memory cache")
        except Exception as e:
            logger.error(f"Error initializing memory cache: {e}")
            self._movies_memory_cache = []

    def start(self):
        """Start the cache manager background thread"""
        logger.info("Starting cache manager background thread")
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()
        logger.info("Cache manager background thread started")

    def stop(self):
        """Stop the cache manager"""
        self.running = False

    @lru_cache(maxsize=128)
    def _get_movie_data(self, movie_id):
        """Cached movie data retrieval"""
        return self._movies_memory_cache.get(str(movie_id))

    def _update_loop(self):
        """Background thread that periodically checks for changes"""
        logger.info("Update loop started")
        while self.running:
            try:
                current_time = time.time()
                logger.debug(f"Current time: {current_time}, Last update: {self.last_update}, Interval: {self.update_interval}")

                # Only check if interval passed AND cache exists
                if os.path.exists(self.cache_file_path) and (current_time - self.last_update >= self.update_interval):
                    logger.info("Update interval reached, checking for changes")
                    with self._cache_lock:
                        self.check_for_changes()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in update loop: {e}", exc_info=True)
                time.sleep(5)

    def check_for_changes(self):
        """Check for changes in the library and update both caches if needed"""
        if self.is_updating:
            logger.info("Update already in progress, skipping")
            return

        if not os.path.exists(self.cache_file_path):
            logger.info("Cache file doesn't exist, skipping check")
            return
        try:
            logger.info("Starting to check for library changes...")
            self.is_updating = True

            # Update all movies cache first
            self.cache_all_plex_movies()

            # Get current unwatched movies directly
            current_unwatched = set()
            for library in self.plex_service.libraries:
                logger.info(f"Checking library {library.title} for unwatched movies...")
                for movie in library.search(unwatched=True):
                    current_unwatched.add(str(movie.ratingKey))

            logger.info(f"Found {len(current_unwatched)} currently unwatched movies")

            # Get cached unwatched movie IDs from memory cache
            cached_unwatched = {str(movie['id']) for movie in self._movies_memory_cache}
            logger.info(f"Have {len(cached_unwatched)} cached unwatched movies")

            # Find differences
            newly_watched = cached_unwatched - current_unwatched
            newly_unwatched = current_unwatched - cached_unwatched

            if newly_watched or newly_unwatched:
                logger.info(f"Found {len(newly_watched)} newly watched and {len(newly_unwatched)} newly unwatched movies")

                # Remove watched movies from cache
                self._movies_memory_cache = [movie for movie in self._movies_memory_cache
                                        if str(movie['id']) not in newly_watched]

                # Add new unwatched movies to cache
                for movie_id in newly_unwatched:
                    logger.info(f"Adding newly unwatched movie: {movie_id}")
                    for library in self.plex_service.libraries:
                        try:
                            movie = library.fetchItem(int(movie_id))
                            if movie:
                                movie_data = self.plex_service.get_movie_data(movie)
                                if movie_data:
                                    self._movies_memory_cache.append(movie_data)
                                    logger.info(f"Added movie: {movie_data['title']}")
                                break
                        except Exception as e:
                            logger.error(f"Error adding movie {movie_id}: {e}")

                # Save updated cache to disk
                self._save_cache_to_disk()
                logger.info("Cache updated successfully")
            else:
                logger.info("No changes detected")

        except Exception as e:
            logger.error(f"Error checking for changes: {e}", exc_info=True)
        finally:
            self.is_updating = False
            self.last_update = time.time()

    def _save_cache_to_disk(self):
        """Save both caches to disk with error handling"""
        try:
            with open(self.cache_file_path, 'w') as f:
                json.dump(self._movies_memory_cache, f)
        except Exception as e:
            logger.error(f"Error saving cache to disk: {e}")

    def cache_all_plex_movies(self):
        """Cache all movies (watched and unwatched) for Plex"""
        try:
            # If already building, skip
            if getattr(self, '_building_all_cache', False):
                logger.info("All movies cache build already in progress, skipping")
                return

            self._building_all_cache = True
            logger.info("Starting to cache all Plex movies in background...")

            def build_cache():
                try:
                    all_movies = []
                    total_movies = 0

                    for library in self.plex_service.libraries:
                        logger.info(f"Processing library: {library.title}")
                        library_movies = list(library.all())
                        total_movies += len(library_movies)

                        for movie in library_movies:
                            try:
                                movie_data = self.plex_service.get_movie_data(movie)
                                if movie_data:
                                    all_movies.append(movie_data)
                            except Exception as e:
                                logger.error(f"Error processing movie {movie.title}: {e}")

                    # Save to disk atomically
                    temp_path = f"{self.all_movies_cache_path}.tmp"
                    with open(temp_path, 'w') as f:
                        json.dump(all_movies, f)
                    os.replace(temp_path, self.all_movies_cache_path)

                    logger.info(f"Successfully cached {len(all_movies)} total Plex movies")
                except Exception as e:
                    logger.error(f"Error building all movies cache: {e}")
                finally:
                    self._building_all_cache = False

            # Start background thread
            Thread(target=build_cache, daemon=True).start()

        except Exception as e:
            logger.error(f"Error initiating all movies cache: {e}")
            self._building_all_cache = False

    @lru_cache(maxsize=1)
    def get_all_plex_movies(self):
        """Get all movies (watched and unwatched) from cache with caching"""
        try:
            if os.path.exists(self.all_movies_cache_path):
                with open(self.all_movies_cache_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error reading all movies cache: {e}")
        return []

    def force_refresh(self):
        """Force a complete cache refresh"""
        try:
            logger.info("Starting forced cache refresh")
            with self._cache_lock:
                self.plex_service.refresh_cache(force=True)
                self.cache_all_plex_movies()
                self._init_memory_cache()  # Reload memory cache
                self.last_update = time.time()
            logger.info("Forced refresh completed successfully")
        except Exception as e:
            logger.error(f"Error during forced refresh: {e}")

    def get_cache_status(self):
        """Get current cache status"""
        return {
            'movies_cached': len(self._movies_memory_cache),
            'last_update': self.last_update,
            'is_updating': self.is_updating,
            'cache_file_exists': os.path.exists(self.cache_file_path),
            'all_movies_cache_exists': os.path.exists(self.all_movies_cache_path)
        }

    def get_cached_movies(self):
        """Get cached movies from memory cache"""
        try:
            return self._movies_memory_cache
        except Exception as e:
            logger.error(f"Error getting cached movies: {e}")
            return []

    def get_all_unwatched_movies(self, progress_callback=None):
        """Get all unwatched movies with progress tracking"""
        try:
            if progress_callback:
                progress_callback(1.0)
            return list(self._movies_memory_cache.values())
        except Exception as e:
            logger.error(f"Error getting all unwatched movies: {e}")
            return []
