import os
import requests
import json
import logging
import random
import time
import threading
import re 
from threading import Thread, Lock
from datetime import datetime, timedelta
from .settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JellyfinService:
    def __init__(self, url=None, api_key=None, user_id=None, update_interval=600):
        jellyfin_settings = settings.get('jellyfin', {}) 
        self.server_url = url or jellyfin_settings.get('url') or os.getenv('JELLYFIN_URL')
        self.admin_api_key = api_key or jellyfin_settings.get('api_key') or os.getenv('JELLYFIN_API_KEY')
        self.admin_user_id = user_id or jellyfin_settings.get('user_id') or os.getenv('JELLYFIN_USER_ID')

        if settings.get('jellyfin', 'enabled'):
            if not all([self.server_url, self.admin_api_key, self.admin_user_id]):
                logger.warning("Jellyfin URL, default API key, or default user ID might be missing in settings/ENV. Background tasks might fail if user-specific credentials aren't provided.")

        self.update_interval = update_interval
        self.last_cache_update = 0
        self.cache_path = '/app/data/jellyfin_all_movies.json'
        self.is_updating = False
        self._cache_lock = threading.Lock()
        self.running = False
        self._start_cache_updater()

        self.playback_start_times = {}

    def _get_request_details(self, user_id=None, api_key=None):
        """Determines the user_id, api_key, and headers for a request."""
        target_user_id = user_id or self.admin_user_id
        target_api_key = api_key or self.admin_api_key

        if not target_user_id or not target_api_key:
            raise ValueError("Cannot make Jellyfin request: Missing User ID or API Key (either user-specific or admin default).")

        headers = {
            'X-Emby-Token': target_api_key,
            'Content-Type': 'application/json'
        }
        return target_user_id, target_api_key, headers

    def _start_cache_updater(self):
        """Start the cache updater thread"""
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()
        logger.info("Jellyfin cache updater thread started")

    def stop_cache_updater(self):
        """Stop the cache updater thread"""
        self.running = False

    def _update_loop(self):
        """Background thread that periodically updates the cache"""
        while self.running:
            try:
                current_time = time.time()
                if current_time - self.last_cache_update >= self.update_interval:
                    with self._cache_lock:
                        if self.admin_user_id and self.admin_api_key: 
                            logger.info("Starting Jellyfin cache update using admin credentials")
                            self.cache_all_jellyfin_movies() 
                            self.last_cache_update = current_time
                            logger.info("Jellyfin cache update completed")
                time.sleep(60)  
            except Exception as e:
                logger.error(f"Error in Jellyfin cache update loop: {e}")
                time.sleep(5)  

    def cache_all_jellyfin_movies(self):
        """Cache all movies for Jellyfin badge checking"""
        if self.is_updating:
            logger.info("Jellyfin cache update already in progress, skipping")
            return

        try:
            self.is_updating = True
            cache_user_id, cache_api_key, cache_headers = self._get_request_details() 
            movies_url = f"{self.server_url}/Users/{cache_user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProviderIds'
            }
            response = requests.get(movies_url, headers=cache_headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            all_movies = []
            for movie in movies:
                all_movies.append({
                    "jellyfin_id": movie['Id'],
                    "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb')  
                })

            temp_path = f"{self.cache_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(all_movies, f)
            os.replace(temp_path, self.cache_path)

            logger.info(f"Cached {len(all_movies)} total Jellyfin movies")
            return all_movies
        except Exception as e:
            logger.error(f"Error caching all Jellyfin movies: {e}")
            return []
        finally:
            self.is_updating = False

    def get_unwatched_count(self, user_id=None, api_key=None):
        """Get count of unwatched movies"""
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items"

            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'IsPlayed': 'false'  
            }
            response = requests.get(movies_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('TotalRecordCount', 0)
        except Exception as e:
            logger.error(f"Error getting unwatched count: {e}")
            return 0

    def get_random_movie(self, user_id=None, api_key=None):
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false'
            }
            response = requests.get(movies_url, headers=headers, params=params)
            response.raise_for_status()
            movies = response.json()
            if movies.get('Items'):
                movie_data = self.get_movie_data(movies['Items'][0])
                return movie_data
            logger.warning("No movies found for screensaver")
            return None
        except Exception as e:
            logger.error(f"Error fetching random movie: {e}")
            return None

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched', user_id=None, api_key=None):
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false' 
            }

            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            genres = genres if genres and genres[0] else None
            years = years if years and years[0] else None
            pg_ratings = pg_ratings if pg_ratings and pg_ratings[0] else None

            if genres:
                params['Genres'] = genres
            if years:
                params['Years'] = years
            if pg_ratings:
                params['OfficialRatings'] = pg_ratings

            logger.debug(f"Jellyfin API request params: {params}")

            response = requests.get(movies_url, headers=headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            logger.debug(f"Jellyfin API returned {len(movies)} movies")

            if not movies:
                logger.warning("No unwatched movies found matching the criteria")
                return None

            chosen_movie = random.choice(movies)
            return self.get_movie_data(chosen_movie, user_id=target_user_id, api_key=api_key)
        except Exception as e:
            logger.error(f"Error filtering movies: {str(e)}")
            return None

    def movie_matches_criteria(self, movie, genres, years, pg_ratings):
        if genres and not any(genre in movie.get('Genres', []) for genre in genres):
            return False
        if years and str(movie.get('ProductionYear', '')) not in years:
            return False
        if pg_ratings and movie.get('OfficialRating', '') not in pg_ratings:
            return False
        return True

    def get_movie_data(self, movie, user_id=None, api_key=None):
        target_user_id, target_api_key, _ = self._get_request_details(user_id, api_key)
        run_time_ticks = movie.get('RunTimeTicks', 0)
        total_minutes = run_time_ticks // 600000000  
        hours = total_minutes // 60
        minutes = total_minutes % 60

        video_format = "Unknown"
        audio_format = "Unknown"

        if 'MediaSources' in movie and movie['MediaSources']:
            media_sources = movie['MediaSources']
            if media_sources and isinstance(media_sources, list):
                media_source = media_sources[0]

                if 'MediaStreams' in media_source:
                    video_streams = [s for s in media_source['MediaStreams'] if s['Type'] == 'Video']
                    if video_streams:
                        video_stream = video_streams[0]
                        height = video_stream.get('Height', 0)

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

                        hdr_types = []
                        if video_stream.get('VideoRange') == 'HDR':
                            if 'DV' in video_stream.get('Title', ''):
                                hdr_types.append('DV')
                            if video_stream.get('VideoRangeType') == 'HDR10':
                                hdr_types.append('HDR10')
                            elif video_stream.get('VideoRangeType') == 'HDR10+':
                                hdr_types.append('HDR10+')
                            elif not hdr_types:  
                                hdr_types.append('HDR')

                        video_format_parts = [resolution]
                        if hdr_types:
                            video_format_parts.append('/'.join(hdr_types))

                        video_format = ' '.join(video_format_parts)

                    audio_streams = [s for s in media_source['MediaStreams'] if s['Type'] == 'Audio']
                    if audio_streams:
                        audio_stream = audio_streams[0]

                        profile = audio_stream.get('Profile', '')
                        if profile:
                            profile_parts = [part.strip() for part in profile.split('+')]

                            if "Dolby TrueHD" in profile_parts and "Dolby Atmos" in profile_parts:
                                profile_parts = ["TrueHD" if part == "Dolby TrueHD" else part for part in profile_parts]

                            audio_format = ' + '.join(profile_parts)
                        else:
                            codec = audio_stream.get('Codec', '').upper()
                            codec_map = {
                                'AC3': 'Dolby Digital',
                                'EAC3': 'Dolby Digital Plus',
                                'TRUEHD': 'Dolby TrueHD',
                                'DTS': 'DTS',
                                'DTSHD': 'DTS-HD',
                                'AAC': 'AAC',
                                'FLAC': 'FLAC'
                            }
                            audio_format = codec_map.get(codec, codec)

                        layout = audio_stream.get('Layout', '')
                        if layout and layout not in audio_format:
                            audio_format += f" {layout}"

                        parts = audio_format.split()
                        audio_format = ' '.join(dict.fromkeys(parts))

        all_people = movie.get('People', [])
    
        directors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "director",
                "job": p.get('Role', ''),
                "department": "Directing"
            }
            for p in all_people if p.get('Type') == 'Director'
        ]

        writers = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "writer",
                "job": p.get('Role', ''),
                "department": "Writing"
            }
            for p in all_people if p.get('Type') == 'Writer'
        ]

        actors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "actor",
                "character": p.get('Role', ''),
                "department": "Acting"
            }
            for p in all_people if p.get('Type') == 'Actor'
        ]

        return {
            "id": movie.get('Id', ''),
            "title": movie.get('Name', ''),
            "year": movie.get('ProductionYear', ''),
            "duration_hours": hours,
            "duration_minutes": minutes,
            "description": movie.get('Overview', ''),
            "genres": movie.get('Genres', []),
            "poster": f"{self.server_url}/Items/{movie['Id']}/Images/Primary?api_key={target_api_key}", 
            "background": f"{self.server_url}/Items/{movie['Id']}/Images/Backdrop?api_key={target_api_key}" if movie.get('BackdropImageTags') else None, 
            "ProviderIds": movie.get('ProviderIds', {}),
            "contentRating": movie.get('OfficialRating', ''),
            "videoFormat": video_format,
            "audioFormat": audio_format,
            "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb'),
            "directors_enriched": directors,
            "writers_enriched": writers,
            "actors_enriched": actors,
            "directors": [d["name"] for d in directors],
            "writers": [w["name"] for w in writers],
            "actors": [a["name"] for a in actors]
        }

    def get_genres(self):
        try:
            target_user_id, _, headers = self._get_request_details() 
            items_url = f"{self.server_url}/Users/{target_user_id}/Items" 
            params = {
                'Recursive': 'true',
                'Fields': 'Genres',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_genres = set()
            for item in data.get('Items', []):
                all_genres.update(item.get('Genres', []))

            genre_list = sorted(list(all_genres))
            logger.debug(f"Extracted genre list: {genre_list}")
            return genre_list
        except Exception as e:
            logger.error(f"Error fetching genres: {e}")
            return []

    def get_years(self):
        try:
            target_user_id, _, headers = self._get_request_details() 
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items" 
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProductionYear'
            }
            response = requests.get(movies_url, headers=headers, params=params)
            response.raise_for_status()
            movies = response.json()
            years = set(movie.get('ProductionYear') for movie in movies.get('Items', []) if movie.get('ProductionYear'))
            year_list = sorted(list(years), reverse=True)
            logger.debug(f"Fetched years: {year_list}")
            return year_list
        except Exception as e:
            logger.error(f"Error fetching years: {e}")
            return []

    def get_pg_ratings(self):
        try:
            target_user_id, _, headers = self._get_request_details() 
            items_url = f"{self.server_url}/Users/{target_user_id}/Items" 
            params = {
                'Recursive': 'true',
                'Fields': 'OfficialRating',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_ratings = set()
            for item in data.get('Items', []):
                rating = item.get('OfficialRating')
                if rating:
                    all_ratings.add(rating)

            rating_list = sorted(list(all_ratings))
            logger.debug(f"Extracted PG rating list: {rating_list}")
            return rating_list
        except Exception as e:
            logger.error(f"Error fetching PG ratings: {e}")
            return []

    def get_playback_info(self, item_id):
        try:
            _, _, headers = self._get_request_details()
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=headers)
            response.raise_for_status()
            sessions = response.json()
            for session in sessions:
                if session.get('NowPlayingItem', {}).get('Id') == item_id:
                    playstate = session.get('PlayState', {})
                    position_ticks = playstate.get('PositionTicks', 0)
                    is_paused = playstate.get('IsPaused', False)

                    position_seconds = position_ticks / 10_000_000
                    total_duration = session['NowPlayingItem']['RunTimeTicks'] / 10_000_000

                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration)

                    is_stopped = session.get('PlayState', {}).get('PlayMethod') is None or session.get('NowPlayingItem') is None

                    return {
                        'is_playing': not is_paused and not is_stopped,
                        'IsPaused': is_paused,
                        'IsStopped': is_stopped,
                        'position': position_seconds,
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'duration': total_duration
                    }
            return {
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'end_time': None,
                'duration': 0
            }
        except requests.RequestException as e:
            logger.error(f"Error fetching playback info: {e}")
        return None

    def get_clients(self, user_id=None, api_key=None):
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=headers, params={'userId': target_user_id}) 
            response.raise_for_status()
            sessions = response.json()

            logger.debug(f"Raw sessions data: {json.dumps(sessions, indent=2)}")

            castable_clients = []
            for session in sessions:
                if session.get('SupportsRemoteControl', False) and session.get('DeviceName') != 'Jellyfin Server':
                    client = {
                        "title": session.get('DeviceName', 'Unknown Device'),
                        "id": session.get('Id'),
                        "client": session.get('Client'),
                        "username": session.get('UserName'),
                        "device_id": session.get('DeviceId'),
                        "supports_media_control": session.get('SupportsMediaControl', False),
                    }
                    castable_clients.append(client)

            if not castable_clients:
                logger.warning("No castable clients found.")
            else:
                logger.info(f"Found {len(castable_clients)} castable clients")

            logger.debug(f"Fetched castable clients: {json.dumps(castable_clients, indent=2)}")
            return castable_clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def get_movie_by_id(self, movie_id, user_id=None, api_key=None):
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            item_url = f"{self.server_url}/Users/{target_user_id}/Items/{movie_id}"
            params = {
                'Fields': 'Overview,People,Genres,RunTimeTicks,ProviderIds,UserData,OfficialRating'
            }
            response = requests.get(item_url, headers=headers, params=params)
            response.raise_for_status()
            movie = response.json()
            return self.get_movie_data(movie, user_id=target_user_id, api_key=api_key)
        except Exception as e:
            logger.error(f"Error fetching movie by ID: {e}")
            return None

    def get_current_playback(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions_json = response.json()
            logger.debug(f"Sessions JSON Response: {json.dumps(sessions_json, indent=2)}")

            if isinstance(sessions_json, list):
                sessions = sessions_json
            elif isinstance(sessions_json, dict):
                sessions = sessions_json.get('Items', [])
            else:
                logger.error("Unexpected JSON structure for sessions.")
                return None

            for session in sessions:
                if not isinstance(session, dict):
                    logger.warning("Session item is not a dictionary. Skipping.")
                    continue

                now_playing = session.get('NowPlayingItem')
                if now_playing:
                    return {
                        'id': now_playing.get('Id'),
                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000  
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching current playback: {e}")
            return None

    def play_movie(self, movie_id, session_id, user_id=None, api_key=None):
        """Play a movie on a specific Jellyfin session"""
        try:
            target_user_id, target_api_key, headers = self._get_request_details(user_id, api_key)

            playback_url = f"{self.server_url}/Sessions/{session_id}/Playing"
            params = {
                'ItemIds': movie_id,
                'PlayCommand': 'PlayNow'
            }

            username = None
            try:
                all_sessions_url = f"{self.server_url}/Sessions"
                all_sessions_response = requests.get(all_sessions_url, headers=headers)
                all_sessions_response.raise_for_status()
                all_sessions_data = all_sessions_response.json()
                
                for session_info in all_sessions_data:
                    if session_info.get('Id') == session_id:
                        username = session_info.get('UserName')
                        if username:
                            logger.info(f"Determined username '{username}' for session {session_id} during play_movie.")
                        else:
                            logger.warning(f"Username not found in session data for session_id {session_id}.")
                        break
                if not username:
                     logger.warning(f"Could not find session_id {session_id} in active sessions to determine username.")
            except Exception as session_err:
                logger.warning(f"Could not determine Jellyfin username for session {session_id} by listing all sessions: {session_err}")

            response = requests.post(playback_url, headers=headers, params=params)
            response.raise_for_status()
            logger.debug(f"Playing movie {movie_id} on session {session_id}")
            logger.debug(f"Response: {response.text}")
        
            self.playback_start_times[movie_id] = datetime.now()
            movie_data = self.get_movie_by_id(movie_id, user_id=target_user_id, api_key=target_api_key)
        
            if movie_data:
                from utils.poster_view import set_current_movie as set_global_current_movie
                set_global_current_movie(movie_data, 'jellyfin', username=username)
                # from flask import session # Keep session for current_service if other parts rely on it
                # session['current_service'] = 'jellyfin'
            
            return {
                "status": "playing",
                "response": response.text,
                "movie_id": movie_id,
                "session_id": session_id,
                "start_time": self.playback_start_times[movie_id].isoformat(),
                "movie_data": movie_data,
                "username": username 
            }
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_active_sessions(self):
        try:
            _, _, headers = self._get_request_details() 
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=headers) 
            response.raise_for_status()
            sessions = response.json()

            active_sessions = []
            for session in sessions:
                if session.get('NowPlayingItem'):
                    active_sessions.append(session)

            logger.debug(f"Found {len(active_sessions)} active Jellyfin sessions")
            return active_sessions
        except Exception as e:
            logger.error(f"Error fetching active Jellyfin sessions: {e}")
            return []

    def get_current_username(self):
        try:
            _, _, headers = self._get_request_details()
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=headers)
            response.raise_for_status()
            sessions = response.json()
            for session in sessions:
                if session.get('NowPlayingItem'):
                    return session.get('UserName')
            return None
        except Exception as e:
            logger.error(f"Error getting current Jellyfin username: {e}")
            return None

    def search_movies(self, query, user_id=None, api_key=None):
        """Search for movies matching the query in titles only"""
        try:
            target_user_id, target_api_key, headers = self._get_request_details(user_id, api_key)
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SearchTerm': query,
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'SearchFields': 'Name',
                'EnableTotalRecordCount': True,
                'Limit': 50,
                'UserId': target_user_id 
            }

            logger.info(f"Searching Jellyfin movies with query: {query} for user {target_user_id}")
            response = requests.get(movies_url, headers=headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            results = []
            try:
                pattern = re.compile(r'\b' + re.escape(query) + r'\b', re.IGNORECASE)
                logger.debug(f"Using regex pattern for Jellyfin search: {pattern.pattern}")
            except re.error as e:
                 logger.error(f"Invalid regex pattern generated for query '{query}': {e}")
                 pattern = None 

            for movie in movies:
                movie_name = movie.get('Name', '')
                if pattern and movie_name and pattern.search(movie_name):
                    movie_data = self.get_movie_data(movie, user_id=target_user_id, api_key=target_api_key)
                    results.append(movie_data)

            logger.info(f"Found {len(results)} Jellyfin movies matching title: {query}")
            return results
        except Exception as e:
            logger.error(f"Error searching Jellyfin movies: {e}")
            return [] 

    def get_filtered_movie_count(self, filters, user_id=None, api_key=None):
        """
        Counts movies matching the provided filters by querying the Jellyfin API.

        Args:
            filters (dict): A dictionary containing filter criteria:
                            {'genres': list, 'years': list, 'pgRatings': list, 'watch_status': str}
            user_id (str, optional): The Jellyfin user ID. Defaults to admin user ID.
            api_key (str, optional): The Jellyfin API key. Defaults to admin API key.

        Returns:
            int: The count of matching movies.
        """
        try:
            target_user_id, _, headers = self._get_request_details(user_id, api_key)
            movies_url = f"{self.server_url}/Users/{target_user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true'
            }

            watch_status = filters.get('watch_status', 'unwatched')
            selected_genres = filters.get('genres', [])
            selected_years = filters.get('years', [])
            selected_pg_ratings = filters.get('pgRatings', [])

            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            if selected_genres:
                params['Genres'] = selected_genres 
            if selected_years:
                params['Years'] = selected_years 
            if selected_pg_ratings:
                params['OfficialRatings'] = selected_pg_ratings 

            logger.debug(f"Jellyfin API count request params (will use repeated params for lists): {params}")

            response = requests.get(movies_url, headers=headers, params=params, timeout=15) 
            response.raise_for_status() 

            data = response.json()

            count = data.get('TotalRecordCount', 0)
            logger.debug(f"Jellyfin API returned count: {count}") 
            return count

        except Exception as e:
            logger.error(f"Error getting filtered movie count from Jellyfin: {str(e)}")
            return 0 

        except Exception as e:
            logger.error(f"Error searching Jellyfin movies: {str(e)}")
            return []
