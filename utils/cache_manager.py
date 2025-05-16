import time
import json
import os
import logging
from threading import Thread, Lock, RLock
from functools import lru_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CacheManager:
    _instances = {}
    def __init__(self, plex_service, socketio, app, update_interval=600, username=None, service_type=None, plex_user_id=None, user_type='plex'):
        self.plex_service = plex_service
        self.socketio = socketio
        self.app = app
        self.update_interval = update_interval
        self.running = False
        self.is_updating = False
        self.last_update = 0
        self._cache_lock = RLock()
        self._movies_memory_cache = []
        self._initializing = False
        self.username = username
        self.service_type = service_type
        self.plex_user_id = plex_user_id
        self.user_type = user_type

        self.user_data_dir, self.cache_file_path, self.all_movies_cache_path, self.metadata_cache_path = self._get_cache_paths()

        if plex_service and hasattr(plex_service, 'set_cache_manager'):
            plex_service.set_cache_manager(self)

        if self.cache_file_path and os.path.exists(self.cache_file_path):
            logger.info(f"Loading existing cache into memory from {self.cache_file_path}")
            self._init_memory_cache()
        elif self.cache_file_path:
            logger.info(f"Cache file doesn't exist at {self.cache_file_path}, memory cache will stay empty until built")
            self._movies_memory_cache = []
        else:
            logger.info(f"Cache file doesn't exist at {self.cache_file_path}, memory cache will stay empty until built")
            self._movies_memory_cache = []

        self.last_update = time.time()

        if self.all_movies_cache_path and not os.path.exists(self.all_movies_cache_path):
             logger.info(f"All movies cache missing at {self.all_movies_cache_path}. Build should be triggered externally for {self.username or 'global'} ({self.user_type}).")
        elif not self.all_movies_cache_path:
             logger.info(f"All movies cache path not applicable for this user ({self.username}, {self.user_type}).")

    def _verify_cache_validity(self):
        """Verify cache is still valid by checking unwatched status using switchUser"""
        try:
            if not self._movies_memory_cache:
                logger.info("Cache verification failed: No movies in memory cache")
                return False

            plex_instance = self.plex_service.plex
            user_switched = False

            if hasattr(self, 'username') and self.username:
                try:
                    plex_instance = self.plex_service.plex.switchUser(self.username)
                    user_switched = True
                    logger.info(f"Successfully switched to user perspective for cache validation: {self.username}")
                except Exception as e:
                    logger.error(f"Error switching to user {self.username} for cache validation: {e}")
                    if hasattr(self, 'username') and self.username:
                        logger.error(f"Cannot validate user cache for {self.username} without their perspective. Cache validation FAILED.")
                        return False
                    logger.warning(f"Falling back to admin perspective for cache validation")

            import random
            sample_size = min(5, len(self._movies_memory_cache))
            sample_movies = random.sample(self._movies_memory_cache, sample_size)
            logger.info(f"Cache Validation: Checking {sample_size} random movies...")

            for movie in sample_movies:
                movie_title = movie.get('title', 'Unknown')
                movie_id = movie.get('id', 'N/A')
                logger.info(f"Cache Validation: Checking movie '{movie_title}' (ID: {movie_id})")

                movie_found_and_unwatched = False
                failure_reason = "Not found in any library or is watched"

                for library in self.plex_service.libraries:
                    try:
                        check_library = library
                        if user_switched:
                            check_library = plex_instance.library.section(library.title)

                        plex_movie = check_library.fetchItem(int(movie['id']))

                        if plex_movie:
                            if not plex_movie.isWatched:
                                movie_found_and_unwatched = True
                                logger.info(f"Cache Validation: Movie '{movie_title}' (ID: {movie_id}) PASSED (found and unwatched in library '{check_library.title}')")
                                break
                            else:
                                failure_reason = f"Found in library '{check_library.title}' but isWatched=True"
                                logger.warning(f"Cache Validation: Movie '{movie_title}' (ID: {movie_id}) FAILED ({failure_reason})")
                                break

                    except Exception as e:
                        logger.error(f"Cache Validation: Error checking movie '{movie_title}' (ID: {movie_id}) in library '{library.title}': {e}")
                        failure_reason = f"Error during check in library '{library.title}': {e}"

                if not movie_found_and_unwatched:
                    logger.warning(f"Cache Validation: FINAL RESULT for movie '{movie_title}' (ID: {movie_id}): FAILED. Reason: {failure_reason}")
                    logger.warning(f"Cache validation failed due to movie '{movie_title}' (ID: {movie_id}). Rebuilding cache.")
                    return False

            logger.info("Cache Validation: All sampled movies PASSED.")
            return True

        except Exception as e:
            logger.error(f"Error verifying cache: {e}")
            return False

    def _get_cache_paths(self):
        """Determines the appropriate cache paths based on user type and ID."""
        user_data_dir = '/app/data'
        cache_file_path = None
        all_movies_cache_path = None
        metadata_cache_path = None

        if self.user_type == 'plex_managed' and self.plex_user_id:
            user_data_dir = f'/app/data/user_data/plex_managed_{self.plex_user_id}'
            try:
                os.makedirs(user_data_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"CacheManager: Failed to create directory {user_data_dir}: {e}. Falling back to base data directory for this user.")
                user_data_dir = '/app/data'
            cache_file_path = f'{user_data_dir}/plex_unwatched_movies.json'
            all_movies_cache_path = f'{user_data_dir}/plex_all_movies.json'
            metadata_cache_path = f'{user_data_dir}/plex_metadata_cache.json'
            logger.info(f"Using managed Plex user cache paths for ID {self.plex_user_id}: {user_data_dir}")
        elif self.user_type == 'plex' and self.username and self.username != "admin":
            display_username = self.username[len('plex_'):] if self.username.startswith('plex_') else self.username
            user_data_dir = f'/app/data/user_data/plex_{display_username}'
            try:
                os.makedirs(user_data_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"CacheManager: Failed to create directory {user_data_dir}: {e}. Falling back to base data directory for this user.")
                user_data_dir = '/app/data'
            cache_file_path = f'{user_data_dir}/plex_unwatched_movies.json'
            all_movies_cache_path = f'{user_data_dir}/plex_all_movies.json'
            metadata_cache_path = f'{user_data_dir}/plex_metadata_cache.json'
            logger.info(f"Using regular Plex user cache paths for {display_username} (internal: {self.username}): {user_data_dir}")
        elif self.username and self.username != "admin":
            display_username = self.username
            service_prefix_for_path = self.user_type
            if self.username.startswith(f'{self.user_type}_'):
                 display_username = self.username[len(f'{self.user_type}_'):]

            user_data_dir = f'/app/data/user_data/{service_prefix_for_path}_{display_username}'
            try:
                os.makedirs(user_data_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"CacheManager: Failed to create directory {user_data_dir} for user {self.username} (type {self.user_type}): {e}. Falling back to base data directory.")
                user_data_dir = '/app/data'

            cache_file_path = None
            all_movies_cache_path = None
            metadata_cache_path = None
            logger.info(f"Using user-specific data directory for {self.username} (type {self.user_type}): {user_data_dir}. Plex-specific cache paths are {cache_file_path}, {all_movies_cache_path}.")
        else:
            user_data_dir = '/app/data'
            cache_file_path = '/app/data/plex_unwatched_movies.json'
            all_movies_cache_path = '/app/data/plex_all_movies.json'
            metadata_cache_path = '/app/data/plex_metadata_cache.json'
            logger.info(f"Using global cache paths for {'admin' if self.username == 'admin' else 'unauthenticated session'}")
        
        return user_data_dir, cache_file_path, all_movies_cache_path, metadata_cache_path

    def start_cache_build(self):
        """Start the cache building process with progress updates"""
        with self._cache_lock:
            if self._initializing:
                logger.info(f"Cache build already in progress for {self.username or self.plex_user_id or 'global'} ({self.user_type}), skipping.")
                return

            self._initializing = True

        try:
            self.socketio.emit('loading_progress', {
                'progress': 0.05,
                'current': 0,
                'total': 0,
                'status': 'Starting cache build...'
            }, namespace='/')

            if hasattr(self, '_build_for_user') and self._build_for_user and self.all_movies_cache_path and os.path.exists(self.all_movies_cache_path):
                with open(self.all_movies_cache_path, 'r') as f:
                    all_movies_data = json.load(f)

                total_movies = len(all_movies_data)
                self.socketio.emit('loading_progress', {
                    'progress': 0.1,
                    'current': 0,
                    'total': total_movies,
                    'status': 'Finding unwatched movies'
                }, namespace='/')

                unwatched_movies = []

                for i, movie in enumerate(all_movies_data):
                    if not movie.get('watched', False):
                        unwatched_movies.append(movie)

                    if i % 10 == 0:
                        progress = (i / total_movies) * 0.8
                        self.socketio.emit('loading_progress', {
                            'progress': progress,
                            'current': i,
                            'total': total_movies,
                            'status': 'Finding unwatched movies'
                        }, namespace='/')

                with self._cache_lock:
                    self._movies_memory_cache = unwatched_movies
                self._save_cache_to_disk()

                self.socketio.emit('loading_progress', {
                    'progress': 1.0,
                    'current': total_movies,
                    'total': total_movies,
                    'status': 'Cache complete'
                }, namespace='/')

                self.socketio.emit('loading_complete', namespace='/')
                self._initializing = False
                return

            if self.username:
                logger.info(f"Building cache with user-specific perspective: {self.username}")

                if not hasattr(self.plex_service, 'cache_manager'):
                    self.plex_service.cache_manager = self

                self.plex_service._is_coordinated_build = True

            original_cache_manager = getattr(self, '_original_cache_manager', None)
            if original_cache_manager:
                original_cache_manager._initializing = False

            self.plex_service.refresh_cache(force=True, from_cache_manager=True)

            new_cache_data = self.plex_service._movies_cache
            with self._cache_lock:
                self._movies_memory_cache = new_cache_data

            self._save_cache_to_disk()

            self.plex_service.save_cache_to_disk()

            total_movies = len(self._movies_memory_cache)
            logger.info(f"Cache build completed with {total_movies} movies for {self.username or 'global'}")

            self.socketio.emit('loading_progress', {
                'progress': 1.0,
                'current': total_movies,
                'total': total_movies,
                'status': 'Cache complete'
            }, namespace='/')

            self.socketio.emit('loading_complete', namespace='/')

        except Exception as e:
            logger.error(f"Error building cache: {e}")
            self.socketio.emit('loading_progress', {
                'progress': 1.0,
                'error': str(e),
                'status': 'Error building cache'
            }, namespace='/')
        finally:
            self._initializing = False
            if hasattr(self.plex_service, '_is_coordinated_build'):
                self.plex_service._is_coordinated_build = False

            if (not self.username or self.username == "admin") and self.user_type == 'plex':
                logger.info(f"Global cache build for '{self.username or 'global'}' completed for unwatched. Now ensuring all_movies_cache is built.")
                try:
                    self.cache_all_plex_movies(synchronous=True)
                except Exception as e_all_cache:
                    logger.error(f"Error during synchronous cache_all_plex_movies for global: {e_all_cache}")

            if self.plex_service:
                try:
                    logger.info(f"Directly updating PlexService internal cache after build/rebuild for {self.username or 'global'}")
                    with self._cache_lock:
                         plex_cache_update = self._movies_memory_cache.copy()
                    self.plex_service._movies_cache = plex_cache_update
                    self.plex_service._cache_loaded = True
                    logger.info(f"PlexService internal cache updated with {len(plex_cache_update)} movies.")
                except Exception as update_err:
                    logger.error(f"Error directly updating PlexService cache: {update_err}")

    def rebuild_user_cache(self, username):
        """Rebuild Plex cache specifically for a user with their Plex watch status"""
        if self.service_type != 'plex':
            logger.info(f"Skipping rebuild_user_cache for non-Plex user {username} ({self.service_type})")
            return

        if self._initializing:
            logger.info(f"Cache rebuild already initializing for {username}, skipping.")
            return

        if not self.all_movies_cache_path or not self.cache_file_path:
             logger.error(f"Cannot rebuild user cache for {username}: Required cache paths are not defined even though service_type is plex.")
             return

        self._initializing = True
        try:
            self.socketio.emit('loading_progress', {
                'progress': 0.1,
                'current': 0,
                'total': 100,
                'status': 'Building user-specific cache'
            }, namespace='/')

            original_username = getattr(self.plex_service, 'username', None)
            self.plex_service.username = username

            logger.info(f"Building user-specific cache for {username}")

            all_movies = []

            user_plex = self.plex_service._get_user_plex_instance()

            for library in self.plex_service.libraries:
                try:
                    try:
                        user_library = user_plex.library.section(library.title)
                        library_movies = list(user_library.all())
                    except Exception as e:
                        logger.error(f"Error getting user library: {e}")
                        library_movies = list(library.all())

                    all_movies.extend(library_movies)

                    self.socketio.emit('loading_progress', {
                        'progress': 0.3,
                        'current': len(all_movies),
                        'total': 100,
                        'status': f'Loaded library: {library.title}'
                    }, namespace='/')
                except Exception as e:
                    logger.error(f"Error loading library {library.title}: {e}")

            processed_movies = []
            for i, movie in enumerate(all_movies):
                try:
                    movie_data = self.plex_service.get_movie_data(movie)
                    if movie_data:
                        try:
                            movie_data['watched'] = movie.isWatched
                        except:
                            movie_data['watched'] = False

                        processed_movies.append(movie_data)
                except Exception as e:
                    logger.error(f"Error processing movie {getattr(movie, 'title', 'Unknown')}: {e}")

                if i % 10 == 0:
                    progress = 0.3 + (0.4 * (i / len(all_movies)))
                    self.socketio.emit('loading_progress', {
                        'progress': progress,
                        'current': i,
                        'total': len(all_movies),
                        'status': 'Processing all movies'
                    }, namespace='/')

            os.makedirs(self.user_data_dir, exist_ok=True)

            temp_all_path = self.all_movies_cache_path + ".tmp"
            try:
                with open(temp_all_path, 'w') as f:
                    json.dump(processed_movies, f)
                os.replace(temp_all_path, self.all_movies_cache_path)
                logger.info(f"Saved all movies cache for {username} to {self.all_movies_cache_path}")
            except Exception as save_all_err:
                 logger.error(f"Error saving all movies cache to {self.all_movies_cache_path}: {save_all_err}")
                 if os.path.exists(temp_all_path):
                     try:
                         os.remove(temp_all_path)
                     except Exception as remove_e:
                         logger.error(f"Error removing temporary all movies cache file {temp_all_path}: {remove_e}")

            unwatched_movies = []
            for i, movie in enumerate(processed_movies):
                if not movie.get('watched', False):
                    unwatched_movies.append(movie)

                if i % 10 == 0:
                    progress = 0.7 + (0.25 * (i / len(processed_movies)))
                    self.socketio.emit('loading_progress', {
                        'progress': progress,
                        'current': i,
                        'total': len(processed_movies),
                        'status': 'Finding unwatched movies'
                    }, namespace='/')

            with self._cache_lock:
                self._movies_memory_cache = unwatched_movies
            self._save_cache_to_disk()
            self._save_cache_to_disk()

            if original_username:
                self.plex_service.username = original_username

            self.socketio.emit('loading_progress', {
                'progress': 1.0,
                'current': len(processed_movies),
                'total': len(processed_movies),
                'status': 'Cache complete'
            }, namespace='/')

            logger.info(f"Completed user cache build for {username}: {len(unwatched_movies)} unwatched of {len(processed_movies)} total")

            self.socketio.emit('loading_complete', namespace='/')

        except Exception as e:
            logger.error(f"Error rebuilding user cache for {username}: {e}")
        finally:
            self._initializing = False
            if self.username and self.user_type == 'plex':
                logger.info(f"User cache rebuild for '{username}' completed for unwatched. Now ensuring user's all_movies_cache is built.")
                try:
                    self.cache_all_plex_movies(synchronous=True)
                except Exception as e_user_all_cache:
                    logger.error(f"Error during synchronous cache_all_plex_movies for user {username}: {e_user_all_cache}")

            if self.plex_service:
                try:
                    logger.info(f"Directly updating PlexService internal cache after build/rebuild for {self.username or username or 'global'}")
                    with self._cache_lock:
                         plex_cache_update = self._movies_memory_cache.copy()
                    self.plex_service._movies_cache = plex_cache_update
                    self.plex_service._cache_loaded = True
                    logger.info(f"PlexService internal cache updated with {len(plex_cache_update)} movies.")
                except Exception as update_err:
                    logger.error(f"Error directly updating PlexService cache: {update_err}")

    def _init_memory_cache(self):
        """Initialize in-memory cache from the unwatched movies disk cache, if applicable."""
        if not self.cache_file_path:
            logger.debug(f"Unwatched cache path not defined for {self.username or 'global'} ({self.service_type}), skipping memory cache init from disk.")
            self._movies_memory_cache = []
            return

        try:
            if os.path.exists(self.cache_file_path):
                with open(self.cache_file_path, 'r') as f:
                    self._movies_memory_cache = json.load(f)
                logger.info(f"Loaded {len(self._movies_memory_cache)} movies into memory cache from {self.cache_file_path}")
            else:
                logger.info(f"Unwatched cache file {self.cache_file_path} does not exist, initializing empty memory cache.")
                self._movies_memory_cache = []
        except Exception as e:
            logger.error(f"Error initializing memory cache from {self.cache_file_path}: {e}")
            self._movies_memory_cache = []

    def start(self):
        """Start the cache manager background thread"""
        logger.info(f"Starting cache manager background thread for {self.username or 'global'}")
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
        logger.info(f"Update loop started for {self.username or 'global'}")
        from datetime import datetime, timedelta

        while self.running:
            try:
                current_time = time.time()
                time_since_last_update = current_time - self.last_update

                logger.debug(f"Update check: Time since last update: {time_since_last_update:.1f}s, Interval: {self.update_interval}s")

                if self.cache_file_path and os.path.exists(self.cache_file_path) and (time_since_last_update >= self.update_interval):
                    logger.info(f"Update interval reached, checking for changes for {self.username or 'global'}")
                    with self._cache_lock:
                        self.check_for_changes()

                self.last_update = time.time()

                time_to_next_update = max(1, self.update_interval - (time.time() - self.last_update))
                next_check_time = datetime.now() + timedelta(seconds=self.update_interval)
                logger.debug(f"Next update check for {self.username or 'global'} scheduled around: {next_check_time.strftime('%H:%M:%S')}")

                sleep_interval = min(60, time_to_next_update)
                for _ in range(int(time_to_next_update / sleep_interval)):
                    if not self.running:
                        break
                    time.sleep(sleep_interval)

                remaining_time = time_to_next_update % sleep_interval
                if remaining_time > 0 and self.running:
                    time.sleep(remaining_time)

            except Exception as e:
                logger.error(f"Error in update loop: {e}", exc_info=True)
                time.sleep(5)

    def check_for_changes(self):
        """Check for changes in the Plex library and update Plex caches if needed."""
        is_plex_related = self.user_type in ['plex', 'plex_managed']
        if not is_plex_related:
            logger.debug(f"Skipping check_for_changes for non-Plex related user {self.username} (user_type: {self.user_type})")
            return

        if not self.cache_file_path:
             logger.warning(f"Cannot check for changes for {self.username or 'global'}: Unwatched cache path is not defined.")
             return

        if not self.plex_service:
             logger.error(f"Cannot check for changes for {self.username or 'global'}: plex_service is not available.")
             return

        if self.is_updating:
            logger.info(f"Update already in progress for {self.username or 'global'}, skipping check_for_changes")
            return

        if not os.path.exists(self.cache_file_path):
            logger.info(f"Unwatched cache file {self.cache_file_path} doesn't exist, skipping check_for_changes. Cache needs initial build.")
            return

        try:
            logger.info(f"Starting to check for library changes for {self.username or 'global'}...")
            self.is_updating = True

            self.cache_all_plex_movies()

            current_unwatched = set()

            plex_instance = self.plex_service.plex
            owner_username = None
            try:
                 owner_username = self.plex_service.plex.myPlexAccount().username
            except Exception as owner_err:
                 logger.warning(f"Could not determine Plex owner username: {owner_err}.")

            plex_user_to_switch_to = None
            if self.user_type == 'plex' and self.username and self.username.startswith('plex_'):
                plex_user_to_switch_to = self.username[len('plex_'):]
            elif self.user_type == 'plex_managed' and self.username:
                plex_user_to_switch_to = self.username

            if plex_user_to_switch_to and owner_username and plex_user_to_switch_to.lower() != owner_username.lower():
                try:
                    logger.info(f"Attempting to switch to user perspective for cache update: {plex_user_to_switch_to} (CM User DisplayName: {self.username}, Plex User ID: {self.plex_user_id}, Type: {self.user_type}, Plex Owner: {owner_username})")
                    plex_instance = self.plex_service.plex.switchUser(plex_user_to_switch_to)
                    logger.info(f"Successfully switched to user perspective for cache update: {plex_user_to_switch_to}")
                except Exception as e:
                    logger.error(f"Error switching to user {plex_user_to_switch_to} (Plex User ID: {self.plex_user_id}) for cache update: {e}")
                    logger.warning(f"Using admin perspective for cache update - results may not be accurate")
                    plex_instance = self.plex_service.plex
            elif self.user_type == 'plex' or self.user_type == 'plex_managed':
                logger.info(f"Using current Plex instance perspective for {self.username or self.plex_user_id} (Type: {self.user_type}, Plex Owner: {owner_username}).")

            for library_name in self.plex_service.library_names:
                logger.info(f"Checking library '{library_name}' for unwatched movies (Perspective: {plex_user_to_switch_to or owner_username or 'default'})...")
                try:
                    fresh_library = plex_instance.library.section(library_name)
                    for movie in fresh_library.search(unwatched=True):
                        current_unwatched.add(str(movie.ratingKey))
                except Exception as e:
                    logger.error(f"Error checking library '{library_name}': {e}")

            logger.info(f"Found {len(current_unwatched)} currently unwatched movies")

            cached_unwatched = {str(movie['id']) for movie in self._movies_memory_cache}
            logger.info(f"Have {len(cached_unwatched)} cached unwatched movies")

            newly_watched = cached_unwatched - current_unwatched
            newly_unwatched = current_unwatched - cached_unwatched

            if newly_watched or newly_unwatched:
                logger.info(f"Found {len(newly_watched)} newly watched and {len(newly_unwatched)} newly unwatched movies")

                movies_added = False
                if newly_watched:
                    logger.info(f"Removing {len(newly_watched)} newly watched movies for {self.username or 'global'}...")
                    self.remove_watched_movies(newly_watched)

                    if not self.username and owner_username:
                        logger.info(f"Global manager detected owner change ({owner_username}). Attempting to sync removal to user-specific cache...")
                        owner_manager = CacheManager.get_user_cache_manager(
                            self.plex_service, self.socketio, self.app, owner_username, 'plex'
                        )
                        if owner_manager and owner_manager != self:
                            logger.info(f"Calling remove_watched_movies on user-specific manager for {owner_username}")
                            owner_manager.remove_watched_movies(newly_watched)
                        elif owner_manager == self:
                             logger.warning(f"Owner manager lookup returned self for {owner_username}. Skipping redundant removal sync.")
                        else:
                             logger.warning(f"Could not retrieve user-specific cache manager for owner {owner_username} to sync watched status removal.")

                if newly_unwatched:
                    logger.info(f"Adding {len(newly_unwatched)} newly unwatched movies for {self.username or 'global'}...")
                    movies_to_add = []
                    for movie_id in newly_unwatched:
                        try:
                            movie_data = self.plex_service.get_movie_by_id(movie_id)

                            if movie_data:
                                movies_to_add.append(movie_data)
                            else:
                                logger.warning(f"[{self.username or 'global'}] Loop: Could not fetch data for newly unwatched movie ID {movie_id}. Skipping add.")
                        except Exception as fetch_err:
                            logger.error(f"[{self.username or 'global'}] Loop: Error fetching data for newly unwatched movie ID {movie_id}: {fetch_err}", exc_info=True)
                    if movies_to_add:
                        with self._cache_lock:
                            existing_ids = {str(m.get('id')) for m in self._movies_memory_cache}
                            added_count = 0

                            for movie in movies_to_add:
                                movie_id_str = str(movie.get('id'))
                                if movie_id_str not in existing_ids:
                                    self._movies_memory_cache.append(movie)
                                    added_count += 1

                            if added_count > 0:
                                logger.info(f"[{self.username or 'global'}] Added {added_count} unique newly unwatched movies to memory cache.")
                                movies_added = True

                        if movies_added:
                            logger.info(f"[{self.username or 'global'}] Calling _save_cache_to_disk (after lock release)...")
                            self._save_cache_to_disk()

            else:
                 logger.info(f"No changes detected in unwatched status for {self.username or 'global'}.")

            self.last_update = time.time()

        except Exception as e:
            logger.error(f"Error checking for changes: {e}", exc_info=True)
        finally:
            self.is_updating = False
            self.last_update = time.time()

    def _load_from_disk_cache(self):
        """Try to load cache from disk and use switchUser if needed to validate"""
        try:
            movies_cache_path = self.MOVIES_CACHE_FILE
            metadata_cache_path = self.METADATA_CACHE_FILE
            is_user_specific = False

            if hasattr(self, 'username') and self.username:
                is_user_specific = True
                user_data_dir = f'/app/data/user_data/plex_{self.username}'
                os.makedirs(user_data_dir, exist_ok=True)
                movies_cache_path = os.path.join(user_data_dir, 'plex_unwatched_movies.json')
                metadata_cache_path = os.path.join(user_data_dir, 'plex_metadata_cache.json')
                logger.info(f"Attempting to load user-specific cache for {self.username} from {user_data_dir}")
            else:
                logger.info(f"Attempting to load global cache from /app/data")

            movies_cache_exists = os.path.exists(movies_cache_path)
            metadata_cache_exists = os.path.exists(metadata_cache_path)
            logger.info(f"Cache Check: Unwatched cache '{os.path.basename(movies_cache_path)}' exists: {movies_cache_exists}")
            logger.info(f"Cache Check: Metadata cache '{os.path.basename(metadata_cache_path)}' exists: {metadata_cache_exists}")

            if is_user_specific and (not movies_cache_exists or not metadata_cache_exists):
                logger.info(f"User-specific cache missing for {self.username}. Will build a new user cache.")
                return False

            if movies_cache_exists and metadata_cache_exists:
                logger.info(f"Loading cached data from disk: {movies_cache_path} and {metadata_cache_path}")
                try:
                    movies_cache_size = os.path.getsize(movies_cache_path)
                    metadata_cache_size = os.path.getsize(metadata_cache_path)
                    logger.info(f"Cache Check: Unwatched cache size: {movies_cache_size} bytes")
                    logger.info(f"Cache Check: Metadata cache size: {metadata_cache_size} bytes")

                    if movies_cache_size == 0 or metadata_cache_size == 0:
                         logger.warning(f"Cache file(s) are empty. Unwatched: {movies_cache_size} bytes, Metadata: {metadata_cache_size} bytes. Rebuilding cache.")
                         self._movies_cache = []
                         self._metadata_cache = {}
                         return False

                    with open(movies_cache_path, 'r') as f:
                        self._movies_cache = json.load(f)
                    logger.info(f"Successfully loaded JSON from unwatched cache.")
                    with open(metadata_cache_path, 'r') as f:
                        self._metadata_cache = json.load(f)

                    logger.info(f"Successfully loaded JSON from metadata cache.")
                    logger.info(f"Loaded {len(self._movies_cache)} movies and {len(self._metadata_cache)} metadata entries into memory.")

                    if self._verify_cache_validity():
                        self._cache_loaded = True
                        logger.info(f"Successfully loaded and verified {len(self._movies_cache)} movies from disk cache ({'user-specific' if is_user_specific else 'global'})")
                        return True
                    else:
                        logger.warning(f"Cache verification failed for {'user ' + self.username if is_user_specific else 'global cache'}, will rebuild cache")
                        self._movies_cache = []
                        self._metadata_cache = {}
                        return False

                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding JSON from cache file: {e}. Rebuilding cache.")
                    self._movies_cache = []
                    self._metadata_cache = {}
                    return False
                except Exception as e:
                    logger.error(f"Error reading cache files: {e}. Rebuilding cache.")
                    self._movies_cache = []
                    self._metadata_cache = {}
                    return False
            else:
                missing_files = []
                if not movies_cache_exists:
                    missing_files.append(os.path.basename(movies_cache_path))
                if not metadata_cache_exists:
                    missing_files.append(os.path.basename(metadata_cache_path))
                logger.warning(f"Required cache file(s) not found: {', '.join(missing_files)}. Will build cache.")
                return False

        except Exception as e:
            if isinstance(e, OSError) and e.errno == 13:
                 logger.error(f"Permission denied accessing cache directory/files: {e}. Check permissions for /app/data.")
            else:
                 logger.error(f"Unexpected error during cache loading: {e}")

            self._movies_cache = []
            self._metadata_cache = {}
            return False

    def _save_cache_to_disk(self):
        """Save the current in-memory unwatched movies cache to disk, if applicable."""
        if not self.cache_file_path:
            logger.debug(f"Unwatched cache path not defined for {self.username or 'global'} ({self.service_type}), skipping save cache to disk.")
            return

        temp_path = None
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            temp_path = self.cache_file_path + ".tmp"
            with self._cache_lock:
                cache_data_to_save = list(self._movies_memory_cache)

            with open(temp_path, 'w') as f:
                json.dump(cache_data_to_save, f)

            os.replace(temp_path, self.cache_file_path)

            logger.info(f"Saved {len(cache_data_to_save)} movies to disk cache: {self.cache_file_path}")
        except Exception as e:
            logger.error(f"Error saving cache to disk {self.cache_file_path}: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as remove_e:
                    logger.error(f"Error removing temporary cache file {temp_path}: {remove_e}")

    def cache_all_plex_movies(self, synchronous=False):
        """Cache all movies (watched and unwatched) for Plex, if applicable."""
        if not self.all_movies_cache_path:
            logger.debug(f"All movies cache path not defined for {self.username or 'global'} ({self.user_type}), skipping cache_all_plex_movies.")
            return

        if not synchronous and getattr(self, '_building_all_cache', False):
            logger.info(f"All movies cache build already in progress for {self.username or 'global'}, skipping")
            return

        if synchronous:
            logger.info(f"Starting SYNCHRONOUS all Plex movies cache build for {self.username or 'global'}...")
        else:
            logger.info(f"Starting to cache all Plex movies in background for {self.username or 'global'}...")

        self._building_all_cache = True

        def build_cache_logic():
            try:
                if not self.plex_service:
                    logger.error(f"plex_service is unexpectedly None in cache_all_plex_movies for {self.username or 'global'}. Aborting build.")
                    return

                logger.info(f"plex_service is available for {self.username or 'global'}, proceeding with all movies cache build.")
                processed_movies = []
                total_movies = 0

                plex_instance = self.plex_service._get_user_plex_instance()

                for library_name in self.plex_service.library_names:
                    logger.info(f"Processing library: {library_name}")
                    try:
                        library = plex_instance.library.section(library_name)
                        library_movies = list(library.all())
                        total_movies += len(library_movies)

                        for movie in library_movies:
                            try:
                                movie_data = self.plex_service.get_movie_data(movie)
                                if movie_data:
                                    try:
                                        movie_data['watched'] = movie.isWatched
                                    except Exception as watch_err:
                                        logger.warning(f"Could not get watched status for {movie.title}: {watch_err}")
                                        movie_data['watched'] = False
                                    processed_movies.append(movie_data)
                            except Exception as e:
                                logger.error(f"Error processing movie {movie.title}: {e}")
                    except Exception as lib_err:
                         logger.error(f"Error accessing library {library_name} from perspective {self.username or 'global'}: {lib_err}")

                if self.username:
                    os.makedirs(os.path.dirname(self.all_movies_cache_path), exist_ok=True)

                temp_path = f"{self.all_movies_cache_path}.tmp"
                with open(temp_path, 'w') as f:
                    json.dump(processed_movies, f)
                os.replace(temp_path, self.all_movies_cache_path)

                logger.info(f"Successfully cached {len(processed_movies)} total Plex movies for {self.username or 'global'}")
            except Exception as e:
                logger.error(f"Error building all movies cache: {e}")
            finally:
                self._building_all_cache = False

        if synchronous:
            build_cache_logic()
        else:
            Thread(target=build_cache_logic, daemon=True).start()


    @lru_cache(maxsize=1)
    def get_all_plex_movies(self):
        """Get all movies (watched and unwatched) from cache with caching"""
        if not self.all_movies_cache_path:
            logger.debug(f"All movies cache path not defined for {self.username or 'global'} ({self.service_type}), cannot get all plex movies.")
            return []

        try:
            if os.path.exists(self.all_movies_cache_path):
                with open(self.all_movies_cache_path, 'r') as f:
                    if os.path.getsize(self.all_movies_cache_path) > 0:
                        return json.load(f)
                    else:
                        logger.warning(f"All movies cache file is empty: {self.all_movies_cache_path}")
                        return []
            else:
                 logger.info(f"All movies cache file does not exist: {self.all_movies_cache_path}")

        except json.JSONDecodeError as json_err:
             logger.error(f"Error decoding JSON from all movies cache {self.all_movies_cache_path}: {json_err}")
        except Exception as e:
            logger.error(f"Error reading all movies cache {self.all_movies_cache_path}: {e}")

        return []

    def force_refresh(self):
        """Force a complete cache refresh"""
        try:
            logger.info(f"Starting forced cache refresh for {self.username or 'global'}")
            with self._cache_lock:
                self.plex_service.refresh_cache(force=True)
                self.cache_all_plex_movies()
                self._init_memory_cache()
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
            'all_movies_cache_exists': os.path.exists(self.all_movies_cache_path),
            'username': self.username
        }

    def get_cached_movies(self):
        """Get cached movies from memory cache"""
        return self._movies_memory_cache
    def get_filtered_movie_count(self, filters):
        """
        Counts movies matching the provided filters.

        Args:
            filters (dict): A dictionary containing filter criteria:
                            {'genres': list, 'years': list, 'pgRatings': list, 'watch_status': str}

        Returns:
            int: The count of matching movies.
        """
        with self._cache_lock:
            watch_status = filters.get('watch_status', 'unwatched')
            selected_genres = set(g for g in filters.get('genres', []) if g)
            selected_years = set(int(y) for y in filters.get('years', []) if y)
            selected_pg_ratings = set(r for r in filters.get('pgRatings', []) if r)

            cache_path_to_load = None
            source_cache_name = "unknown"

            if watch_status == 'unwatched':
                cache_path_to_load = self.cache_file_path
                source_cache_name = f"unwatched (disk - {cache_path_to_load})"
            elif watch_status in ['all', 'watched']:
                cache_path_to_load = self.all_movies_cache_path
                source_cache_name = f"all movies (disk - {cache_path_to_load})"
            else:
                logger.warning(f"Unknown watch_status '{watch_status}' received. Defaulting to unwatched cache file.")
                cache_path_to_load = self.cache_file_path
                source_cache_name = f"unwatched (disk - default - {cache_path_to_load})"

            logger.debug(f"Attempting to load cache for filtering from: {source_cache_name}")

            movies_to_filter = []
            try:
                if not cache_path_to_load:
                    logger.warning(f"Cache path is None for filtering '{watch_status}'. Cannot load cache. Returning 0.")
                    return 0
                if os.path.exists(cache_path_to_load):
                    with open(cache_path_to_load, 'r') as f:
                        if os.path.getsize(cache_path_to_load) > 0:
                            movies_to_filter = json.load(f)
                            logger.debug(f"Successfully loaded {len(movies_to_filter)} movies from {source_cache_name}")
                        else:
                            logger.warning(f"Cache file is empty at {cache_path_to_load}. Returning 0.")
                            return 0
                else:
                    logger.warning(f"Cache file not found at {cache_path_to_load} for filtering '{watch_status}'. Returning 0.")
                    return 0
            except json.JSONDecodeError as json_err:
                logger.error(f"Error decoding JSON from cache file {cache_path_to_load}: {json_err}", exc_info=True)
                return 0
            except Exception as e:
                logger.error(f"Error loading cache file {cache_path_to_load} for filtering: {e}", exc_info=True)
                return 0

            count = 0
            for movie in movies_to_filter:
                if watch_status == 'watched':
                    if not movie.get('watched', False):
                        continue

                movie_genres = set(movie.get('genres', []))
                if selected_genres and selected_genres.isdisjoint(movie_genres):
                    continue

                try:
                    movie_year_int = int(movie.get('year')) if movie.get('year') is not None else None
                except (ValueError, TypeError):
                    movie_year_int = None
                if selected_years and movie_year_int not in selected_years:
                    continue

                movie_rating = movie.get('contentRating')
                if selected_pg_ratings and movie_rating not in selected_pg_ratings:
                    continue

                count += 1

            logger.debug(f"Filter count from {source_cache_name}: {count}")
            return count

    def get_all_unwatched_movies(self, progress_callback=None):
        """Get all unwatched movies with progress tracking"""
        try:
            if progress_callback:
                progress_callback(1.0)
            return list(self._movies_memory_cache)
        except Exception as e:
            logger.error(f"Error getting all unwatched movies: {e}")
            return []

    @classmethod
    def get_user_cache_manager(cls, plex_service, socketio, app, username=None, service_type=None, plex_user_id=None, user_type='plex'):
        """
        Factory method to get or create a cache manager instance.
        Uses a class-level registry (_instances) to manage instances based on user type and ID.
        """
        instance_key = '_global'

        if user_type == 'plex_managed' and plex_user_id:
            instance_key = f"plex_managed_{plex_user_id}"
        elif user_type == 'plex' and username and username != "admin":
            instance_key = f"plex_{username}"
        elif username and username != "admin":
            effective_service_type = service_type or user_type
            instance_key = f"{effective_service_type}_{username}"

        if instance_key in cls._instances:
            logger.debug(f"Returning existing CacheManager instance for key: {instance_key}")
            return cls._instances[instance_key]

        logger.info(f"Creating new CacheManager instance for key: {instance_key} (User: {username}, PlexID: {plex_user_id}, Type: {user_type})")

        instance = cls(
            plex_service=plex_service,
            socketio=socketio,
            app=app,
            username=username,
            service_type=service_type,
            plex_user_id=plex_user_id,
            user_type=user_type
        )
        cls._instances[instance_key] = instance
        return instance

    def remove_watched_movies(self, movie_ids_to_remove):
        """Removes specified movie IDs from the memory cache and saves to disk."""
        if not movie_ids_to_remove:
            return

        removed_count = 0
        ids_set = set(map(str, movie_ids_to_remove))

        with self._cache_lock:
            original_count = len(self._movies_memory_cache)
            self._movies_memory_cache = [
                movie for movie in self._movies_memory_cache
                if str(movie.get('id')) not in ids_set
            ]
            removed_count = original_count - len(self._movies_memory_cache)

        if removed_count > 0:
            logger.info(f"[{self.username or 'global'}] Removed {removed_count} newly watched movies from memory cache.")
            self._save_cache_to_disk()
        else:
            logger.info(f"[{self.username or 'global'}] No movies found in cache matching IDs to remove: {movie_ids_to_remove}")
