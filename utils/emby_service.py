import os
import requests
import json
import logging
import random
import time
import threading
import uuid
from threading import Thread, Lock
from datetime import datetime, timedelta
from .settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmbyService:
    def __init__(self, url=None, api_key=None, user_id=None, update_interval=600):
        # Try settings first, then fall back to ENV
        self.server_url = url or settings.get('emby', 'url') or os.getenv('EMBY_URL')
        self.api_key = api_key or settings.get('emby', 'api_key') or os.getenv('EMBY_API_KEY')
        self.user_id = user_id or settings.get('emby', 'user_id') or os.getenv('EMBY_USER_ID')

        # Only validate if service is enabled
        if settings.get('emby', 'enabled'):
            if not all([self.server_url, self.api_key, self.user_id]):
                raise ValueError("Emby URL, API key, and user ID are required when enabled")

        # Initialize headers
        self._update_headers()

        self.update_interval = update_interval
        self.last_cache_update = 0
        self.cache_path = '/app/data/emby_all_movies.json'
        self.is_updating = False
        self._cache_lock = threading.Lock()
        self.running = False
        self._start_cache_updater()

        self.playback_start_times = {}

    def _update_headers(self):
        """Update request headers with current API key"""
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json'
        }

    def authenticate_with_connect(self, username, password):
        """Authenticate with Emby Connect using username/password"""
        try:
            connect_url = "https://connect.emby.media/service/user/authenticate"
            data = {
                "nameOrEmail": username,
                "rawpw": password
            }
            headers = {
                'Content-Type': 'application/json',
                'X-Application': 'MovieRoulette/1.0'
            }

            response = requests.post(connect_url, json=data, headers=headers)
            response.raise_for_status()
            connect_data = response.json()

            if 'AccessToken' not in connect_data:
                raise ValueError("No access token in response")

            # Get user's servers
            servers_url = f"https://connect.emby.media/service/servers?userId={connect_data['User']['Id']}"
            servers_headers = {
                'X-Application': 'MovieRoulette/1.0',
                'X-Connect-UserToken': connect_data['AccessToken']
            }

            servers_response = requests.get(servers_url, headers=servers_headers)
            servers_response.raise_for_status()
            servers = servers_response.json()

            if not servers:
                raise ValueError("No Emby servers found for this account")

            # Return the server list and connect data for frontend selection
            return {
                "status": "servers_available",
                "connect_user_id": connect_data['User']['Id'],
                "connect_token": connect_data['AccessToken'],
                "servers": [{
                    "id": server.get('SystemId'),
                    "name": server.get('Name'),
                    "url": server.get('Url'),
                    "local_url": server.get('LocalAddress'),
                    "access_key": server.get('AccessKey')
                } for server in servers]
            }

        except Exception as e:
            logger.error(f"Error in Emby Connect authentication: {e}")
            raise

    def authenticate(self, username, password):
        """Direct authentication with Emby server"""
        try:
            # Get server info first (required for auth)
            server_info_url = f"{self.server_url}/System/Info/Public"
            response = requests.get(server_info_url)
            response.raise_for_status()

            auth_url = f"{self.server_url}/Users/AuthenticateByName"
            auth_data = {
                "Username": username,
                "Pw": password,
                "Password": password,
                "PasswordMd5": "",  # Leave empty for plain password auth
                "AuthenticationScheme": "Username"
            }

            response = requests.post(auth_url, json=auth_data, headers={
                'X-Emby-Authorization': ('MediaBrowser Client="Movie Roulette",'
                                       'Device="Movie Roulette",'
                                       'DeviceId="MovieRoulette",'
                                       'Version="1.0.0"')
            })

            response.raise_for_status()
            data = response.json()

            self.api_key = data.get('AccessToken')
            self.user_id = data.get('User', {}).get('Id')
            self._update_headers()

            return {
                "status": "success",
                "api_key": self.api_key,
                "user_id": self.user_id
            }

        except Exception as e:
            logger.error(f"Error in direct authentication: {e}")
            raise

    def get_users(self):
        """Get list of users from Emby server"""
        try:
            users_url = f"{self.server_url}/Users"
            response = requests.get(users_url, headers=self.headers)
            response.raise_for_status()
            users = response.json()
            return [user.get('Name') for user in users]
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return []

    def _start_cache_updater(self):
        """Start the cache updater thread"""
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()
        logger.info("Emby cache updater thread started")

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
                        logger.info("Starting Emby cache update")
                        self.cache_all_emby_movies()
                        self.last_cache_update = current_time
                        logger.info("Emby cache update completed")
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in Emby cache update loop: {e}")
                time.sleep(5)  # Short sleep on error

    def cache_all_emby_movies(self):
        """Cache all movies for Emby badge checking"""
        if not all([self.server_url, self.api_key, self.user_id]):
            logger.info("Emby not fully configured, skipping cache update")
            return

        if self.is_updating:
            logger.info("Emby cache update already in progress, skipping")
            return

        try:
            self.is_updating = True
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProviderIds'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            all_movies = []
            for movie in movies:
                all_movies.append({
                    "emby_id": movie['Id'],
                    "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb')
                })

            # Save to disk atomically
            temp_path = f"{self.cache_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(all_movies, f)
            os.replace(temp_path, self.cache_path)

            logger.info(f"Cached {len(all_movies)} total Emby movies")
            return all_movies
        except Exception as e:
            logger.error(f"Error caching all Emby movies: {e}")
            return []
        finally:
            self.is_updating = False

    def get_unwatched_count(self):
        """Get count of unwatched movies"""
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'IsPlayed': 'false'  # Get only unwatched movies
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('TotalRecordCount', 0)
        except Exception as e:
            logger.error(f"Error getting unwatched count: {e}")
            return 0

    def get_random_movie(self):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating,MediaSources,MediaStreams,ProductionYear'
            }

            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()

            if movies.get('Items'):
                movie_data = self.get_movie_data(movies['Items'][0])
                logger.info(f"Selected random Emby movie for screensaver: {movie_data.get('title')}")  # Add logging
                return movie_data
            logger.warning("No movies found for screensaver")
            return None
        except Exception as e:
            logger.error(f"Error fetching random movie: {e}")
            return None

    def get_movie_data(self, movie):
        run_time_ticks = movie.get('RunTimeTicks', 0)
        total_minutes = run_time_ticks // 600000000  # Convert ticks to minutes
        hours = total_minutes // 60
        minutes = total_minutes % 60

        # Extract video and audio format information
        video_format = "Unknown"
        audio_format = "Unknown"

        if 'MediaSources' in movie and movie['MediaSources']:
            media_source = movie['MediaSources'][0]

            # Video format extraction
            video_streams = [s for s in media_source.get('MediaStreams', [])
                           if s.get('Type') == 'Video']
            if video_streams:
                video_stream = video_streams[0]
                height = video_stream.get('Height', 0)

                # Resolution detection
                if height <= 480:
                    resolution = "SD"
                elif height <= 720:
                    resolution = "HD"
                elif height <= 1080:
                    resolution = "FHD"
                elif height <= 2160:
                    resolution = "4K"
                else:
                    resolution = "Unknown"

                # HDR detection
                hdr_types = []
                if 'HDR' in str(video_stream):
                    if 'DolbyVision' in str(video_stream):
                        hdr_types.append('DV')
                    if 'HDR10Plus' in str(video_stream):
                        hdr_types.append('HDR10+')
                    elif 'HDR10' in str(video_stream):
                        hdr_types.append('HDR10')
                    elif not hdr_types:
                        hdr_types.append('HDR')

                video_format_parts = [resolution]
                if hdr_types:
                    video_format_parts.append('/'.join(hdr_types))
                video_format = ' '.join(video_format_parts)

            # Audio format extraction
            audio_streams = [s for s in media_source.get('MediaStreams', [])
                           if s.get('Type') == 'Audio']
            if audio_streams:
                audio_stream = audio_streams[0]
                codec = audio_stream.get('Codec', '').upper()

                # Map Emby codec names to display names
                codec_map = {
                    'AC3': 'Dolby Digital',
                    'EAC3': 'Dolby Digital Plus',
                    'TRUEHD': 'Dolby TrueHD',
                    'DTS': 'DTS',
                    'DTSHD': 'DTS-HD MA',
                    'AAC': 'AAC',
                    'FLAC': 'FLAC'
                }

                audio_format = codec_map.get(codec, codec)

                # Detect Atmos
                if any(s in str(audio_stream) for s in ['Atmos', 'ATMOS']):
                    audio_format = 'Dolby Atmos'

                # Add channel layout if available
                channels = audio_stream.get('Channels', 0)
                if channels > 0:
                    layout_map = {
                        1: 'Mono',
                        2: 'Stereo',
                        6: '5.1',
                        8: '7.1'
                    }
                    layout = layout_map.get(channels, f"{channels}ch")
                    audio_format = f"{audio_format} {layout}"

        # Process people (cast & crew)
        all_people = movie.get('People', [])

        # Process and enrich person data with proper departments
        directors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "director",
                "job": "Director",
                "department": "Directing"
            }
            for p in all_people if p.get('Type') == 'Director'
        ]

        writers = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "writer",
                "job": p.get('Role', 'Writer'),
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
            "poster": f"{self.server_url}/Items/{movie['Id']}/Images/Primary?api_key={self.api_key}",
            "background": f"{self.server_url}/Items/{movie['Id']}/Images/Backdrop?api_key={self.api_key}" if movie.get('BackdropImageTags') else None,
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

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'IsPlayed': 'false'
            }

            # Log incoming parameters
            logger.info(f"Filter movies called with - genres: {genres}, years: {years}, pg_ratings: {pg_ratings}")

            # Handle watch status
            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            # Handle empty lists as None
            genres = genres if genres and genres[0] else None
            years = years if years and years[0] else None
            pg_ratings = pg_ratings if pg_ratings and pg_ratings[0] else None

            if genres:
                params['Genres'] = '|'.join(genres)
                logger.info(f"Using genres in request: {params['GenreIds']}")

            if years:
                params['Years'] = years
                logger.info(f"Using years in request: {params['Years']}")

            if pg_ratings:
                params['OfficialRatings'] = '|'.join(pg_ratings)
                logger.info(f"Using ratings in request: {params['OfficialRatings']}")

            # Log final request
            response = requests.get(movies_url, headers=self.headers, params=params)
            logger.info(f"Response status code: {response.status_code}")

            response.raise_for_status()
            movies = response.json().get('Items', [])
            logger.info(f"Got {len(movies)} movies matching filters")

            if not movies:
                logger.warning("No unwatched movies found matching the criteria")
                return None

            return self.get_movie_data(movies[0])
        except Exception as e:
            logger.error(f"Error filtering movies: {str(e)}")
            return None

    def get_playback_info(self, item_id):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
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

                    is_stopped = session.get('PlayState', {}).get('PlayMethod') is None

                    return {
                        'is_playing': not is_paused and not is_stopped,
                        'IsPaused': is_paused,
                        'IsStopped': is_stopped,
                        'position': position_seconds,
                        'start_time': self.playback_start_times[item_id].isoformat(),
                        'duration': total_duration
                    }

            return {
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'duration': 0
            }
        except Exception as e:
            logger.error(f"Error fetching playback info: {e}")
            return None

    def get_clients(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()

            logger.debug(f"Raw sessions data: {json.dumps(sessions, indent=2)}")

            castable_clients = []
            for session in sessions:
                # Emby specific check for remote control capability
                if session.get('SupportsRemoteControl', False) and session.get('DeviceName') != 'Emby Server':
                    client = {
                        "title": session.get('DeviceName', 'Unknown Device'),
                        "id": session.get('Id'),
                        "client": session.get('Client', 'Unknown'),
                        "username": session.get('UserName'),
                        "device_id": session.get('DeviceId'),
                        "supports_media_control": session.get('SupportsMediaControl', False),
                    }
                    castable_clients.append(client)

            if not castable_clients:
                logger.warning("No castable clients found.")
            else:
                logger.info(f"Found {len(castable_clients)} castable clients")

            return castable_clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def play_movie(self, movie_id, session_id):
        try:
            playback_url = f"{self.server_url}/Sessions/{session_id}/Playing"
            params = {
                'ItemIds': movie_id,
                'PlayCommand': 'PlayNow'
            }

            # Get session info to find username
            username = None
            try:
                session_info_url = f"{self.server_url}/Sessions/{session_id}"
                session_response = requests.get(session_info_url, headers=self.headers)
                session_response.raise_for_status()
                session_data = session_response.json()
                username = session_data.get('UserName')
                logger.info(f"Playing movie for Emby user: {username}")
            except:
                logger.info("Could not determine Emby username for session")

            response = requests.post(playback_url, headers=self.headers, params=params)
            response.raise_for_status()
            logger.debug(f"Playing movie {movie_id} on session {session_id}")
            self.playback_start_times[movie_id] = datetime.now()
            movie_data = self.get_movie_by_id(movie_id)
        
            if movie_data:
                start_time = self.playback_start_times[movie_id]
                end_time = start_time + timedelta(hours=movie_data['duration_hours'],
                                                minutes=movie_data['duration_minutes'])
                from flask import session
                session['current_movie'] = movie_data
                session['movie_start_time'] = start_time.isoformat()
                session['movie_end_time'] = end_time.isoformat()
                session['current_service'] = 'emby'
            
            return {
                "status": "playing",
                "movie_id": movie_id,
                "session_id": session_id,
                "start_time": self.playback_start_times[movie_id].isoformat(),
                "movie_data": movie_data,
                "username": username 
            }
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_genres(self):
        try:
            items_url = f"{self.server_url}/Genres"
            params = {
                'Recursive': 'true',
                'IncludeItemTypes': 'Movie',
                'UserId': self.user_id
            }

            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            genres = [item.get('Name') for item in data.get('Items', []) if item.get('Name')]
            logger.debug(f"Extracted genre list: {genres}")
            return sorted(genres)
        except Exception as e:
            logger.error(f"Error fetching genres: {e}")
            return []

    def get_years(self):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProductionYear'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()
            years = set(movie.get('ProductionYear') for movie in movies.get('Items', [])
                       if movie.get('ProductionYear'))
            year_list = sorted(list(years), reverse=True)
            logger.debug(f"Fetched years: {year_list}")
            return year_list
        except Exception as e:
            logger.error(f"Error fetching years: {e}")
            return []

    def get_pg_ratings(self):
        try:
            items_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'OfficialRating',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=self.headers, params=params)
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

    def get_movie_by_id(self, movie_id):
        try:
            item_url = f"{self.server_url}/Users/{self.user_id}/Items/{movie_id}"
            params = {
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating'
            }
            response = requests.get(item_url, headers=self.headers, params=params)
            response.raise_for_status()
            movie = response.json()
            return self.get_movie_data(movie)
        except Exception as e:
            logger.error(f"Error fetching movie by ID: {e}")
            return None

    def check_token_validity(self):
        """Check if the current API token is still valid"""
        try:
            test_url = f"{self.server_url}/System/Info"
            response = requests.get(test_url, headers=self.headers)
            return response.status_code == 200
        except:
            return False

    def get_server_info(self):
        """Get Emby server information"""
        try:
            info_url = f"{self.server_url}/System/Info"
            response = requests.get(info_url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting server info: {e}")
            return None

    def get_current_username(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            for session in sessions:
                if session.get('UserId') == self.user_id:
                    return session.get('UserName')
            return None
        except Exception as e:
            logger.error(f"Error getting current username: {e}")
            return None

    def get_active_sessions(self):
        """Get all active sessions from Emby"""
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            return sessions
        except Exception as e:
            logger.error(f"Error fetching Emby sessions: {e}")
            return []

    def search_movies(self, query):
        """Search for movies matching the query in titles only"""
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SearchTerm': query,
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'SearchFields': 'Name',
                'EnableTotalRecordCount': True,
                'Limit': 50
            }

            logger.info(f"Searching Emby movies with query: {query}")
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            # Double check title match and process results
            results = []
            for movie in movies:
                if query.lower() in movie.get('Name', '').lower():
                    movie_data = self.get_movie_data(movie)
                    results.append(movie_data)

            logger.info(f"Found {len(results)} Emby movies matching title: {query}")
            return results

        except Exception as e:
            logger.error(f"Error searching Emby movies: {str(e)}")
            return []
