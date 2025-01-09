import os
import random
import logging
import json
import time
import requests
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

    def __init__(self, url=None, token=None, libraries=None):
        logger.info("Initializing PlexService")
        logger.info(f"Parameters - URL: {bool(url)}, Token: {bool(token)}, Libraries: [REDACTED]")

        # First try settings (from parameters)
        self.PLEX_URL = url
        self.PLEX_TOKEN = token
        self.PLEX_MOVIE_LIBRARIES = libraries if isinstance(libraries, list) else libraries.split(',') if libraries else []

        # Cache file paths
        self.MOVIES_CACHE_FILE = '/app/data/plex_unwatched_movies.json'
        self.METADATA_CACHE_FILE = '/app/data/plex_metadata_cache.json'

        # Fallback to ENV variables if needed
        if not self.PLEX_URL:
            self.PLEX_URL = os.getenv('PLEX_URL')
            logger.info("Using ENV for PLEX_URL")
        if not self.PLEX_TOKEN:
            self.PLEX_TOKEN = os.getenv('PLEX_TOKEN')
            logger.info("Using ENV for PLEX_TOKEN")
        if not self.PLEX_MOVIE_LIBRARIES:
            self.PLEX_MOVIE_LIBRARIES = os.getenv('PLEX_MOVIE_LIBRARIES', 'Movies').split(',')
            logger.info("Using ENV for PLEX_MOVIE_LIBRARIES")

        # Validate required fields
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
            self.libraries = []
            for lib in self.PLEX_MOVIE_LIBRARIES:
                try:
                    library = self.plex.library.section(lib.strip())
                    self.libraries.append(library)
                    logger.info(f"Successfully added library: {lib}")
                except Exception as e:
                    logger.error(f"Failed to add library {lib}: {e}")

            if not self.libraries:
                raise ValueError("No valid libraries found")

        except Exception as e:
            logger.error(f"Error initializing libraries: {e}")
            raise

        self.playback_start_times = {}
        self._metadata_cache = {}
        self._movies_cache = []
        self._cache_loaded = False
        self._initializing_cache = False

        # Try to load from disk cache first
        start_time = time.time()
        if self._load_from_disk_cache():
            logger.info(f"Loaded cache from disk in {time.time() - start_time:.2f} seconds")
            self._cache_loaded = True
        else:
            logger.info("Cache will be built asynchronously")
            self._movies_cache = []

        logger.info("PlexService initialization completed successfully")

    def _load_from_disk_cache(self):
        """Try to load cache from disk"""
        try:
            if os.path.exists(self.MOVIES_CACHE_FILE) and os.path.exists(self.METADATA_CACHE_FILE):
                logger.info("Loading cached data from disk...")

                # Load movies cache
                with open(self.MOVIES_CACHE_FILE, 'r') as f:
                    self._movies_cache = json.load(f)

                # Load metadata cache
                with open(self.METADATA_CACHE_FILE, 'r') as f:
                    self._metadata_cache = json.load(f)

                # Verify cache is still valid
                if self._verify_cache_validity():
                    self._cache_loaded = True
                    logger.info(f"Successfully loaded {len(self._movies_cache)} movies from disk cache")
                    return True
                else:
                    logger.warning("Cache verification failed, will rebuild cache")
                    self._movies_cache = []
                    self._metadata_cache = {}

        except Exception as e:
            logger.error(f"Error loading cache from disk: {e}")
            self._movies_cache = []
            self._metadata_cache = {}

        return False

    def _verify_cache_validity(self):
        """Verify cache is still valid by checking unwatched status"""
        try:
            if not self._movies_cache:
                return False

            # Check a few random movies
            sample_size = min(5, len(self._movies_cache))
            sample_movies = random.sample(self._movies_cache, sample_size)

            for movie in sample_movies:
                # Check if movie still exists and unwatched status matches
                movie_found = False
                for library in self.libraries:
                    try:
                        plex_movie = library.fetchItem(int(movie['id']))
                        if plex_movie and not plex_movie.isWatched:
                            movie_found = True
                            break
                    except:
                        continue
                if not movie_found:
                    return False
            return True

        except Exception as e:
            logger.error(f"Error verifying cache: {e}")
            return False

    def save_cache_to_disk(self):
        """Save current cache state to disk"""
        try:
            start_time = time.time()
            # Save movies cache
            with open(self.MOVIES_CACHE_FILE, 'w') as f:
                json.dump(self._movies_cache, f)

            # Save metadata cache
            with open(self.METADATA_CACHE_FILE, 'w') as f:
                json.dump(self._metadata_cache, f)

            logger.info(f"Cache saved to disk successfully in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Error saving cache to disk: {e}")

    @lru_cache(maxsize=1024)
    def _get_guid_tmdb_id(self, rating_key):
        """Cache TMDb ID lookups"""
        try:
            movie = self.plex.fetchItem(int(rating_key))
            for guid in movie.guids:
                if 'tmdb://' in guid.id:
                    return guid.id.split('//')[1]
        except:
            pass
        return None

    def _basic_movie_data(self, movie):
        """Get basic movie data with optimized caching and attribute collection"""
        try:
            # Fast duration calculations
            duration_ms = movie.duration or 0
            movie_duration_hours = (duration_ms / (1000 * 60 * 60)) % 24
            movie_duration_minutes = (duration_ms / (1000 * 60)) % 60

            # Cache TMDb ID lookup
            tmdb_id = self._get_guid_tmdb_id(movie.ratingKey)

            # Use sets for faster attribute collection
            directors = {director.tag for director in movie.directors} if hasattr(movie, 'directors') else set()
            writers = {writer.tag for writer in movie.writers} if hasattr(movie, 'writers') else set()
            actors = {role.tag for role in movie.roles} if hasattr(movie, 'roles') else set()
            genres = {genre.tag for genre in movie.genres} if hasattr(movie, 'genres') else set()

            # Base movie data with optimized structure
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

            # Check enriched cache first
            enriched_cache_key = f"enriched_{movie.ratingKey}"
            if enriched_cache_key in self._metadata_cache:
                # Use cached enrichment data
                movie_data.update(self._metadata_cache[enriched_cache_key])
                return movie_data

            # If not in cache, get basic URLs
            try:
                from utils.fetch_movie_links import fetch_movie_links
                current_service = 'plex'  # Constant for cache
                tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie_data, current_service)

                # Create optimized enriched structure
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

                # Cache the enriched data
                self._metadata_cache[enriched_cache_key] = enriched_data
                movie_data.update(enriched_data)

            except Exception as e:
                logger.error(f"Error enriching movie data for {movie.title}: {e}")
                # Provide basic enriched structure even if enrichment fails
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
            # Return minimal movie data if processing fails
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
            # Process roles/actors
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

            # Process directors
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

            # Process writers
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

            # Update movie data with both basic and enriched data for all roles
            if actors:
                movie_data['actors'] = actors
                movie_data['actors_enriched'] = actors_enriched

            if directors_list:
                movie_data['directors'] = directors_list
                movie_data['directors_enriched'] = directors_enriched

            if writers_list:
                movie_data['writers'] = writers_list
                movie_data['writers_enriched'] = writers_enriched

            # Process media info for video/audio format
            media_list = metadata.get('Media', [])
            if media_list:
                media = media_list[0]
                part_list = media.get('Part', [])
                if part_list:
                    part = part_list[0]
                    streams = part.get('Stream', [])

                    # Video format extraction
                    video_stream = next((s for s in streams if s.get('streamType') == 1), None)
                    if video_stream:
                        height = video_stream.get('height', 0)
                        if height <= 480:
                            resolution = "SD"
                        elif height <= 720:
                            resolution = "HD"
                        elif height <= 1080:
                            resolution = "FHD"
                        elif height > 1080:
                            resolution = "4K"
                        else:
                            resolution = "Unknown"

                        # Check for HDR and Dolby Vision
                        hdr_types = []
                        if video_stream.get('DOVIPresent'):
                            hdr_types.append("DV")
                        if video_stream.get('colorTrc') == 'smpte2084' and video_stream.get('colorSpace') == 'bt2020nc':
                            hdr_types.append("HDR10")

                        # Combine resolution and HDR info
                        movie_data['videoFormat'] = f"{resolution} {'/'.join(hdr_types)}".strip()

                    # Audio format extraction
                    audio_stream = next((s for s in streams if s.get('streamType') == 2), None)
                    if audio_stream:
                        codec = audio_stream.get('codec', '').lower()
                        channels = audio_stream.get('channels', 0)

                        codec_map = {
                            'ac3': 'Dolby Digital',
                            'eac3': 'Dolby Digital Plus',
                            'truehd': 'Dolby TrueHD',
                            'dca': 'DTS',
                            'dts': 'DTS',
                            'aac': 'AAC',
                            'flac': 'FLAC',
                            'dca-ma': 'DTS-HD MA'
                        }

                        audio_format = codec_map.get(codec, codec.upper())

                        if audio_stream.get('audioChannelLayout'):
                            channel_layout = audio_stream['audioChannelLayout'].split('(')[0]
                            audio_format += f" {channel_layout}"
                        elif channels:
                            if channels == 8:
                                audio_format += ' 7.1'
                            elif channels == 6:
                                audio_format += ' 5.1'
                            elif channels == 2:
                                audio_format += ' stereo'

                        movie_data['audioFormat'] = audio_format

        except Exception as e:
            logger.error(f"Error enriching movie data: {e}")

    def _initialize_cache(self):
        """Load all movies and their metadata at startup"""
        logger.info("Initializing movie cache...")
        start_time = time.time()
        all_movies = []
        for library in self.libraries:
            all_movies.extend(library.search(unwatched=True))

        total_movies = len(all_movies)
        logger.info(f"Found {total_movies} unwatched movies to cache")

        self._movies_cache = []

        # Batch load metadata for all movies
        for i, movie in enumerate(all_movies, 1):
            try:
                # Fetch metadata if not cached
                metadata = self._fetch_metadata(movie.ratingKey)
                if metadata:
                    self._metadata_cache[str(movie.ratingKey)] = metadata

                movie_data = self._basic_movie_data(movie)
                if metadata:
                    self._enrich_with_metadata(movie_data, metadata)
                self._movies_cache.append(movie_data)

                if i % 10 == 0:  # Log progress every 10 movies
                    progress = (i / total_movies) * 100
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    logger.info(f"Cached {i}/{total_movies} movies ({progress:.1f}%) - {rate:.1f} movies/sec")

            except Exception as e:
                logger.error(f"Error caching movie {movie.title}: {e}")

        logger.info(f"Cache initialized with {len(self._movies_cache)} movies in {time.time() - start_time:.2f} seconds")

    def update_watched_status(self, movie_id):
        """Remove movie from cache when watched and update counts"""
        logger.info(f"Updating watched status for movie {movie_id}")

        # Remove from unwatched movies cache only
        self._movies_cache = [m for m in self._movies_cache if str(m['id']) != str(movie_id)]

        # Clean up both regular and enriched metadata
        base_key = str(movie_id)
        enriched_key = f"enriched_{movie_id}"

        if base_key in self._metadata_cache:
            del self._metadata_cache[base_key]
        if enriched_key in self._metadata_cache:
            del self._metadata_cache[enriched_key]

        self.save_cache_to_disk()
    
        # Ensure CacheManager has updated counts
        if hasattr(self, 'cache_manager'):
            self.cache_manager._init_memory_cache()
        
        logger.info(f"Removed movie {movie_id} from unwatched cache, new total: {len(self._movies_cache)}")

    def add_new_movie(self, movie):
        """Add new unwatched movie to cache"""
        logger.info(f"Adding new movie to cache: {movie.title}")
        movie_data = self.get_movie_data(movie)
        self._movies_cache.append(movie_data)
        self.save_cache_to_disk()

        if hasattr(self, 'cache_manager'):
            self.cache_manager.cache_all_plex_movies()

        logger.info(f"Added movie {movie.title} to cache")

    def get_movie_data(self, movie):
        """Get complete movie data, using cached metadata if available"""
        movie_data = self._basic_movie_data(movie)

        # Use cached metadata if available
        cache_key = str(movie.ratingKey)
        if cache_key in self._metadata_cache:
            self._enrich_with_metadata(movie_data, self._metadata_cache[cache_key])
        else:
            # Fetch and cache if not available
            metadata = self._fetch_metadata(movie.ratingKey)
            if metadata:
                self._metadata_cache[cache_key] = metadata
                self._enrich_with_metadata(movie_data, metadata)

        # Enriched structure (will have TMDb IDs if available)
        if not 'actors_enriched' in movie_data:
            movie_data['actors_enriched'] = [{"name": name, "id": None, "type": "actor"}
                                           for name in movie_data.get('actors', [])]
        if not 'directors_enriched' in movie_data:
            movie_data['directors_enriched'] = [{"name": name, "id": None, "type": "director"}
                                              for name in movie_data.get('directors', [])]
        if not 'writers_enriched' in movie_data:
            movie_data['writers_enriched'] = [{"name": name, "id": None, "type": "writer"}
                                            for name in movie_data.get('writers', [])]

        return movie_data

    def get_random_movie(self):
        """Now uses in-memory cache"""
        if not self._movies_cache:
            logger.info("No movies in cache")
            return None
        movie = random.choice(self._movies_cache)
        source = "memory" if self._cache_loaded else "plex"
        logger.info(f"Movie '{movie['title']}' loaded from {source} cache")
        return movie

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        try:
            start_time = time.time()
            logger.info(f"Starting to filter movies with watch_status: {watch_status}")

            if not watch_status:
                watch_status = 'unwatched'

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

                        # Check if all_movies cache exists
                        if not os.path.exists(cache_manager.all_movies_cache_path):
                            logger.info("All movies cache not ready, falling back to unwatched")
                            filtered_movies = self._movies_cache.copy()
                        else:
                            all_movies = cache_manager.get_all_plex_movies()
                            logger.info(f"Got {len(all_movies)} movies from metadata cache")

                            if watch_status == 'watched':
                                unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                filtered_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                                logger.info(f"Found {len(filtered_movies)} watched movies")
                            else:  # 'all'
                                filtered_movies = all_movies
                                logger.info(f"Using all movies: {len(filtered_movies)}")

                except Exception as e:
                    logger.error(f"Error accessing cache manager: {e}")
                    filtered_movies = self._movies_cache.copy()  # Fallback to unwatched

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
        try:
            start_time = time.time()
            logger.info(f"Starting next movie selection with watch_status: {watch_status}")

            if not watch_status:
                watch_status = 'unwatched'

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

                        # Check if all_movies cache exists
                        if not os.path.exists(cache_manager.all_movies_cache_path):
                            logger.info("All movies cache not ready, falling back to unwatched")
                            filtered_movies = self._movies_cache.copy()
                        else:
                            all_movies = cache_manager.get_all_plex_movies()
                            logger.info(f"Got {len(all_movies)} movies from metadata cache")

                            if watch_status == 'watched':
                                unwatched_ids = {str(m['id']) for m in self._movies_cache}
                                filtered_movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                                logger.info(f"Found {len(filtered_movies)} watched movies")
                            else:  # 'all'
                                filtered_movies = all_movies
                                logger.info(f"Using all movies: {len(filtered_movies)}")

                except Exception as e:
                    logger.error(f"Error accessing cache manager: {e}")
                    filtered_movies = self._movies_cache.copy()  # Fallback to unwatched

            if not filtered_movies:
                logger.error(f"No valid movies found for status: {watch_status}")
                return None

            logger.info(f"Initial movies count: {len(filtered_movies)}")
            logger.info(f"Filter params - genres: {genres}, years: {years}, ratings: {pg_ratings}, watch_status: {watch_status}")

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
                logger.info(f"Next movie selection took {duration:.2f}ms")
                return movie

            return None

        except Exception as e:
            logger.error(f"Error in get_next_movie: {str(e)}")
            return None

    def get_genres(self, watch_status='unwatched'):
        """Get genres based on watch status"""
        try:
            genres = set()
            if watch_status == 'unwatched':
                # Use unwatched cache
                movies = self._movies_cache
            else:
                # Get all movies
                cache_manager = current_app.config.get('CACHE_MANAGER')
                all_movies = cache_manager.get_all_plex_movies()
                if watch_status == 'watched':
                    # Filter for watched movies by excluding unwatched ones
                    unwatched_ids = {str(m['id']) for m in self._movies_cache}
                    movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                else:  # 'all'
                    movies = all_movies

            for movie in movies:
                if movie.get('genres'):
                    genres.update(movie['genres'])
            return sorted(list(genres))
        except Exception as e:
            logger.error(f"Error getting genres: {e}")
            return []

    def get_years(self, watch_status='unwatched'):
        """Get years based on watch status"""
        try:
            years = set()
            if watch_status == 'unwatched':
                movies = self._movies_cache
            else:
                cache_manager = current_app.config.get('CACHE_MANAGER')
                all_movies = cache_manager.get_all_plex_movies()
                if watch_status == 'watched':
                    unwatched_ids = {str(m['id']) for m in self._movies_cache}
                    movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                else:  # 'all'
                    movies = all_movies

            for movie in movies:
                if movie.get('year'):
                    years.add(movie['year'])
            return sorted(list(years), reverse=True)
        except Exception as e:
            logger.error(f"Error getting years: {e}")
            return []

    def get_pg_ratings(self, watch_status='unwatched'):
        """Get PG ratings based on watch status"""
        try:
            ratings = set()
            if watch_status == 'unwatched':
                movies = self._movies_cache
            else:
                cache_manager = current_app.config.get('CACHE_MANAGER')
                all_movies = cache_manager.get_all_plex_movies()
                if watch_status == 'watched':
                    unwatched_ids = {str(m['id']) for m in self._movies_cache}
                    movies = [m for m in all_movies if str(m['id']) not in unwatched_ids]
                else:  # 'all'
                    movies = all_movies

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
            for library in self.libraries:
                try:
                    movie = library.fetchItem(int(movie_id))
                    if movie:
                        break
                except:
                    continue

            if not movie:
                raise ValueError(f"Movie with id {movie_id} not found in any library")

            client = next((c for c in self.plex.clients()
                         if c.machineIdentifier == client_id), None)
            if not client:
                raise ValueError(f"Unknown client id: {client_id}")

            client.proxyThroughServer()
            client.playMedia(movie)

            # Set the start time for the movie
            self.playback_start_times[movie_id] = datetime.now()

            # If movie was watched, update cache
            if movie.isWatched:
                self.update_watched_status(movie_id)

            # Use cached movie data if available
            movie_data = next((m for m in self._movies_cache
                             if str(m['id']) == str(movie_id)), None)
            if not movie_data:
                movie_data = self.get_movie_data(movie)

            if movie_data:
                set_current_movie(movie_data, service='plex', resume_position=0)
            return {"status": "playing"}
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_total_unwatched_movies(self):
        """Get total count of unwatched movies from cache"""
        return len(self._movies_cache)

    def get_all_unwatched_movies(self, progress_callback=None):
        """Get all unwatched movies with metadata"""
        if progress_callback:
            progress_callback(1.0)  # Since we're using cache, we're already done
        return self._movies_cache

    def get_movie_by_id(self, movie_id):
        """Get movie by ID from cache first, then Plex if needed"""
        # Try cache first
        cached_movie = next((movie for movie in self._movies_cache
                           if str(movie['id']) == str(movie_id)), None)
        if cached_movie:
            return cached_movie

        # If not in cache, try Plex
        for library in self.libraries:
            try:
                movie = library.fetchItem(int(movie_id))
                return self.get_movie_data(movie)
            except:
                continue
        logger.error(f"Movie with id {movie_id} not found in any library")
        return None

    def get_all_movies_with_metadata(self):
        """Get all movies with full metadata"""
        try:
            # Try loading from metadata cache first
            metadata_cache_path = '/app/data/plex_metadata_cache.json'
            if os.path.exists(metadata_cache_path):
                with open(metadata_cache_path, 'r') as f:
                    return json.load(f)

            # If no cache, build full movie data
            all_movies = []
            for library in self.libraries:
                movies = library.all()
                for movie in movies:
                    try:
                        movie_data = self.get_movie_data(movie)
                        if movie_data:
                            all_movies.append(movie_data)
                    except Exception as e:
                        logger.error(f"Error getting data for movie {movie.title}: {e}")

            # Cache the results
            with open(metadata_cache_path, 'w') as f:
                json.dump(all_movies, f)

            return all_movies
        except Exception as e:
            logger.error(f"Error getting all movies with metadata: {e}")
            return []

    def get_playback_info(self, item_id):
        """Get playback information for a movie"""
        try:
            for session in self.plex.sessions():
                if str(session.ratingKey) == str(item_id):
                    position_ms = session.viewOffset or 0
                    duration_ms = session.duration or 0
                    position_seconds = position_ms / 1000
                    total_duration_seconds = duration_ms / 1000

                    # Correctly access the playback state
                    session_state = session.player.state.lower()
                    is_paused = session_state == 'paused'
                    is_playing = session_state == 'playing'
                    is_buffering = session_state == 'buffering'

                    # Handle buffering state
                    if is_buffering:
                        is_playing = True
                        is_paused = False

                    # Use stored start time or current time if not available
                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration_seconds)

                    # Check if movie was just watched and update cache if needed
                    if session.viewOffset and session.duration:
                        if (session.viewOffset / session.duration) > 0.9:  # 90% watched
                            self.update_watched_status(item_id)

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
            # If no matching session found, the movie is stopped
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

    def refresh_cache(self, force=False):
        """Force refresh the cache"""
        if force:
            self._movies_cache = []
            self._metadata_cache = {}
        self._initialize_cache()
        self.save_cache_to_disk()
        logger.info("Cache refreshed successfully")

    def cleanup_metadata_cache(self, max_size=1000):
        """Clean up metadata cache if it gets too large"""
        if len(self._metadata_cache) > max_size:
            # Remove oldest entries to get back to max_size
            items_to_remove = len(self._metadata_cache) - max_size
            for _ in range(items_to_remove):
                self._metadata_cache.pop(next(iter(self._metadata_cache)))
            logger.info(f"Cleaned up metadata cache, removed {items_to_remove} items")

    def get_clients(self):
        """Get available Plex clients"""
        return [{"id": client.machineIdentifier, "title": client.title}
                for client in self.plex.clients()]

    def play_movie(self, movie_id, client_id):
        """Play a movie on specified client"""
        try:
            movie = None
            for library in self.libraries:
                try:
                    movie = library.fetchItem(int(movie_id))
                    if movie:
                        break
                except:
                    continue

            if not movie:
                raise ValueError(f"Movie with id {movie_id} not found in any library")

            client = next((c for c in self.plex.clients()
                         if c.machineIdentifier == client_id), None)
            if not client:
                raise ValueError(f"Unknown client id: {client_id}")

            client.proxyThroughServer()
            client.playMedia(movie)

            # Set the start time for the movie
            self.playback_start_times[movie_id] = datetime.now()

            # If movie was watched, update cache
            if movie.isWatched:
                self.update_watched_status(movie_id)

            # Use cached movie data if available
            movie_data = next((m for m in self._movies_cache
                             if str(m['id']) == str(movie_id)), None)
            if not movie_data:
                movie_data = self.get_movie_data(movie)

            if movie_data:
                set_current_movie(movie_data, service='plex', resume_position=0)
            return {"status": "playing"}
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_total_unwatched_movies(self):
        """Get total count of unwatched movies from cache"""
        return len(self._movies_cache)

    def get_all_unwatched_movies(self, progress_callback=None):
        """Get all unwatched movies with metadata"""
        if progress_callback:
            progress_callback(1.0)  # Since we're using cache, we're already done
        return self._movies_cache

    def get_movie_by_id(self, movie_id):
        """Get movie by ID from cache first, then Plex if needed"""
        # Try cache first
        cached_movie = next((movie for movie in self._movies_cache
                           if str(movie['id']) == str(movie_id)), None)
        if cached_movie:
            return cached_movie

        # If not in cache, try Plex
        for library in self.libraries:
            try:
                movie = library.fetchItem(int(movie_id))
                return self.get_movie_data(movie)
            except:
                continue
        logger.error(f"Movie with id {movie_id} not found in any library")
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

                    # Correctly access the playback state
                    session_state = session.player.state.lower()
                    is_paused = session_state == 'paused'
                    is_playing = session_state == 'playing'
                    is_buffering = session_state == 'buffering'

                    # Handle buffering state
                    if is_buffering:
                        is_playing = True
                        is_paused = False

                    # Use stored start time or current time if not available
                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration_seconds)

                    # Check if movie was just watched and update cache if needed
                    if session.viewOffset and session.duration:
                        if (session.viewOffset / session.duration) > 0.9:  # 90% watched
                            self.update_watched_status(item_id)

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
            # If no matching session found, the movie is stopped
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

    def refresh_cache(self, force=False):
        """Force refresh the cache"""
        if force:
            self._movies_cache = []
            self._metadata_cache = {}
        self._initialize_cache()
        self.save_cache_to_disk()
        logger.info("Cache refreshed successfully")

    def cleanup_metadata_cache(self, max_size=1000):
        """Clean up metadata cache if it gets too large"""
        if len(self._metadata_cache) > max_size:
            # Remove oldest entries to get back to max_size
            items_to_remove = len(self._metadata_cache) - max_size
            for _ in range(items_to_remove):
                self._metadata_cache.pop(next(iter(self._metadata_cache)))
            logger.info(f"Cleaned up metadata cache, removed {items_to_remove} items")

    def search_movies(self, query):
        """Search for movies matching the query"""
        try:
            logger.info(f"Searching for movies with query: {query}")
            results = []

            # Search all movie libraries
            for library in self.libraries:
                try:
                    # Use the Plex search functionality
                    movies = library.search(title=query, libtype="movie")

                    for movie in movies:
                        try:
                            if query.lower() in movie.title.lower():  # Title match check
                                # Use get_movie_data to get full metadata instead of basic_movie_data
                                movie_data = self.get_movie_data(movie)
                                if movie_data:
                                    results.append(movie_data)
                        except Exception as e:
                            logger.error(f"Error processing movie {movie.title} in search results: {e}")
                            continue

                except Exception as e:
                    logger.error(f"Error searching library {library.title}: {e}")
                    continue

            # Remove any duplicates based on movie ID
            seen_ids = set()
            unique_results = []
            for movie in results:
                if movie['id'] not in seen_ids:
                    seen_ids.add(movie['id'])
                    unique_results.append(movie)

            logger.info(f"Found {len(unique_results)} unique movies matching query: {query}")
            return unique_results

        except Exception as e:
            logger.error(f"Error in search_movies: {e}")
            return []
