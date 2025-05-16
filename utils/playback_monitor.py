import threading
import time
import logging
import os
from flask import current_app
from utils.jellyfin_service import JellyfinService
from utils.plex_service import PlexService
from utils.settings import settings
from utils.poster_view import set_current_movie

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaybackMonitor(threading.Thread):
    def __init__(self, app, interval=10):
        super().__init__()
        self.interval = interval
        self.jellyfin_service = None
        self.plex_service = None
        self.emby_service = None

        plex_settings = settings.get('plex', {})
        jellyfin_settings = settings.get('jellyfin', {})
        emby_settings = settings.get('emby', {})

        self.plex_user_mapping = {}

        self.plex_available = (
            bool(plex_settings.get('enabled')) or
            all([
                os.getenv('PLEX_URL'),
                os.getenv('PLEX_TOKEN'),
                os.getenv('PLEX_MOVIE_LIBRARIES')
            ])
        )

        self.jellyfin_available = (
            bool(jellyfin_settings.get('enabled')) or
            all([
                os.getenv('JELLYFIN_URL'),
                os.getenv('JELLYFIN_API_KEY'),
                os.getenv('JELLYFIN_USER_ID')
            ])
        )

        self.emby_available = (
            bool(emby_settings.get('enabled')) or
            all([
                os.getenv('EMBY_URL'),
                os.getenv('EMBY_API_KEY'),
                os.getenv('EMBY_USER_ID')
            ])
        )

        if self.jellyfin_available:
            self.jellyfin_service = app.config.get('JELLYFIN_SERVICE')
            if not self.jellyfin_service:
                logger.warning("Jellyfin marked as available but service not found in app config")
                self.jellyfin_available = False

        if self.plex_available:
            self.plex_service = app.config.get('PLEX_SERVICE')
            if not self.plex_service:
                logger.warning("Plex marked as available but service not found in app config")
                self.plex_available = False

        if self.emby_available:
            self.emby_service = app.config.get('EMBY_SERVICE')
            if not self.emby_service:
                logger.warning("Emby marked as available but service not found in app config")
                self.emby_available = False

        self.current_movie_id = None
        self.running = True
        self.app = app
        self.settings = settings

        features_settings = settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        features_settings = settings.get('features', {})
        poster_display = features_settings.get('poster_display', {}) 
        self.display_mode = poster_display.get('mode', 'first_active')

        preferred_user_config = poster_display.get('preferred_user', {})
        self.preferred_users = {
            'plex': '',
            'jellyfin': '',
            'emby': ''
        }
        if preferred_user_config:
            preferred_username = preferred_user_config.get('username', '')
            preferred_service = preferred_user_config.get('service', '')
            if preferred_username and preferred_service:
                self.preferred_users[preferred_service] = preferred_username

        logger.info(f"Initialized with display mode: {self.display_mode}")
        logger.info(f"Preferred users configuration: {self.preferred_users}")

        if os.getenv('PLEX_POSTER_USERS'):
            self.plex_poster_users = [u.strip() for u in os.getenv('PLEX_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.plex_poster_users = poster_users.get('plex', []) if isinstance(poster_users.get('plex'), list) else []

        if os.getenv('JELLYFIN_POSTER_USERS'):
            self.jellyfin_poster_users = [u.strip() for u in os.getenv('JELLYFIN_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.jellyfin_poster_users = poster_users.get('jellyfin', []) if isinstance(poster_users.get('jellyfin'), list) else []

        if os.getenv('EMBY_POSTER_USERS'):
            self.emby_poster_users = [u.strip() for u in os.getenv('EMBY_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.emby_poster_users = poster_users.get('emby', []) if isinstance(poster_users.get('emby'), list) else []

        self.active_streams = {}
        self.current_stream = None
        self.current_state = None
        self.is_showing_default = True

        logger.info(f"Initialized PlaybackMonitor with settings:")
        logger.info(f"Plex available: {self.plex_available}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Emby available: {self.emby_available}")
        logger.info(f"Plex poster users: {self.plex_poster_users}")
        logger.info(f"Jellyfin poster users: {self.jellyfin_poster_users}")
        logger.info(f"Emby poster users: {self.emby_poster_users}")

    def update_service_status(self):
        """Update service availability and instances from app config"""
        plex_settings = self.settings.get('plex', {})
        jellyfin_settings = self.settings.get('jellyfin', {})
        emby_settings = self.settings.get('emby', {})
        features_settings = self.settings.get('features', {})

        poster_display = features_settings.get('poster_display', {})
        self.display_mode = poster_display.get('mode', 'first_active')
    
        preferred_user_config = poster_display.get('preferred_user', {})
        self.preferred_users = {
            'plex': '',
            'jellyfin': '',
            'emby': ''
        }
        if preferred_user_config:
            preferred_username = preferred_user_config.get('username', '')
            preferred_service = preferred_user_config.get('service', '')
            if preferred_username and preferred_service:
                self.preferred_users[preferred_service] = preferred_username

        logger.info(f"Updated display mode to: {self.display_mode}")
        logger.info(f"Updated preferred users configuration: {self.preferred_users}")

        self.plex_available = (
            bool(plex_settings.get('enabled')) or
            all([
                os.getenv('PLEX_URL'),
                os.getenv('PLEX_TOKEN'),
                os.getenv('PLEX_MOVIE_LIBRARIES')
            ])
        )

        self.jellyfin_available = (
            bool(jellyfin_settings.get('enabled')) or
            all([
                os.getenv('JELLYFIN_URL'),
                os.getenv('JELLYFIN_API_KEY'),
                os.getenv('JELLYFIN_USER_ID')
            ])
        )

        self.emby_available = (
            bool(emby_settings.get('enabled')) or
            all([
                os.getenv('EMBY_URL'),
                os.getenv('EMBY_API_KEY'),
                os.getenv('EMBY_USER_ID')
            ])
        )

        if self.plex_available:
            self.plex_service = self.app.config.get('PLEX_SERVICE')
            if not self.plex_service:
                logger.warning("Plex marked as available but service not found in app config")
                self.plex_available = False

        if self.jellyfin_available:
            self.jellyfin_service = self.app.config.get('JELLYFIN_SERVICE')
            if not self.jellyfin_service:
                logger.warning("Jellyfin marked as available but service not found in app config")
                self.jellyfin_available = False

        if self.emby_available:
            self.emby_service = self.app.config.get('EMBY_SERVICE')
            if not self.emby_service:
                logger.warning("Emby marked as available but service not found in app config")
                self.emby_available = False

        self.update_authorized_users()

        logger.info(f"Updated service status:")
        logger.info(f"Plex available: {self.plex_available}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Emby available: {self.emby_available}")

    def can_switch_streams(self):
        """Determine if we're allowed to switch to a different stream"""
        return (self.is_showing_default or
                not self.current_stream or
                self.current_state == 'STOPPED')

    def update_stream_status(self, stream_id, status):
        """Update stream status and handle state changes"""
        if stream_id in self.active_streams:
            old_status = self.active_streams[stream_id].get('status')
            self.active_streams[stream_id]['status'] = status

            if old_status != status:
                logger.info(f"Stream {stream_id} status changed: {old_status} -> {status}")

            if self.current_stream and stream_id == self.current_stream.get('id'):
                if self.current_state != status:
                    self.current_state = status
                    logger.info(f"Current display stream status changed to: {status}")

    def select_display_stream(self):
        """Select which stream to display based on configured mode and active streams"""
        playing_streams = {
            stream_id: stream
            for stream_id, stream in self.active_streams.items()
            if stream['status'] == 'PLAYING'
        }

        if not playing_streams:
            if not self.is_showing_default:
                logger.info("No active playing streams, switching to default poster")
                self.is_showing_default = True
                default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')
                if default_poster_manager:
                    default_poster_manager.handle_playback_state('STOPPED')
                self.current_stream = None
            return None

        sorted_streams = sorted(playing_streams.values(), key=lambda x: x.get('first_active', float('inf')))

        logger.info(f"Selecting display stream from {len(playing_streams)} active streams:")
        for i, stream in enumerate(sorted_streams, 1):
            logger.info(f"  {i}. {stream['service']} stream: {stream['username']} - {stream['title']}")
            logger.info(f"     Started: {time.strftime('%H:%M:%S', time.localtime(stream['first_active']))}")

        if not self.can_switch_streams() and self.current_stream:
            if self.current_stream.get('id') in playing_streams:
                logger.info(f"Maintaining current stream: {self.current_stream.get('title')} ({self.current_stream.get('username')})")
                return self.current_stream
            else:
                logger.info("Current stream is no longer active")

        selected_stream = None
        if self.display_mode == 'preferred_user':
            for stream in sorted_streams:
                service = stream['service']
                username = stream['username']
                preferred_username = self.preferred_users.get(service, '')
            
                if preferred_username and username == preferred_username:
                    selected_stream = stream
                    logger.info(f"Selected preferred user stream: {username} - {stream['title']} ({service})")
                    break

            if not selected_stream:
                logger.info("No preferred user stream found, falling back to first active")
                selected_stream = sorted_streams[0]
        else:
            selected_stream = sorted_streams[0]
            logger.info(f"Selected first active stream: {selected_stream['username']} - {selected_stream['title']}")

        if self.current_stream and selected_stream:
            if self.current_stream.get('id') != selected_stream['id']:
                logger.info(f"Switching display from {self.current_stream['title']} to {selected_stream['title']}")

        self.current_stream = selected_stream
        return selected_stream

    def update_authorized_users(self):
        """Update authorized users list from settings or ENV"""
        features_settings = self.settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        if os.getenv('PLEX_POSTER_USERS'):
            self.plex_poster_users = [u.strip() for u in os.getenv('PLEX_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.plex_poster_users = poster_users.get('plex', []) if isinstance(poster_users.get('plex'), list) else []

        if os.getenv('JELLYFIN_POSTER_USERS'):
            self.jellyfin_poster_users = [u.strip() for u in os.getenv('JELLYFIN_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.jellyfin_poster_users = poster_users.get('jellyfin', []) if isinstance(poster_users.get('jellyfin'), list) else []

        if os.getenv('EMBY_POSTER_USERS'):
            self.emby_poster_users = [u.strip() for u in os.getenv('EMBY_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.emby_poster_users = poster_users.get('emby', []) if isinstance(poster_users.get('emby'), list) else []

    def _check_authorization(self, username, service):
        """Internal method to check if user is authorized without logging"""
        if not username:
            return False

        if service == 'plex':
            canonical_username = self.plex_user_mapping.get(username.lower(), username)
            authorized_users = [user.lower() for user in self.plex_poster_users]
            return (canonical_username.lower() in authorized_users or
                   any(mapped_name.lower() in authorized_users
                       for mapped_name, mapped_user in self.plex_user_mapping.items()
                       if mapped_user.lower() == canonical_username.lower()))
        elif service == 'jellyfin':
            return username in self.jellyfin_poster_users
        elif service == 'emby':
            return username in self.emby_poster_users
        return False

    def is_poster_user(self, username, service):
        """Check if a user is authorized for poster updates"""
        if not username:
            logger.info(f"No username provided for {service} authorization check")
            return False

        is_authorized = self._check_authorization(username, service)
        if not is_authorized:
            logger.info(f"Unauthorized {service} playback by user {username}")
            return False

        return True

    def run(self):
        """Main monitoring loop with improved stream tracking"""
        last_state = None
        last_movie_id = None
        last_log_time = {}
        log_interval = 60

        while self.running:
            try:
                with self.app.app_context():
                    default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')
                    current_streams = {}
                    
                    if self.jellyfin_available and self.jellyfin_service:
                        jellyfin_sessions = self.jellyfin_service.get_active_sessions()
                        for session in jellyfin_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie' and self.is_poster_user(username, 'jellyfin'):
                                stream_id = f"jellyfin_{now_playing.get('Id')}"
                                current_streams[stream_id] = {
                                    'id': now_playing.get('Id'),
                                    'service': 'jellyfin',
                                    'username': username,
                                    'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000,
                                    'status': 'PLAYING',
                                    'title': now_playing.get('Name'),
                                    'first_active': self.active_streams.get(stream_id, {}).get('first_active', time.time())
                                }

                    if self.emby_available and self.emby_service:
                        emby_sessions = self.emby_service.get_active_sessions()
                        for session in emby_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie' and self.is_poster_user(username, 'emby'):
                                stream_id = f"emby_{now_playing.get('Id')}"
                                current_streams[stream_id] = {
                                    'id': now_playing.get('Id'),
                                    'service': 'emby',
                                    'username': username,
                                    'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000,
                                    'status': 'PLAYING',
                                    'title': now_playing.get('Name'),
                                    'first_active': self.active_streams.get(stream_id, {}).get('first_active', time.time())
                                }

                    if self.plex_available and self.plex_service:
                        plex_sessions = self.plex_service.plex.sessions()
                        for session in plex_sessions:
                            username = session.usernames[0] if session.usernames else None
                            if session.type == 'movie' and self.is_poster_user(username, 'plex'):
                                stream_id = f"plex_{session.ratingKey}"
                                playback_info = self.plex_service.get_playback_info(session.ratingKey)
                                current_streams[stream_id] = {
                                    'id': session.ratingKey,
                                    'service': 'plex',
                                    'username': username,
                                    'position': playback_info.get('position', 0),
                                    'status': 'PLAYING',
                                    'title': session.title,
                                    'first_active': self.active_streams.get(stream_id, {}).get('first_active', time.time())
                                }

                    current_time = time.time()
                    for stream_id in list(self.active_streams.keys()):
                        if stream_id not in current_streams:
                            if self.active_streams[stream_id]['status'] != 'STOPPED':
                                self.active_streams[stream_id]['status'] = 'STOPPED'
                                self.active_streams[stream_id]['stop_time'] = current_time
                                logger.info(f"Stream stopped: {self.active_streams[stream_id]['username']} ({self.active_streams[stream_id]['service']}) - {self.active_streams[stream_id]['title']}")
                                
                                active_streams = [s for s in self.active_streams.values() if s['status'] == 'PLAYING']
                                if active_streams:
                                    logger.info(f"Remaining active streams ({len(active_streams)}):")
                                    sorted_streams = sorted(active_streams, key=lambda x: x['first_active'])
                                    for i, stream in enumerate(sorted_streams, 1):
                                        logger.info(f"  {i}. {stream['service']} stream: {stream['username']} - {stream['title']}")
                                        logger.info(f"     Started: {time.strftime('%H:%M:%S', time.localtime(stream['first_active']))}")
                                        if i == 1:
                                            logger.info(f"     [This stream should now be selected as it started first]")
                            
                            if current_time - self.active_streams[stream_id].get('stop_time', 0) > 300:
                                logger.info(f"Removing inactive stream: {self.active_streams[stream_id]['title']}")
                                del self.active_streams[stream_id]

                    for stream_id, stream_data in current_streams.items():
                        is_new_stream = stream_id not in self.active_streams
                        if is_new_stream:
                            stream_data['first_active'] = time.time()
                            logger.info(f"New stream started: {stream_data['username']} ({stream_data['service']}) - {stream_data['title']}")
                        self.active_streams[stream_id] = stream_data

                        if is_new_stream:
                            logger.info(f"Playback started: {stream_data['username']} ({stream_data['service']}) - {stream_data['title']}")
                            
                            active_streams = [s for s in self.active_streams.values() if s['status'] == 'PLAYING']
                            sorted_streams = sorted(active_streams, key=lambda x: x['first_active'])
                            
                            logger.info("Playbacks ongoing:")
                            for i, stream in enumerate(sorted_streams, 1):
                                prefix = "→" if i == 1 else " "
                                logger.info(f"{prefix} {stream['username']} ({stream['service']}) - {stream['title']}")

                            should_force = False
                            if self.display_mode == 'preferred_user':
                                if stream_data['username'] == self.preferred_users.get(stream_data['service']):
                                    logger.info(f"Preferred user {stream_data['username']} takes precedence - forcing update")
                                    should_force = True
                            elif sorted_streams[0]['id'] == stream_data['id']:
                                logger.info(f"First active stream - forcing update")
                                should_force = True
                            
                            if should_force and os.path.exists('/app/data/current_movie.json'):
                                os.remove('/app/data/current_movie.json')

                    active_streams = [s for s in self.active_streams.values() if s['status'] == 'PLAYING']
                    sorted_streams = sorted(active_streams, key=lambda x: x['first_active'])

                    selected_stream = None
                    if active_streams:
                        if self.display_mode == 'preferred_user':
                            for stream in sorted_streams:
                                if stream['username'] == self.preferred_users.get(stream['service']):
                                    selected_stream = stream
                                    logger.info(f"Preferred user {stream['username']} takes precedence")
                                    break
                        
                        if not selected_stream:
                            selected_stream = sorted_streams[0]

                    if selected_stream:
                        movie_id = selected_stream['id']
                        service = selected_stream['service']
                        username = selected_stream['username']

                        movie_data = None
                        if service == 'jellyfin':
                            movie_data = self.jellyfin_service.get_movie_by_id(movie_id)
                        elif service == 'emby':
                            movie_data = self.emby_service.get_movie_by_id(movie_id)
                        elif service == 'plex':
                            movie_data = self.plex_service.get_movie_by_id(movie_id)

                        if movie_data:
                            current_state = f"{service}_{movie_id}_{selected_stream['status']}"
                            current_time = time.time()

                            logger.info("Playbacks ongoing:")
                            for i, stream in enumerate(sorted_streams, 1):
                                prefix = "→" if stream['id'] == movie_id else " "
                                logger.info(f"{prefix} {stream['username']} ({stream['service']}) - {stream['title']}")
                                logger.info(f"     Started: {time.strftime('%H:%M:%S', time.localtime(stream['first_active']))}")

                            if movie_id != self.current_movie_id:
                                if self.current_movie_id:
                                    logger.info(f"Switching poster display from {self.current_movie_id} to {movie_id}")
                                else:
                                    logger.info(f"Setting initial poster display to {movie_id}")
                                
                                logger.info(f"Updating poster to: {movie_data.get('title')} ({service}) - User: {username}")
                                set_current_movie(movie_data, service=service,
                                            resume_position=selected_stream.get('position', 0),
                                            username=username)
                                self.current_movie_id = movie_id
                                self.is_showing_default = False
                                last_log_time['state'] = current_time
                                last_state = current_state
                    else:
                        if self.current_movie_id is not None:
                            logger.info("No active streams - switching to default poster")
                            self.current_movie_id = None
                            self.is_showing_default = True
                            if default_poster_manager:
                                default_poster_manager.handle_playback_state('STOPPED')

                    time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in PlaybackMonitor: {e}", exc_info=True)
                time.sleep(self.interval)

    def get_all_sessions(self):
        """Helper to get all sessions from all services"""
        sessions = {}
        if self.plex_available and self.plex_service:
            sessions['plex'] = self.plex_service.plex.sessions()
        if self.jellyfin_available and self.jellyfin_service:
            sessions['jellyfin'] = self.jellyfin_service.get_active_sessions()
        if self.emby_available and self.emby_service:
            sessions['emby'] = self.emby_service.get_active_sessions()
        return sessions

    def get_username(self, session, service):
        """Helper to extract username from session based on service"""
        if service == 'plex':
            return session.usernames[0] if session.usernames else None
        return session.get('UserName')

    def stop(self):
        self.running = False