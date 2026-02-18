import logging
import os
import json
from functools import lru_cache
from datetime import datetime
from utils.tmdb_service import tmdb_service
from utils.trakt_service import get_watched_movies as get_trakt_watched_movies, get_local_watched_movies, is_movie_watched as is_movie_watched_on_trakt, is_trakt_enabled_for_user, get_current_user_id
from utils.settings import settings

logger = logging.getLogger(__name__)

class CollectionService:
    """Service to handle movie collection related operations"""

    def __init__(self, app=None, socketio=None):
        self.app = app
        self.cache = {}
        self.socketio = socketio
        self.cache_building = False

    def _get_cache_path(self, user=None, service_name=None):
        """Get the cache path for a specific user and service, ensuring it's in a user-specific directory."""
        from utils.auth import auth_manager
        base_dir = '/app/data'
        
        service_prefix = service_name if service_name else 'plex'
        cache_filename = f'{service_prefix}_collections_cache.json'

        is_admin = user and user.get('is_admin')
        auth_disabled = not auth_manager.auth_enabled

        if user and user.get('internal_username') and not is_admin and not auth_disabled:
            username = user['internal_username']
            user_dir_name = "".join(c for c in username if c.isalnum() or c in ('_', '-')).rstrip()
            user_data_dir = os.path.join(base_dir, 'user_data', user_dir_name)
            
            try:
                os.makedirs(user_data_dir, exist_ok=True)
                return os.path.join(user_data_dir, cache_filename)
            except OSError as e:
                logger.error(f"Failed to create user directory {user_data_dir}: {e}. Falling back to base data directory.")
                return os.path.join(base_dir, f'{service_prefix}_collections_cache_{user_dir_name}.json')

        return os.path.join(base_dir, cache_filename)

    @lru_cache(maxsize=100)
    def get_collection_info(self, collection_id):
        """Get detailed information about a movie collection by ID"""
        return tmdb_service._make_request(f"collection/{collection_id}")

    def get_movie_collection(self, tmdb_id):
        """
        Check if a movie belongs to a collection and return collection info

        Args:
            tmdb_id: The TMDb ID of the movie

        Returns:
            dict: Collection information if the movie is part of a collection, None otherwise
        """
        if not tmdb_id:
            return None

        movie_details = tmdb_service.get_movie_details(tmdb_id)

        if not movie_details or not movie_details.get('belongs_to_collection'):
            return None

        collection_id = movie_details['belongs_to_collection']['id']
        collection_name = movie_details['belongs_to_collection']['name']
        
        return self.get_collection_info(collection_id)

    def get_previous_movies_in_collection(self, tmdb_id):
        """
        Get list of movies that come before the given movie in a collection

        Args:
            tmdb_id: The TMDb ID of the movie

        Returns:
            list: List of previous movies in the collection
        """
        movie_details = tmdb_service.get_movie_details(tmdb_id)
        if not movie_details or not movie_details.get('belongs_to_collection'):
            return []

        collection_id = movie_details['belongs_to_collection']['id']
        collection = self.get_collection_info(collection_id)
        if not collection or 'parts' not in collection:
            return []

        today = datetime.now().strftime('%Y-%m-%d')

        parts = sorted(
            collection['parts'],
            key=lambda x: x.get('release_date', '9999-99-99')
        )

        current_movie_index = next(
            (i for i, part in enumerate(parts) if part['id'] == int(tmdb_id)),
            -1
        )

        if current_movie_index <= 0:  
            return []

        previous_movies = [
            part for part in parts[:current_movie_index]
            if part.get('release_date') and part.get('release_date', '9999-99-99') <= today
        ]

    def check_request_status(self, tmdb_id):
        """Check if a movie has been requested in the appropriate request service for the current media service"""
        from utils.settings import settings

        current_service = getattr(self, '_current_service', None)
        if not current_service:
            try:
                from flask import session
                current_service = session.get('current_service', 'plex')
            except:
                current_service = 'plex'

        try:
            request_config = settings.get('request_services', {})
            default_service = request_config.get('default', 'auto')
            service_override = request_config.get(f'{current_service}_override', 'auto')

            request_service = service_override if service_override != 'auto' else default_service

            if request_service == 'overseerr' and current_service != 'plex':
                return False

            if request_service == 'auto':
                overseerr_enabled = settings.get('overseerr', {}).get('enabled', False)
                jellyseerr_enabled = settings.get('jellyseerr', {}).get('enabled', False)
                ombi_enabled = settings.get('ombi', {}).get('enabled', False)

                if current_service == 'plex' and overseerr_enabled:
                    request_service = 'overseerr'
                elif jellyseerr_enabled:
                    request_service = 'jellyseerr'
                elif ombi_enabled:
                    request_service = 'ombi'
                else:
                    return False  

            if request_service == 'overseerr':
                try:
                    from utils.overseerr_service import get_media_status, OVERSEERR_INITIALIZED
                    if OVERSEERR_INITIALIZED:
                        status = get_media_status(tmdb_id)
                        if status and status.get('mediaInfo'):
                            requested = status['mediaInfo'].get('status') in [2, 3, 4, 5]
                            return requested
                except Exception as e:
                    logger.error(f"Error checking Overseerr status: {e}")

            elif request_service == 'jellyseerr':
                try:
                    from utils.jellyseerr_service import get_media_status, JELLYSEERR_INITIALIZED
                    if JELLYSEERR_INITIALIZED:
                        status = get_media_status(tmdb_id)
                        if status and status.get('mediaInfo'):
                            requested = status['mediaInfo'].get('status') in [2, 3, 4, 5]
                            return requested
                except Exception as e:
                    logger.error(f"Error checking Jellyseerr status: {e}")

            elif request_service == 'ombi':
                try:
                    from utils.ombi_service import get_media_status, OMBI_INITIALIZED
                    if OMBI_INITIALIZED:
                        status = get_media_status(tmdb_id)
                        if status and status.get('mediaInfo'):
                            requested = status['mediaInfo'].get('requested', False)
                            return requested
                except Exception as e:
                    logger.error(f"Error checking Ombi status: {e}")

        except Exception as e:
            logger.error(f"Error determining request service: {e}")

        return False

    def is_request_service_active(self):
        """Check if any request service is configured and enabled."""
        request_config = settings.get('request_services', {})
        overseerr_enabled = settings.get('overseerr', {}).get('enabled', False)
        jellyseerr_enabled = settings.get('jellyseerr', {}).get('enabled', False)
        ombi_enabled = settings.get('ombi', {}).get('enabled', False)

        if any(s in ['overseerr', 'jellyseerr', 'ombi'] for s in request_config.values()):
            return True
        
        if overseerr_enabled or jellyseerr_enabled or ombi_enabled:
            return True
            
        return False

    def check_collection_status(self, tmdb_id, current_service):
        """
        Check the status of a movie collection, including previous movies

        Args:
            tmdb_id: The TMDb ID of the movie
            current_service: The current media service (plex, jellyfin, emby)

        Returns:
            dict: Collection status information
        """
        found_future_unowned_unrequested = False
        movie_details = tmdb_service.get_movie_details(tmdb_id)
        if not movie_details or not movie_details.get('belongs_to_collection'):
            return {
                'is_in_collection': False,
                'previous_movies': []
            }

        collection_name = movie_details['belongs_to_collection']['name']
        collection_id = movie_details['belongs_to_collection']['id']
        collection = self.get_collection_info(collection_id)

        if not collection or 'parts' not in collection:
            return {
                'is_in_collection': True,
                'collection_name': collection_name,
                'collection_id': collection_id,
                'previous_movies': []
            }

        today = datetime.now().strftime('%Y-%m-%d')

        parts = sorted(
            collection['parts'],
            key=lambda x: x.get('release_date', '9999-99-99')
        )

        current_movie_index = next(
            (i for i, part in enumerate(parts) if part['id'] == int(tmdb_id)),
            -1
        )

        previous_movies = [
            part for part in parts[:current_movie_index]
            if part.get('release_date') and part.get('release_date', '9999-99-99') <= today
        ]

        other_movies = [
            part for part in parts
            if part['id'] != int(tmdb_id) and part not in previous_movies
        ]

        result_previous = []
        for movie in previous_movies:
            in_library = False
            try:
                if current_service == 'plex':
                    in_library = self._is_movie_in_plex(movie['id'])
                elif current_service == 'jellyfin':
                    in_library = self._is_movie_in_jellyfin(movie['id'])
                elif current_service == 'emby':
                    in_library = self._is_movie_in_emby(movie['id'])
            except Exception as e:
                logger.error(f"Error checking library status for movie {movie['id']}: {e}")

            is_watched = self._is_movie_watched(movie['id'], self.get_all_movies())

            is_requested = self.check_request_status(movie['id'])

            result_previous.append({
                'id': movie['id'],
                'title': movie['title'],
                'release_date': movie.get('release_date', ''),
                'poster_path': movie.get('poster_path', ''),
                'in_library': in_library,
                'is_watched': is_watched,
                'is_requested': is_requested
            })

        result_other = []
        for movie in other_movies:
            in_library = False
            try:
                if current_service == 'plex':
                    in_library = self._is_movie_in_plex(movie['id'])
                elif current_service == 'jellyfin':
                    in_library = self._is_movie_in_jellyfin(movie['id'])
                elif current_service == 'emby':
                    in_library = self._is_movie_in_emby(movie['id'])
            except Exception as e:
                logger.error(f"Error checking library status for movie {movie['id']}: {e}")

            is_requested = self.check_request_status(movie['id'])

            result_other.append({
                'id': movie['id'],
                'title': movie['title'],
                'release_date': movie.get('release_date', ''),
                'poster_path': movie.get('poster_path', ''),
                'in_library': in_library,
                'is_requested': is_requested
            })

            if not found_future_unowned_unrequested:
                movie_release_date_str = movie.get('release_date')
                if movie_release_date_str:
                    try:
                        movie_release_date = datetime.strptime(movie_release_date_str, '%Y-%m-%d').date()
                        if movie_release_date > datetime.now().date() and not in_library and not is_requested:
                            found_future_unowned_unrequested = True
                    except ValueError:
                        logger.warning(f"Could not parse release_date '{movie_release_date_str}' for movie {movie['id']}")


        final_result = {
            'is_in_collection': True,
            'collection_name': collection_name,
            'collection_id': collection_id,
            'collection_poster': movie_details['belongs_to_collection'].get('poster_path', ''),
            'previous_movies': result_previous,
            'other_movies': result_other,
            'has_future_unowned_unrequested_movie': found_future_unowned_unrequested
        }
        return final_result

    def _is_movie_in_plex(self, tmdb_id):
        """Check if a movie exists in the Plex library"""
        try:
            cache_path = '/app/data/plex_all_movies.json'
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                return any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies) 
        except Exception as e:
            logger.error(f"Error checking Plex library for movie {tmdb_id}: {e}")
        return False

    def _is_movie_in_jellyfin(self, tmdb_id):
        """Check if a movie exists in the Jellyfin library"""
        try:
            cache_path = '/app/data/jellyfin_all_movies.json'
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                return any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies)
        except Exception as e:
            logger.error(f"Error checking Jellyfin library for movie {tmdb_id}: {e}")
        return False

    def _is_movie_in_emby(self, tmdb_id):
        """Check if a movie exists in the Emby library"""
        try:
            cache_path = '/app/data/emby_all_movies.json'
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                return any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies)
        except Exception as e:
            logger.error(f"Error checking Emby library for movie {tmdb_id}: {e}")
        return False

    def _is_movie_watched(self, tmdb_id, all_movies):
        """Check if a movie is marked as watched in the media service"""
        try:
            for movie in all_movies:
                if str(movie.get('tmdb_id')) == str(tmdb_id):
                    return movie.get('watched', False)
        except Exception as e:
            logger.error(f"Error checking watched status for movie {tmdb_id}: {e}")
        return False

    def get_all_movies(self):
        from flask import g
        return g.media_service.get_all_movies('all')

    def get_collections_from_cache(self, user=None, path=None, service_name=None):
        """Get collections from the cache file."""
        cache_path = path or self._get_cache_path(user=user, service_name=service_name)
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                return json.load(f)
        return None


    def build_collections_cache(self, app, current_service, cache_manager=None, user=None, path=None, sid=None):
        """Build and save the collections cache."""
        with app.app_context():
            if self.cache_building:
                return

            self.cache_building = True
            try:
                from flask import g
                from movie_selector import plex, jellyfin, emby
                from utils.cache_manager import CacheManager
                
                if current_service == 'plex':
                    g.media_service = plex
                    if user:
                        g.cache_manager = CacheManager.get_user_cache_manager(
                            plex, self.socketio, app, username=user.get('internal_username'), 
                            service_type='plex', plex_user_id=user.get('id'), user_type=user.get('user_type', 'plex')
                        )
                    elif cache_manager:
                        g.cache_manager = cache_manager
                elif current_service == 'jellyfin':
                    g.media_service = jellyfin
                elif current_service == 'emby':
                    g.media_service = emby
                
                service_instance = g.media_service
                all_movies = service_instance.get_all_movies('all')
                
                collections = {}
                total_movies = len(all_movies)
                for i, movie in enumerate(all_movies):
                    tmdb_id = movie.get('tmdb_id')
                    if tmdb_id:
                        collection_info = self.get_movie_collection(tmdb_id)
                        if collection_info:
                            collection_id = collection_info['id']
                            if collection_id not in collections:
                                collections[collection_id] = {
                                    'id': collection_id,
                                    'name': collection_info['name'],
                                    'poster_path': collection_info.get('poster_path'),
                                    'overview': collection_info.get('overview'),
                                    'movies': []
                                }
                    if self.socketio:
                        self.socketio.emit('collections_cache_progress', {'progress': (i + 1) / total_movies * 50}, room=sid)

                user_id = user['internal_username'] if user else get_current_user_id()
                trakt_enabled = is_trakt_enabled_for_user(user_id)
                trakt_watched_movies = set(get_trakt_watched_movies(user_id)) if trakt_enabled else set()

                if trakt_enabled:
                    trakt_movie_ids = list(trakt_watched_movies)
                    total_trakt_movies = len(trakt_movie_ids)
                    for i, tmdb_id in enumerate(trakt_movie_ids):
                        collection_info = self.get_movie_collection(tmdb_id)
                        if collection_info:
                            collection_id = collection_info['id']
                            if collection_id not in collections:
                                collections[collection_id] = {
                                    'id': collection_id,
                                    'name': collection_info['name'],
                                    'poster_path': collection_info.get('poster_path'),
                                    'overview': collection_info.get('overview'),
                                    'movies': []
                                }
                        if self.socketio and total_trakt_movies > 0:
                            progress = 50 + (i + 1) / total_trakt_movies * 25
                            self.socketio.emit('collections_cache_progress', {'progress': progress}, room=sid)

                all_tmdb_ids = {str(movie.get('tmdb_id')) for movie in all_movies if movie.get('tmdb_id')}

                final_collections = []
                collection_items = list(collections.items())
                total_collections = len(collection_items)
                for i, (collection_id, collection_data) in enumerate(collection_items):
                    collection_info = self.get_collection_info(collection_id)
                    if not collection_info or 'parts' not in collection_info:
                        continue

                    processed_movies = []
                    is_fully_watched = True
                    if not collection_info['parts']:
                        is_fully_watched = False

                    for movie_part in collection_info['parts']:
                        part_tmdb_id = str(movie_part['id'])
                        in_library = part_tmdb_id in all_tmdb_ids
                        is_requested = self.check_request_status(part_tmdb_id) if not in_library else False
                        is_watched_in_library = self._is_movie_watched(part_tmdb_id, all_movies) if in_library else False
                        is_watched_trakt = int(part_tmdb_id) in trakt_watched_movies
                        
                        if not (is_watched_in_library or is_watched_trakt):
                            is_fully_watched = False

                        status = "request"
                        if in_library:
                            status = "Watched" if is_watched_in_library else "In Library"
                        elif is_requested:
                            status = "Requested"
                        elif trakt_enabled:
                            if is_watched_trakt:
                                status = "Watched"
                            else:
                                status = "unwatched"
                        
                        movie_details = tmdb_service.get_movie_details(movie_part['id'])
                        processed_movies.append({
                            'id': movie_part['id'],
                            'title': movie_part['title'],
                            'poster_path': movie_part.get('poster_path') or movie_details.get('poster_path'),
                            'release_date': movie_part.get('release_date') or movie_details.get('release_date'),
                            'overview': movie_details.get('overview', ''),
                            'in_library': in_library,
                            'is_requested': is_requested,
                            'is_watched': is_watched_in_library or is_watched_trakt,
                            'status': status
                        })
                    
                    collection_data['movies'] = processed_movies

                    if not is_fully_watched:
                        final_collections.append(collection_data)

                    if self.socketio and total_collections > 0:
                        progress_start = 75 if trakt_enabled else 50
                        progress_range = 25 if trakt_enabled else 50
                        progress = progress_start + (i + 1) / total_collections * progress_range
                        self.socketio.emit('collections_cache_progress', {'progress': progress}, room=sid)
                
                cache_path = path or self._get_cache_path(user=user, service_name=current_service)
                if cache_path:
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                
                cache_content = {
                    'collections': final_collections,
                    'trakt_enabled_in_cache': trakt_enabled
                }
                with open(cache_path, 'w') as f:
                    json.dump(cache_content, f)
            finally:
                self.cache_building = False
                if self.socketio:
                    self.socketio.emit('collections_cache_complete', room=sid)

    def update_collections_cache(self, app, current_service, cache_manager=None, user=None):
        """Periodically update the collections cache for a user."""
        with app.app_context():
            cache_path = self._get_cache_path(user=user, service_name=current_service)
            if not os.path.exists(cache_path):
                logger.info(f"Cache file not found for user {user['internal_username'] if user else 'default'}. Skipping update.")
                return

            cached_data = self.get_collections_from_cache(user=user, service_name=current_service)
            if not isinstance(cached_data, dict) or 'collections' not in cached_data:
                logger.warning(f"Invalid cache format for user {user['internal_username'] if user else 'default'}. Triggering full rebuild.")
                self.build_collections_cache(app, current_service, cache_manager, user)
                return

            collections = cached_data.get('collections', [])
            if not collections:
                logger.info(f"No collections to update for user {user['internal_username'] if user else 'default'}.")
                return

            logger.info(f"Starting differential cache update for {len(collections)} collections for user {user['internal_username'] if user else 'default'}.")

            if cache_manager and hasattr(cache_manager.get_all_plex_movies, 'cache_clear'):
                cache_manager.get_all_plex_movies.cache_clear()
            all_movies = cache_manager.get_all_plex_movies() if cache_manager else []
            movie_status_map = {str(movie.get('tmdb_id')): movie for movie in all_movies}

            user_id = user['internal_username'] if user else get_current_user_id()
            trakt_enabled = is_trakt_enabled_for_user(user_id)
            trakt_watched_movies = set(get_local_watched_movies(user_id)) if trakt_enabled else set()
            
            cached_movie_ids = {str(movie['id']) for collection in collections for movie in collection.get('movies', [])}

            all_library_movie_ids = set(movie_status_map.keys())
            all_trakt_movie_ids = {str(tmdb_id) for tmdb_id in trakt_watched_movies}
            all_current_movie_ids = all_library_movie_ids.union(all_trakt_movie_ids)

            new_movie_ids_to_check = all_current_movie_ids - cached_movie_ids

            if new_movie_ids_to_check:
                logger.info(f"Found {len(new_movie_ids_to_check)} new movies to check for collections.")
                newly_discovered_collections = {}
                
                for tmdb_id in new_movie_ids_to_check:
                    collection_info = self.get_movie_collection(tmdb_id)
                    if collection_info:
                        collection_id = collection_info['id']
                        if collection_id not in newly_discovered_collections:
                            newly_discovered_collections[collection_id] = collection_info

                if newly_discovered_collections:
                    existing_collection_ids = {c['id'] for c in collections}
                    for collection_id, collection_data in newly_discovered_collections.items():
                        if collection_id not in existing_collection_ids:
                            is_fully_watched = True
                            if not collection_data.get('parts'):
                                is_fully_watched = False
                            else:
                                for movie_part in collection_data.get('parts', []):
                                    part_tmdb_id = str(movie_part['id'])
                                    is_watched_in_library = movie_status_map.get(part_tmdb_id, {}).get('watched', False)
                                    is_watched_trakt = int(part_tmdb_id) in trakt_watched_movies
                                    if not (is_watched_in_library or is_watched_trakt):
                                        is_fully_watched = False
                                        break
                            
                            if not is_fully_watched:
                                logger.info(f"Discovered new incomplete collection: '{collection_data['name']}'. Adding to cache.")
                                
                                processed_collection = {
                                    'id': collection_id,
                                    'name': collection_data['name'],
                                    'poster_path': collection_data.get('poster_path'),
                                    'overview': collection_data.get('overview'),
                                    'movies': []
                                }
                                for movie_part in collection_data.get('parts', []):
                                    processed_collection['movies'].append({
                                        'id': movie_part['id'],
                                        'title': movie_part['title'],
                                        'poster_path': movie_part.get('poster_path'),
                                        'release_date': movie_part.get('release_date'),
                                        'overview': movie_part.get('overview', '')
                                    })
                                collections.append(processed_collection)
                            else:
                                logger.info(f"Discovered new collection '{collection_data['name']}', but it's fully watched. Skipping.")

            for collection in collections:
                for movie in collection.get('movies', []):
                    tmdb_id = str(movie.get('id'))
                    is_watched_in_library = False
                    
                    if tmdb_id in movie_status_map:
                        latest_status = movie_status_map[tmdb_id]
                        movie['in_library'] = True
                        is_watched_in_library = latest_status.get('watched', False)
                    else:
                        movie['in_library'] = False

                    is_watched_trakt = int(tmdb_id) in trakt_watched_movies
                    movie['is_watched'] = is_watched_in_library or is_watched_trakt
                    
                    if movie['in_library']:
                        movie['status'] = "Watched" if movie['is_watched'] else "In Library"
                    elif movie['is_watched']:
                        movie['status'] = "Watched"
                    else:
                        is_requested = self.check_request_status(tmdb_id)
                        movie['is_requested'] = is_requested
                        movie['status'] = "Requested" if is_requested else "Request"

            cached_data['collections'] = collections
            try:
                with open(cache_path, 'w') as f:
                    json.dump(cached_data, f)
                logger.info(f"Successfully updated and saved collections cache for user {user['internal_username'] if user else 'default'}.")
            except Exception as e:
                logger.error(f"Failed to save updated collections cache for user {user['internal_username'] if user else 'default'}: {e}")

collection_service = CollectionService()
