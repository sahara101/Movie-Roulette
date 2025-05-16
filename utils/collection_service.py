import logging
import os
import json
from functools import lru_cache
from datetime import datetime
from utils.tmdb_service import tmdb_service

logger = logging.getLogger(__name__)

class CollectionService:
    """Service to handle movie collection related operations"""

    def __init__(self):
        self.cache = {}

    @lru_cache(maxsize=100)
    def get_collection_info(self, collection_id):
        """Get detailed information about a movie collection by ID"""
        logger.info(f"Fetching collection info for collection ID: {collection_id}")
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

        logger.info(f"Checking if movie {tmdb_id} belongs to a collection")
        movie_details = tmdb_service.get_movie_details(tmdb_id)

        if not movie_details or not movie_details.get('belongs_to_collection'):
            return None

        collection_id = movie_details['belongs_to_collection']['id']
        collection_name = movie_details['belongs_to_collection']['name']
        logger.info(f"Movie {tmdb_id} belongs to collection: {collection_name} (ID: {collection_id})")

        return self.get_collection_info(collection_id)

    def get_previous_movies_in_collection(self, tmdb_id):
        """
        Get list of movies that come before the given movie in a collection

        Args:
            tmdb_id: The TMDb ID of the movie

        Returns:
            list: List of previous movies in the collection
        """
        logger.info(f"Finding previous movies in collection for movie {tmdb_id}")
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
                logger.warning(f"Overseerr configured for {current_service} but only works with Plex")
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
                    logger.info(f"No compatible request service configured for {current_service}") 
                    return False  

            logger.debug(f"Checking request status with service: {request_service} for tmdb_id={tmdb_id}")

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

        logger.info(f"check_request_status for {tmdb_id} returning: False") 
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
        logger.info(f"Checking collection status for movie {tmdb_id} on {current_service}")

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

        logger.info(f"Identified {len(previous_movies)} previous movies and {len(other_movies)} other movies for {tmdb_id}") 

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

            is_watched = self._is_movie_watched(movie['id'])

            is_requested = self.check_request_status(movie['id'])

            logger.info(f"Previous movie {movie['id']} ({movie['title']}): In Library={in_library}, Watched={is_watched}, Requested={is_requested}") 
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

            logger.info(f"Other movie {movie['id']} ({movie['title']}): In Library={in_library}, Requested={is_requested}") 
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
                            logger.info(f"Found future unowned/unrequested movie: {movie['title']} (ID: {movie['id']})")
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
        logger.info(f"Final collection status for {tmdb_id}: {json.dumps(final_result, indent=2)}")
        return final_result

    def _is_movie_in_plex(self, tmdb_id):
        """Check if a movie exists in the Plex library"""
        try:
            cache_path = '/app/data/plex_all_movies.json'
            logger.info(f"_is_movie_in_plex: Checking for {tmdb_id} using cache path: {cache_path}") 
            found = False 
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                found = any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies) 
            logger.info(f"_is_movie_in_plex: Found status for {tmdb_id}: {found}") 
            return found 
        except Exception as e:
            logger.error(f"Error checking Plex library for movie {tmdb_id}: {e}")
            logger.info(f"_is_movie_in_plex: Returning False due to error for {tmdb_id}") 
            return False

    def _is_movie_in_jellyfin(self, tmdb_id):
        """Check if a movie exists in the Jellyfin library"""
        try:
            cache_path = '/app/data/jellyfin_all_movies.json'
            logger.info(f"_is_movie_in_jellyfin: Checking for {tmdb_id} using cache path: {cache_path}") 
            found = False
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                found = any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies)
            logger.info(f"_is_movie_in_jellyfin: Found status for {tmdb_id}: {found}") 
            return found
        except Exception as e:
            logger.error(f"Error checking Jellyfin library for movie {tmdb_id}: {e}")
            logger.info(f"_is_movie_in_jellyfin: Returning False due to error for {tmdb_id}") 
            return False

    def _is_movie_in_emby(self, tmdb_id):
        """Check if a movie exists in the Emby library"""
        try:
            cache_path = '/app/data/emby_all_movies.json'
            logger.info(f"_is_movie_in_emby: Checking for {tmdb_id} using cache path: {cache_path}") 
            found = False
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    all_movies = json.load(f)
                found = any(str(m.get('tmdb_id')) == str(tmdb_id) for m in all_movies)
            logger.info(f"_is_movie_in_emby: Found status for {tmdb_id}: {found}") 
            return found
        except Exception as e:
            logger.error(f"Error checking Emby library for movie {tmdb_id}: {e}")
            logger.info(f"_is_movie_in_emby: Returning False due to error for {tmdb_id}") 
            return False

    def _is_movie_watched(self, tmdb_id):
        """Check if a movie is marked as watched in Trakt"""
        try:
            from utils.trakt_service import get_local_watched_movies
            watched_movies = get_local_watched_movies()
            logger.info(f"_is_movie_watched: Checking {tmdb_id} against {len(watched_movies)} watched movies.") 
            found = int(tmdb_id) in watched_movies
            logger.info(f"_is_movie_watched: Found status for {tmdb_id}: {found}") 
            return found
        except Exception as e:
            logger.error(f"Error checking Trakt watched status for movie {tmdb_id}: {e}")
            logger.info(f"_is_movie_watched: Returning False due to error for {tmdb_id}") 
            return False

collection_service = CollectionService()
