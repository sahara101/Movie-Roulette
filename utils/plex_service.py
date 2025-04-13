import os
import random
import logging
import json
import time
import requests
import threading
from flask import current_app
from plexapi.server import PlexServer
from datetime import datetime, timedelta
from utils.poster_view import set_current_movie
from .settings import settings
from functools import lru_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlexService:
    _cache_build_in_progress = False
    _cache_lock = threading.Lock()
    _initializing = False

    def __init__(self, url=None, token=None, libraries=None, username=None, cache_manager=None):
        logger.info("Initializing PlexService")
        logger.info(f"Parameters - URL: {bool(url)}, Token: {bool(token)}, Libraries: [REDACTED]")

        self.username = username
        logger.info(f"Using Plex username: {username}" if username else "Using default admin watch status")

        self._cache_manager = cache_manager
        self.socketio = self._cache_manager.socketio if self._cache_manager else None

        self.PLEX_URL = url
        self.PLEX_TOKEN = token
        self.PLEX_MOVIE_LIBRARIES = libraries if isinstance(libraries, list) else libraries.split(',') if libraries else []

        self.MOVIES_CACHE_FILE = '/app/data/plex_unwatched_movies.json'
        self.METADATA_CACHE_FILE = '/app/data/plex_metadata_cache.json'
        
        if self._cache_manager:
            self.MOVIES_CACHE_FILE = self._cache_manager.cache_file_path
            self.METADATA_CACHE_FILE = self._cache_manager.metadata_cache_path

        if not self.PLEX_URL:
            self.PLEX_URL = os.getenv('PLEX_URL')
            logger.info("Using ENV for PLEX_URL")
        if not self.PLEX_TOKEN:
            self.PLEX_TOKEN = os.getenv('PLEX_TOKEN')
            logger.info("Using ENV for PLEX_TOKEN")
        if not self.PLEX_MOVIE_LIBRARIES:
            self.PLEX_MOVIE_LIBRARIES = os.getenv('PLEX_MOVIE_LIBRARIES', 'Movies').split(',')
            logger.info("Using ENV for PLEX_MOVIE_LIBRARIES")

        if not self.PLEX_URL:
            raise ValueError("Plex URL is required")
        if not self.PLEX_TOKEN:
            raise ValueError("Plex token is required")
        if not self.PLEX_MOVIE_LIBRARIES:
            raise ValueError("At least one movie library must be specified")

        logger.info(f"Connecting to Plex server at {self.PLEX_URL}")
        try:
            self.plex = PlexServer(self.PLEX_URL, self.PLEX_TOKEN)
            logger.info("Successfully connected to Plex server")
        except Exception as e:
            logger.error(f"Failed to connect to Plex server: {e}")
            raise

        try:
            self.library_names = [] 
            all_sections = self.plex.library.sections()
            valid_library_names = {section.title for section in all_sections}

            for lib_name in self.PLEX_MOVIE_LIBRARIES:
                clean_name = lib_name.strip()
                if clean_name in valid_library_names:
                    self.library_names.append(clean_name)
                    logger.info(f"Successfully validated library name: {clean_name}")
                else:
                    logger.error(f"Configured library name '{clean_name}' not found on Plex server. Valid names: {valid_library_names}")

            if not self.library_names:
                raise ValueError(f"No valid libraries found matching configured names: {self.PLEX_MOVIE_LIBRARIES}. Available on server: {valid_library_names}")

        except Exception as e:
            logger.error(f"Error initializing/validating library names: {e}")
            raise

        self.playback_start_times = {}
        self._metadata_cache = {}
        self._movies_cache = []
        self._cache_loaded = False
        self._initializing = False

        start_time = time.time()
        if self._load_from_disk_cache():
            logger.info(f"Loaded cache from disk in {time.time() - start_time:.2f} seconds")
            self._cache_loaded = True
        else:
            logger.info("Cache will be built asynchronously")
            self._movies_cache = []

        logger.info("PlexService initialization completed successfully")

    def _get_user_plex_instance(self):
        """Get the appropriate Plex instance based on username, handling owner account."""
        if hasattr(self, 'username') and self.username:
            try:
                try:
                    owner_username = self.plex.myPlexAccount().username
                except Exception as owner_err:
                    logger.warning(f"Could not get owner username from myPlexAccount: {owner_err}. Proceeding with switchUser attempt.")
                    owner_username = None 

                if owner_username and self.username.lower() == owner_username.lower():
                    logger.info(f"Using main Plex instance for owner account: {self.username}")
                    return self.plex  
                elif self.username.lower() == 'admin':
                    logger.info(f"Using main Plex instance for local 'admin' user.")
                    return self.plex  

                logger.info(f"Attempting to switch to managed user perspective: {self.username}")
                user_instance = self.plex.switchUser(self.username)
                logger.info(f"Successfully switched to user perspective: {self.username}")
                return user_instance
            except Exception as e:
                logger.error(f"Error getting user perspective for {self.username}: {e}")
                raise e
        logger.info("Using default Plex instance (no username specified).")
        return self.plex

    def _verify_cache_validity(self):
        """Verify cache is still valid by checking unwatched status using switchUser"""
        try:
            if not self._movies_cache:
                logger.info("Cache verification failed: No movies in memory cache")
                return False

            user_switched = False 
            try:
                plex_instance = self._get_user_plex_instance()
                user_switched = (plex_instance != self.plex) 
                logger.info(f"Using {'user (' + self.username + ')' if user_switched else 'default'} perspective for cache validation.")
            except Exception as e:
                logger.error(f"Failed to get Plex instance for user {self.username} during validation: {e}. Cache validation FAILED.")
                return False

            sample_size = min(5, len(self._movies_cache))
            sample_movies = random.sample(self._movies_cache, sample_size)
            logger.info(f"Cache Validation: Checking {sample_size} random movies...")

            for movie in sample_movies:
                movie_title = movie.get('title', 'Unknown')
                movie_id = movie.get('id', 'N/A')
                logger.info(f"Cache Validation: Checking movie '{movie_title}' (ID: {movie_id})")
                movie_found_and_unwatched = False
                failure_reason = "Not found in any library or is watched" 

                for library_name in self.library_names: 
                    try:
                        fresh_library = plex_instance.library.section(library_name)

                        plex_movie = fresh_library.fetchItem(int(movie['id']))

                        if plex_movie:
                            if not plex_movie.isWatched:
                                movie_found_and_unwatched = True
                                logger.info(f"Cache Validation: Movie '{movie_title}' (ID: {movie_id}) PASSED (found and unwatched in library '{library_name}')")
                                break 
                            else:
                                failure_reason = f"Found in library '{library_name}' but isWatched=True"
                                logger.warning(f"Cache Validation: Movie '{movie_title}' (ID: {movie_id}) FAILED ({failure_reason})")
                                break 

                    except Exception as e:
                        logger.error(f"Cache Validation: Error checking movie '{movie_title}' (ID: {movie_id}) in library '{library_name}': {e}")
                        failure_reason = f"Error during check in library '{library_name}': {e}"

                if not movie_found_and_unwatched:
                    logger.warning(f"Cache Validation: FINAL RESULT for movie '{movie_title}' (ID: {movie_id}): FAILED. Reason: {failure_reason}")
                    logger.warning(f"Cache validation failed due to movie '{movie_title}' (ID: {movie_id}). Rebuilding cache.")

            logger.info("Cache Validation: All sampled movies PASSED.")
            return True

        except Exception as e:
            logger.error(f"Error verifying cache: {e}")
            return False

    def _initialize_cache(self):
        """Load all movies and their metadata at startup"""
        with PlexService._cache_lock:
            if self._cache_loaded and self._movies_cache:
                 logger.info("Cache already initialized by another thread, skipping.")
                 return

            self._initializing = True
            
            logger.info("Initializing movie cache...")
            if hasattr(self, 'username') and self.username:
                logger.info(f"Building cache for specific user: {self.username}")

            start_time = time.time()
            all_movies = []

            try:
                socketio = None
                if hasattr(self, 'cache_manager') and self.cache_manager and hasattr(self.cache_manager, 'socketio'):
                    socketio = self.cache_manager.socketio
                    logger.info("Got SocketIO from cache_manager")

                user_switched = False 
                try:
                    plex_instance = self._get_user_plex_instance()
                    user_switched = (plex_instance != self.plex) 
                    logger.info(f"Using {'user (' + self.username + ')' if user_switched else 'default'} perspective for cache initialization.")
                except Exception as e:
                    logger.error(f"Failed to get Plex instance for user {self.username} during initialization: {e}. Cache build FAILED.")
                    raise e

                for library_name in self.library_names: 
                    try:
                        fresh_library = plex_instance.library.section(library_name)

                        unwatched_in_library = fresh_library.search(unwatched=True)
                        logger.info(f"Found {len(unwatched_in_library)} unwatched movies for perspective '{self.username or 'default'}' in library '{library_name}'")
                        all_movies.extend(unwatched_in_library)

                    except Exception as e:
                        logger.error(f"Error loading library '{library_name}' for perspective '{self.username or 'default'}': {e}")

                unique_movie_ids = set()
                deduplicated_movies = []
                for movie in all_movies:
                    if movie.ratingKey not in unique_movie_ids:
                        unique_movie_ids.add(movie.ratingKey)
                        deduplicated_movies.append(movie)
                
                all_movies = deduplicated_movies
                total_movies = len(all_movies)
                logger.info(f"Found {total_movies} unique unwatched movies to cache")

                self._movies_cache = []

                if socketio:
                    logger.info("Sending initial loading progress via SocketIO")
                    socketio.emit('loading_progress', {
                        'progress': 0.1,
                        'current': 0,
                        'total': total_movies,
                        'status': 'Building cache'
                    }, namespace='/')
                else:
                    logger.warning("No socketio reference available from cache_manager for progress updates, trying self.socketio fallback...")
                    if hasattr(self, 'socketio') and self.socketio:
                        logger.info("Using self.socketio for progress updates")
                        socketio = self.socketio 
                        socketio.emit('loading_progress', {
                            'progress': 0.1,
                            'current': 0,
                            'total': total_movies,
                            'status': 'Building cache'
                        }, namespace='/')
                    else:
                         logger.error("Fallback failed: self.socketio is also unavailable. Progress updates disabled.")


                for i, movie in enumerate(all_movies, 1):
                    try:
                        metadata = self._fetch_metadata(movie.ratingKey)
                        if metadata:
                            self._metadata_cache[str(movie.ratingKey)] = metadata

                        movie_data = self._basic_movie_data(movie)
                        if metadata:
                            self._enrich_with_metadata(movie_data, metadata)
                        self._movies_cache.append(movie_data)

                        progress = (i / total_movies) * 100
                        elapsed = time.time() - start_time
                        rate = i / elapsed if elapsed > 0 else 0

                        if i % 10 == 0:
                            logger.info(f"Cached {i}/{total_movies} movies ({progress:.1f}%) - {rate:.1f} movies/sec")

                        if socketio:
                            socketio.emit('loading_progress', {
                                'progress': min(0.9, (i / total_movies)),
                                'current': i,
                                'total': total_movies,
                                'status': 'Building cache'
                            }, namespace='/')

                    except Exception as e:
                        logger.error(f"Error caching movie {movie.title}: {e}")

                self._cache_loaded = True 

                logger.info(f"Cache initialized with {len(self._movies_cache)} movies in {time.time() - start_time:.2f} seconds")
                
                self.save_cache_to_disk()
                
                if socketio:
                    logger.info("Sending final loading progress via SocketIO")
                    socketio.emit('loading_progress', {
                        'progress': 1.0,
                        'current': total_movies,
                        'total': total_movies,
                        'status': 'Cache complete'
                    }, namespace='/')
                    socketio.emit('loading_complete', namespace='/')
                
            except Exception as e:
                logger.error(f"Error during cache initialization: {e}")
                if socketio:
                    socketio.emit('loading_progress', {
                        'progress': 1.0,
                        'error': str(e),
                        'status': 'Error building cache'
                    }, namespace='/')
                    socketio.emit('loading_complete', namespace='/') 
            finally:
                self._initializing = False

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

            logger.info(f"Cache Path Check: Using movies_cache_path = {movies_cache_path}")
            logger.info(f"Cache Path Check: Using metadata_cache_path = {metadata_cache_path}")
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

    def _is_watched_by_user(self, movie, username):
        """Check if a specific user has watched this movie"""
        try:
            history = movie.history()

            for view in history:
                if view.account.title.lower() == username.lower():
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking user watch status for {movie.title}: {e}")
            return False

    def save_cache_to_disk(self):
        """Save current cache state to disk"""
        movies_cache_path = self.MOVIES_CACHE_FILE
        metadata_cache_path = self.METADATA_CACHE_FILE
        if hasattr(self, 'username') and self.username:
            user_data_dir = f'/app/data/user_data/plex_{self.username}'
            os.makedirs(user_data_dir, exist_ok=True) 
            movies_cache_path = os.path.join(user_data_dir, 'plex_unwatched_movies.json')
            metadata_cache_path = os.path.join(user_data_dir, 'plex_metadata_cache.json')

        logger.info(f"Attempting to save cache for instance ({self.username or 'global'})")
        logger.info(f"Saving unwatched cache to: {movies_cache_path}")
        logger.info(f"Saving metadata cache to: {metadata_cache_path}")

        try:
            start_time = time.time()
            with open(movies_cache_path, 'w') as f:
                json.dump(self._movies_cache, f)
            logger.info(f"Successfully saved unwatched cache to {movies_cache_path}")

            with open(metadata_cache_path, 'w') as f:
                json.dump(self._metadata_cache, f)

            logger.info(f"Successfully saved metadata cache to {metadata_cache_path}")
            logger.info(f"Cache saved to disk successfully in {time.time() - start_time:.2f} seconds for instance ({self.username or 'global'})")
        except Exception as e:
            logger.error(f"Error saving cache to disk for instance ({self.username or 'global'}): {e}")

    @lru_cache(maxsize=1024)
    def _get_guid_tmdb_id(self, rating_key):
        """Cache TMDb ID lookups"""
        try:
            movie = self.plex.fetchItem(int(rating_key))
            for guid in movie.guids:
                if 'tmdb://' in guid.id:
                    return guid.id.split('//')[1]
        except Exception:
            pass
        return None

    def _basic_movie_data(self, movie):
        """Get basic movie data with optimized caching and attribute collection"""
        try:
            duration_ms = movie.duration or 0
            movie_duration_hours = (duration_ms / (1000 * 60 * 60)) % 24
            movie_duration_minutes = (duration_ms / (1000 * 60)) % 60

            tmdb_id = self._get_guid_tmdb_id(movie.ratingKey)

            directors = {director.tag for director in movie.directors} if hasattr(movie, 'directors') else set()
            writers = {writer.tag for writer in movie.writers} if hasattr(movie, 'writers') else set()
            actors = {role.tag for role in movie.roles} if hasattr(movie, 'roles') else set()
            genres = {genre.tag for genre in movie.genres} if hasattr(movie, 'genres') else set()

            movie_data = {
                "id": movie.ratingKey,
                "tmdb_id": tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "duration_hours": int(movie_duration_hours),
                "duration_minutes": int(movie_duration_minutes),
                "description": movie.summary,
                "poster": movie.thumbUrl,
                "background": movie.artUrl,
                "contentRating": movie.contentRating,
                "videoFormat": "Unknown",
                "audioFormat": "Unknown",
                "directors": list(directors),
                "writers": list(writers),
                "actors": list(actors),
                "genres": list(genres)
            }

            enriched_cache_key = f"enriched_{movie.ratingKey}"
            if enriched_cache_key in self._metadata_cache:
                movie_data.update(self._metadata_cache[enriched_cache_key])
                return movie_data

            try:
                from utils.fetch_movie_links import fetch_movie_links
                current_service = 'plex'  
                tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie_data, current_service)

                enriched_data = {
                    "tmdb_url": tmdb_url,
                    "trakt_url": trakt_url,
                    "imdb_url": imdb_url,
                    "actors_enriched": [
                        {
                            "name": name,
                            "id": None,
                            "type": "actor",
                            "department": "Acting"
                        }
                        for name in actors
                    ],
                    "directors_enriched": [
                        {
                            "name": name,
                            "id": None,
                            "type": "director",
                            "department": "Directing"
                        }
                        for name in directors
                    ],
                    "writers_enriched": [
                        {
                            "name": name,
                            "id": None,
                            "type": "writer",
                            "department": "Writing"
                        }
                        for name in writers
                    ]
                }

                self._metadata_cache[enriched_cache_key] = enriched_data
                movie_data.update(enriched_data)

            except Exception as e:
                logger.error(f"Error enriching movie data for {movie.title}: {e}")
                movie_data.update({
                    "tmdb_url": None,
                    "trakt_url": None,
                    "imdb_url": None,
                    "actors_enriched": [{"name": name, "id": None, "type": "actor"} for name in actors],
                    "directors_enriched": [{"name": name, "id": None, "type": "director"} for name in directors],
                    "writers_enriched": [{"name": name, "id": None, "type": "writer"} for name in writers]
                })

            return movie_data

        except Exception as e:
            logger.error(f"Error in _basic_movie_data for movie {getattr(movie, 'title', 'Unknown')}: {e}")
            return {
                "id": getattr(movie, 'ratingKey', None),
                "title": getattr(movie, 'title', 'Unknown Movie'),
                "year": getattr(movie, 'year', None),
                "duration_hours": 0,
                "duration_minutes": 0,
                "description": getattr(movie, 'summary', ''),
                "poster": getattr(movie, 'thumbUrl', None),
                "background": getattr(movie, 'artUrl', None),
                "contentRating": getattr(movie, 'contentRating', None),
                "videoFormat": "Unknown",
                "audioFormat": "Unknown",
                "directors": [],
                "writers": [],
                "actors": [],
                "genres": [],
                "actors_enriched": [],
                "directors_enriched": [],
                "writers_enriched": []
            }

    @lru_cache(maxsize=512)
    def _fetch_metadata(self, rating_key):
        """Fetch extended metadata from Plex API"""
        metadata_url = f"{self.PLEX_URL}/library/metadata/{rating_key}?includeChildren=1"
        headers = {"X-Plex-Token": self.PLEX_TOKEN, "Accept": "application/json"}
        try:
            response = requests.get(metadata_url, headers=headers)
            if response.status_code == 200:
                metadata = response.json()
                return metadata.get('MediaContainer', {}).get('Metadata', [{}])[0]
        except Exception as e:
            logger.error(f"Error fetching metadata: {e}")
        return None
            
    def _enrich_with_metadata(self, movie_data, metadata):
        """Enrich movie data with extended metadata"""
        try:
            roles = metadata.get('Role', [])
            actors = []
            actors_enriched = []
            for role in roles:
                actor_name = role.get('tag')
                actor_id = role.get('id')
                if actor_name:
                    actors.append(actor_name)
                    actors_enriched.append({
                        "name": actor_name,
                        "id": actor_id,
                        "type": "actor",
                        "department": "Acting",
                        "thumb": role.get('thumb'),
                        "role": role.get('role')
                    })

            directors = metadata.get('Director', [])
            directors_list = []
            directors_enriched = []
            for director in directors:
                director_name = director.get('tag')
                director_id = director.get('id')
                if director_name:
                    directors_list.append(director_name)
                    directors_enriched.append({
                        "name": director_name,
                        "id": director_id,
                        "type": "director",
                        "department": "Directing",
                        "thumb": director.get('thumb'),
                        "job": director.get('role')
                    })

            writers = metadata.get('Writer', [])
            writers_list = []
            writers_enriched = []
            for writer in writers:
                writer_name = writer.get('tag')
                writer_id = writer.get('id')
                if writer_name:
                    writers_list.append(writer_name)
                    writers_enriched.append({
                        "name": writer_name,
                        "id": writer_id,
                        "department": "Writing",
                        "type": "writer",
                        "thumb": writer.get('thumb'),
                        "job": writer.get('role')
                    })

            if actors:
                movie_data['actors'] = actors
                movie_data['actors_enriched'] = actors_enriched

            if directors_list:
                movie_data['directors'] = directors_list
                movie_data['directors_enriched'] = directors_enriched

            if writers_list:
                movie_data['writers'] = writers_list
                movie_data['writers_enriched'] = writers_enriched

            media_list = metadata.get('Media', [])
            if media_list:
                media = media_list[0]
                part_list = media.get('Part', [])
                if part_list:
                    part = part_list[0]
                    streams = part.get('Stream', [])

                    video_stream = next((s for s in streams if s.get('streamType') == 1), None)
                    if video_stream:
                        height = video_stream.get('height', 0)
                        resolution = "Unknown"
                        if height <= 480: resolution = "SD"
                        elif height <= 720: resolution = "HD"
                        elif height <= 1080: resolution = "FHD"
                        elif height > 1080: resolution = "4K"

                        hdr_types = []
                        if video_stream.get('DOVIPresent'): hdr_types.append("DV")
                        if video_stream.get('colorTrc') == 'smpte2084' and video_stream.get('colorSpace') == 'bt2020nc': hdr_types.append("HDR10")
                        movie_data['videoFormat'] = f"{resolution} {'/'.join(hdr_types)}".strip()

                    audio_stream = next((s for s in streams if s.get('streamType') == 2), None)
                    if audio_stream:
                        codec = audio_stream.get('codec', '').lower()
                        channels = audio_stream.get('channels', 0)
                        codec_map = {'ac3': 'Dolby Digital', 'eac3': 'Dolby Digital Plus', 'truehd': 'Dolby TrueHD',
                                    'dca': 'DTS', 'dts': 'DTS', 'aac': 'AAC', 'flac': 'FLAC', 'dca-ma': 'DTS-HD MA'}
                        audio_format = codec_map.get(codec, codec.upper())
                        if audio_stream.get('audioChannelLayout'):
                            channel_layout = audio_stream['audioChannelLayout'].split('(')[0]
                            audio_format += f" {channel_layout}"
                        elif channels:
                            if channels == 8: audio_format += ' 7.1'
                            elif channels == 6: audio_format += ' 5.1'
                            elif channels == 2: audio_format += ' stereo'
                        movie_data['audioFormat'] = audio_format
        except Exception as e:
            logger.error(f"Error enriching movie data: {e}")

    def update_watched_status(self, movie_id, username):
        """
        Update the watched status of a movie in relevant caches (global and user-specific if owner).
        This is typically called after playback stops.
        Removes the movie from the unwatched list and associated metadata.
        """
        movie_id_str = str(movie_id)
        logger.info(f"Updating watched status for movie {movie_id_str} triggered by user '{username}'")

        try:
            from .cache_manager import CacheManager 
            socketio = getattr(self, 'socketio', None) or getattr(self._cache_manager, 'socketio', None)
            app = getattr(self, 'app', None) or getattr(self._cache_manager, 'app', None)
            global_cache_manager = CacheManager.get_user_cache_manager(self, socketio, app, username=None) 
            if global_cache_manager:
                 logger.info(f"Calling remove_watched_movies on global cache manager for movie {movie_id_str}")
                 global_cache_manager.remove_watched_movies([movie_id_str]) 
            else:
                 logger.error("Could not get global cache manager instance to update watched status.")
        except Exception as e:
            logger.error(f"Error updating global cache for watched movie {movie_id_str}: {e}")

        try:
            owner_username = None
            try:
                owner_username = self.plex.myPlexAccount().username
            except Exception as owner_err:
                logger.warning(f"Could not determine Plex owner username during watched update: {owner_err}")

            if owner_username and username and username.lower() == owner_username.lower():
                logger.info(f"Watched event user '{username}' is owner. Updating owner's user-specific cache...")
                socketio = getattr(self, 'socketio', None) or getattr(self._cache_manager, 'socketio', None)
                app = getattr(self, 'app', None) or getattr(self._cache_manager, 'app', None)
                owner_cache_manager = CacheManager.get_user_cache_manager(self, socketio, app, username=username, service_type='plex')
                if owner_cache_manager:
                    logger.info(f"Calling remove_watched_movies on owner's ({username}) cache manager for movie {movie_id_str}")
                    owner_cache_manager.remove_watched_movies([movie_id_str]) 
                else:
                    logger.error(f"Could not get owner's ({username}) cache manager instance to update watched status.")
            else:
                 logger.info(f"Watched event user '{username}' is not owner ('{owner_username}'). No user-specific cache update needed from here.")

        except Exception as e:
            logger.error(f"Error updating owner's user-specific cache for watched movie {movie_id_str}: {e}")

    def get_movie_data(self, movie):
        """Get complete movie data, using cached metadata if available"""
        movie_data = self._basic_movie_data(movie)

        cache_key = str(movie.ratingKey)
        if cache_key in self._metadata_cache:
            self._enrich_with_metadata(movie_data, self._metadata_cache[cache_key])
        else:
            metadata = self._fetch_metadata(movie.ratingKey)
            if metadata:
                self._metadata_cache[cache_key] = metadata
                self._enrich_with_metadata(movie_data, metadata)

        try:
            movie_data['watched'] = movie.isWatched
        except Exception as e:
            logger.error(f"Error getting watch status for {movie.title} (ID: {getattr(movie, 'ratingKey', 'N/A')}): {e}", exc_info=True) 
            movie_data['watched'] = False

        if 'actors_enriched' not in movie_data:
            movie_data['actors_enriched'] = [{"name": name, "id": None, "type": "actor"}
                                           for name in movie_data.get('actors', [])]
        if 'directors_enriched' not in movie_data:
            movie_data['directors_enriched'] = [{"name": name, "id": None, "type": "director"}
                                              for name in movie_data.get('directors', [])]
        if 'writers_enriched' not in movie_data:
            movie_data['writers_enriched'] = [{"name": name, "id": None, "type": "writer"}
                                            for name in movie_data.get('writers', [])]

        return movie_data

    def set_cache_manager(self, cache_manager):
        """Set cache manager instance"""
        self._cache_manager = cache_manager
        
    def get_random_movie(self):
        """Get a random movie from all movies in library (instead of just unwatched)."""
        try:
            cache_manager = self._cache_manager

            if cache_manager:
                all_movies = cache_manager.get_all_plex_movies()
                if all_movies:
                    movie = random.choice(all_movies)
                    logger.info(f"Selected random movie for screensaver from ALL movies cache: {movie['title']}")
                    return {
                        'title': movie['title'], 'poster': movie['poster'],
                        'contentRating': movie.get('contentRating', ''), 'videoFormat': movie.get('videoFormat', ''),
                        'audioFormat': movie.get('audioFormat', ''), 'year': movie.get('year', '')
                    }
                else:
                    logger.warning("Cache manager returned no ALL movies, falling back to unwatched cache if available.")
            else:
                logger.warning("No cache manager found; falling back to unwatched cache.")

            if self._movies_cache:
                movie = random.choice(self._movies_cache)
                logger.info(f"Selected random movie for screensaver from UNWATCHED cache fallback: {movie['title']}")
                return {
                    'title': movie['title'], 'poster': movie['poster'],
                    'contentRating': movie.get('contentRating', ''), 'videoFormat': movie.get('videoFormat', ''),
                    'audioFormat': movie.get('audioFormat', ''), 'year': movie.get('year', '')
                }

            logger.warning("No movies available for screensaver (both all-movies and unwatched are empty).")
            return None

        except Exception as e:
            logger.error(f"Error getting random movie for screensaver: {e}")
            return None

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        """Filter movies based on criteria and return a random movie"""
        try:
            start_time = time.time()
            logger.info(f"Starting to filter movies with watch_status: {watch_status}")

            if not watch_status:
                watch_status = 'unwatched'

            plex_instance = self._get_user_plex_instance()

            filtered_movies = []
            if watch_status == 'unwatched':
                filtered_movies = self._movies_cache.copy()
                logger.info(f"Using unwatched cache: {len(filtered_movies)} movies")
            else:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        cache_manager = current_app.config.get('CACHE_MANAGER')
                        if not cache_manager:
                            logger.error("Cache manager not available")
                            return None

                        cache_path = cache_manager.all_movies_cache_path

                        if not os.path.exists(cache_path):
                            logger.info("All movies cache not ready, falling back to unwatched")
                            filtered_movies = self._movies_cache.copy()
                        else:
                            with open(cache_path, 'r') as f:
                                all_movies = json.load(f)

                            logger.info(f"Got {len(all_movies)} movies from metadata cache")

                            if watch_status == 'watched':
                                filtered_movies = [m for m in all_movies if m.get('watched', False)]
                                logger.info(f"Found {len(filtered_movies)} watched movies using 'watched' flag")

                                if not filtered_movies:
                                    unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                    filtered_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                                    logger.info(f"Found {len(filtered_movies)} watched movies using ID exclusion")
                            else:  
                                filtered_movies = all_movies
                                logger.info(f"Using all movies: {len(filtered_movies)}")

                except Exception as e:
                    logger.error(f"Error accessing cache manager: {e}")
                    filtered_movies = self._movies_cache.copy()  

            if not filtered_movies:
                logger.error(f"No valid movies found for status: {watch_status}")
                return None

            logger.info(f"Initial movies count: {len(filtered_movies)}")

            if genres:
                filtered_movies = [movie for movie in filtered_movies if any(genre in movie.get('genres',[]) for genre in genres)]
                logger.info(f"After genre filter: {len(filtered_movies)} movies")

            if years:
                filtered_movies = [movie for movie in filtered_movies if str(movie.get('year')) in years]
                logger.info(f"After year filter: {len(filtered_movies)} movies")

            if pg_ratings:
                filtered_movies = [movie for movie in filtered_movies if movie.get('contentRating') in pg_ratings]
                logger.info(f"After rating filter: {len(filtered_movies)} movies")

            if filtered_movies:
                movie = random.choice(filtered_movies)
                duration = (time.time() - start_time) * 1000
                logger.info(f"Movie selection took {duration:.2f}ms")
                return movie

            return None

        except Exception as e:
            logger.error(f"Error in filter_movies: {str(e)}")
            return None

    def get_next_movie(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        """Get next random movie based on criteria"""
        return self.filter_movies(genres, years, pg_ratings, watch_status)

    def get_genres(self, watch_status='unwatched'):
        """Get genres based on watch status using user perspective"""
        try:
            genres = set()

            plex_instance = self._get_user_plex_instance()

            if watch_status == 'unwatched':
                movies = self._movies_cache
            else:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        cache_manager = current_app.config.get('CACHE_MANAGER')
                        if not cache_manager:
                            return sorted(list(set([g for m in self._movies_cache for g in m.get('genres', [])])))

                        cache_path = cache_manager.all_movies_cache_path
                        if not os.path.exists(cache_path):
                            return sorted(list(set([g for m in self._movies_cache for g in m.get('genres', [])])))

                        with open(cache_path, 'r') as f:
                            all_movies = json.load(f)

                        if watch_status == 'watched':
                            watched_movies = [m for m in all_movies if m.get('watched', False)]
                            if not watched_movies:
                                unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                watched_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                            movies = watched_movies
                        else:  
                            movies = all_movies
                except Exception as e:
                    logger.error(f"Error accessing cache for genres: {e}")
                    movies = self._movies_cache

            for movie in movies:
                if movie.get('genres'):
                    genres.update(movie['genres'])
            return sorted(list(genres))
        except Exception as e:
            logger.error(f"Error getting genres: {e}")
            return []

    def get_years(self, watch_status='unwatched'):
        """Get years based on watch status using user perspective"""
        try:
            years = set()

            plex_instance = self._get_user_plex_instance()

            if watch_status == 'unwatched':
                movies = self._movies_cache
            else:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        cache_manager = current_app.config.get('CACHE_MANAGER')
                        if not cache_manager:
                            return sorted([m.get('year') for m in self._movies_cache if m.get('year')], reverse=True)

                        cache_path = cache_manager.all_movies_cache_path
                        if not os.path.exists(cache_path):
                            return sorted([m.get('year') for m in self._movies_cache if m.get('year')], reverse=True)

                        with open(cache_path, 'r') as f:
                            all_movies = json.load(f)

                        if watch_status == 'watched':
                            watched_movies = [m for m in all_movies if m.get('watched', False)]
                            if not watched_movies:
                                unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                watched_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                            movies = watched_movies
                        else:  
                            movies = all_movies
                except Exception as e:
                    logger.error(f"Error accessing cache for years: {e}")
                    movies = self._movies_cache

            for movie in movies:
                if movie.get('year'):
                    years.add(movie['year'])
            return sorted(list(years), reverse=True)
        except Exception as e:
            logger.error(f"Error getting years: {e}")
            return []

    def get_pg_ratings(self, watch_status='unwatched'):
        """Get PG ratings based on watch status using user perspective"""
        try:
            ratings = set()

            plex_instance = self._get_user_plex_instance()

            if watch_status == 'unwatched':
                movies = self._movies_cache
            else:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        cache_manager = current_app.config.get('CACHE_MANAGER')
                        if not cache_manager:
                            return sorted([m.get('contentRating') for m in self._movies_cache if m.get('contentRating')])

                        cache_path = cache_manager.all_movies_cache_path
                        if not os.path.exists(cache_path):
                            return sorted([m.get('contentRating') for m in self._movies_cache if m.get('contentRating')])

                        with open(cache_path, 'r') as f:
                            all_movies = json.load(f)

                        if watch_status == 'watched':
                            watched_movies = [m for m in all_movies if m.get('watched', False)]
                            if not watched_movies:
                                unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                watched_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                            movies = watched_movies
                        else:  
                            movies = all_movies
                except Exception as e:
                    logger.error(f"Error accessing cache for ratings: {e}")
                    movies = self._movies_cache

            for movie in movies:
                if movie.get('contentRating'):
                    ratings.add(movie['contentRating'])
            return sorted(list(ratings))
        except Exception as e:
            logger.error(f"Error getting PG ratings: {e}")
            return []

    def get_clients(self):
        """Get available Plex clients"""
        return [{"id": client.machineIdentifier, "title": client.title}
                for client in self.plex.clients()]

    def play_movie(self, movie_id, client_id):
        """Play a movie on specified client"""
        try:
            movie = None
            plex_instance = self._get_user_plex_instance() 
            for library_name in self.library_names: 
                try:
                    fresh_library = plex_instance.library.section(library_name)
                    movie = fresh_library.fetchItem(int(movie_id))
                    if movie:
                        break 
                except Exception as e:
                    logger.error(f"Error fetching movie {movie_id} from library '{library_name}': {e}")
                    continue 

            if not movie:
                raise ValueError(f"Movie with id {movie_id} not found in any library")

            client = next((c for c in self.plex.clients()
                         if c.machineIdentifier == client_id), None)
            if not client:
                raise ValueError(f"Unknown client id: {client_id}")

            try:
                client.proxyThroughServer()
                client.playMedia(movie)
            except requests.exceptions.ReadTimeout:
                logger.warning(f"Timeout while waiting for response from client {client.title}, but play command was sent")
            except Exception as e:
                raise e

            username = None
            try:
                username = client.usernames[0] if client.usernames else None
                logger.info(f"Playing movie for user: {username} on client: {client.title}")
            except:
                logger.info("Could not determine username for client")

            self.playback_start_times[movie_id] = datetime.now()

            movie_data = next((m for m in self._movies_cache
                            if str(m['id']) == str(movie_id)), None)
            if not movie_data:
                movie_data = self.get_movie_data(movie)

            return {"status": "playing", "username": username}  
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_total_unwatched_movies(self):
        """Get total count of unwatched movies from cache"""
        return len(self._movies_cache)

    def get_all_unwatched_movies(self, progress_callback=None):
        """Get all unwatched movies with metadata"""
        if progress_callback:
            progress_callback(1.0)  
        return self._movies_cache

    def get_movie_by_id(self, movie_id):
        """Get movie by ID from cache first, then Plex if needed"""
        movie_id_str = str(movie_id) 
        cached_movie = next((movie for movie in self._movies_cache
                           if str(movie.get('id')) == movie_id_str), None) 
        if cached_movie:
            return cached_movie
        try:
            movie_id_int = int(movie_id) 
            plex_instance = self._get_user_plex_instance() 

            for library_name in self.library_names: 
                try:
                    fresh_library = plex_instance.library.section(library_name)
                    movie = fresh_library.fetchItem(movie_id_int)
                    if movie:
                        try:
                            movie_data = self.get_movie_data(movie)
                            if movie_data:
                                if not cached_movie:
                                     logger.info(f"get_movie_by_id: Adding newly fetched movie ID {movie_id_str} ('{movie.title}') to memory cache.")
                                     self._movies_cache.append(movie_data)
                                return movie_data
                            else:
                                logger.warning(f"get_movie_by_id: get_movie_data returned None for ID {movie_id_int} ('{movie.title}') from library '{library_name}' even after fetchItem succeeded.")
                        except Exception as get_data_err:
                            logger.error(f"get_movie_by_id: Error calling get_movie_data for ID {movie_id_int} ('{getattr(movie, 'title', 'N/A')}') from library '{library_name}': {get_data_err}", exc_info=True)
                except Exception as e:
                    if 'NotFound' in str(e):
                         logger.debug(f"get_movie_by_id: Movie ID {movie_id_int} not found in library '{library_name}' using perspective '{perspective}'.")
                    else:
                         logger.error(f"get_movie_by_id: Error fetching movie ID {movie_id_int} from library '{library_name}' using perspective '{perspective}': {e}")
            
            logger.warning(f"get_movie_by_id: Movie with ID {movie_id_str} not found via Plex in any configured library ({self.library_names}) using perspective '{perspective}'.")
            return None
        except Exception as outer_err:
            logger.error(f"get_movie_by_id: Unexpected error processing movie ID {movie_id_str}: {outer_err}", exc_info=True)
            return None

    def get_playback_info(self, item_id):
        """Get playback information for a movie"""
        try:
            for session in self.plex.sessions():
                if str(session.ratingKey) == str(item_id):
                    position_ms = session.viewOffset or 0
                    duration_ms = session.duration or 0
                    position_seconds = position_ms / 1000
                    total_duration_seconds = duration_ms / 1000

                    session_state = session.player.state.lower()
                    is_paused = session_state == 'paused'
                    is_playing = session_state == 'playing'
                    is_buffering = session_state == 'buffering'

                    if is_buffering:
                        is_playing = True
                        is_paused = False

                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration_seconds)

                    if session.viewOffset and session.duration:
                        if (session.viewOffset / session.duration) > 0.9:  
                            username = session.user.title if hasattr(session, 'user') and hasattr(session.user, 'title') else None
                            if username:
                                logger.info(f"Detected movie {item_id} watched >= 90% by user '{username}'. Updating status.")
                                self.update_watched_status(item_id, username)
                            else:
                                logger.warning(f"Could not determine username for session watching item {item_id}. Cannot update watched status.")

                    return {
                        'id': str(item_id),
                        'is_playing': is_playing,
                        'IsPaused': is_paused,
                        'IsStopped': False,
                        'position': position_seconds,
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'duration': total_duration_seconds
                    }
            return {
                'id': str(item_id),
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'end_time': None,
                'duration': 0
            }
        except Exception as e:
            logger.error(f"Error fetching playback info: {e}")
            return None

    def reload(self):
        """Reset and reload cache"""
        self._movies_cache = []
        self._metadata_cache = {}
        self._cache_loaded = False
        self._load_from_disk_cache()

    def refresh_cache(self, force=False, from_cache_manager=False):
        """Force refresh the cache"""
        if from_cache_manager and hasattr(self, '_is_coordinated_build') and self._is_coordinated_build:
            logger.info(f"Processing coordinated cache refresh from cache manager for ({self.username or 'global'}).")
        else:
            if self._initializing:
                logger.info(f"Refresh skipped: Initialization already in progress for instance ({self.username or 'global'}).")
                return

        socketio = None
        if hasattr(self, '_cache_manager') and self._cache_manager and hasattr(self._cache_manager, 'socketio'):
            socketio = self._cache_manager.socketio
            logger.info("Using cache_manager's socketio for progress updates")
        elif hasattr(self, 'socketio') and self.socketio:
            socketio = self.socketio
            logger.info("Using direct socketio reference for progress updates")
        
        if socketio:
            socketio.emit('loading_progress', {
                'progress': 0.05,
                'current': 0,
                'total': 0,
                'status': f'Starting cache build for {self.username or "global"}...'
            }, namespace='/')
            logger.info(f"Emitted initial loading event for user: {self.username or 'global'}")
        else:
            logger.warning("No socketio available for progress updates, loading overlay won't appear")

        with PlexService._cache_lock:
            if not from_cache_manager:
                if self._initializing:
                     logger.info(f"Refresh skipped: Initialization started by another thread for instance ({self.username or 'global'}) while waiting for lock.")
                     return

            if force:
                logger.info(f"Forcing cache refresh for instance ({self.username or 'global'}): Clearing existing cache data.")
                self._movies_cache = []
                self._metadata_cache = {}
                self._cache_loaded = False 

            if not from_cache_manager and self._cache_loaded and not force:
                 logger.info(f"Cache already initialized/refreshed for instance ({self.username or 'global'}), skipping redundant refresh.")
                 return

            self._initializing = True

        try:
            self._initialize_cache()
        except Exception as e:
            logger.error(f"Error refreshing cache: {e}")
            
            if socketio:
                socketio.emit('loading_progress', {
                    'progress': 1.0,
                    'error': str(e),
                    'status': 'Error building cache'
                }, namespace='/')
        finally:
            self._initializing = False
            
            if socketio and not self._cache_loaded:
                socketio.emit('loading_complete', namespace='/')
                logger.info(f"Forced loading_complete event for {self.username or 'global'} as cache build ended")
