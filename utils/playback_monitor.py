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

        # Get settings instead of checking ENV directly
        plex_settings = settings.get('plex', {})
        jellyfin_settings = settings.get('jellyfin', {})
        emby_settings = settings.get('emby', {})

        # Initialize user mapping dictionary
        self.plex_user_mapping = {}

        # Check for both settings and ENV availability
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

        # Get services from app config
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
            else:
                # Initialize user mapping on startup
                self.update_plex_user_mapping()

        if self.emby_available:
            self.emby_service = app.config.get('EMBY_SERVICE')
            if not self.emby_service:
                logger.warning("Emby marked as available but service not found in app config")
                self.emby_available = False

        self.current_movie_id = None
        self.running = True
        self.app = app
        self.settings = settings

        # Get poster users
        features_settings = settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        # Get poster display mode settings
        features_settings = settings.get('features', {})
        poster_display_mode = features_settings.get('poster_display_mode', {})
        self.display_mode = poster_display_mode.get('mode', 'first_active')
        self.preferred_users = poster_display_mode.get('preferred_user', {
            'plex': '',
            'jellyfin': '',
            'emby': ''
        })

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

        self.active_streams = {}  # Track all active authorized streams
        self.current_stream = None  # Currently displayed stream
        self.current_state = None  # Current playback state
        self.is_showing_default = True  # Track if showing default poster

        logger.info(f"Initialized PlaybackMonitor with settings:")
        logger.info(f"Plex available: {self.plex_available}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Emby available: {self.emby_available}")
        logger.info(f"Plex poster users: {self.plex_poster_users}")
        logger.info(f"Jellyfin poster users: {self.jellyfin_poster_users}")
        logger.info(f"Emby poster users: {self.emby_poster_users}")

    def update_service_status(self):
        """Update service availability and instances from app config"""
        # Get current settings
        plex_settings = self.settings.get('plex', {})
        jellyfin_settings = self.settings.get('jellyfin', {})
        emby_settings = self.settings.get('emby', {})

        # Update availability flags
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

        # Update service instances
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

        # Update authorized users
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

            # Log only status changes
            if old_status != status:
                logger.info(f"Stream {stream_id} status changed: {old_status} -> {status}")

            # If this is our current stream, update current state
            if self.current_stream and stream_id == self.current_stream.get('id'):
                if self.current_state != status:
                    self.current_state = status
                    logger.info(f"Current display stream status changed to: {status}")

    def select_display_stream(self):
        """Select which stream to display based on Last Active logic"""
        if not self.can_switch_streams():
            return self.current_stream

        if not self.active_streams:
            if not self.is_showing_default:
                logger.info("No active streams, switching to default poster")
                self.is_showing_default = True
                default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')
                if default_poster_manager:
                    default_poster_manager.handle_playback_state('STOPPED')
            return None

        # Get most recently active stream
        newest_stream = max(self.active_streams.values(),
                          key=lambda x: x['last_active'])
        return newest_stream

    def update_authorized_users(self):
        """Update authorized users list from settings or ENV"""
        features_settings = self.settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        # Update poster users with ENV priority
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

    def should_update_poster(self, username, service):
        """Check if this playback should take over the poster display"""
        if self.display_mode == 'first_active':
            # Keep existing behavior
            return not os.path.exists('/app/data/current_movie.json')
        elif self.display_mode == 'preferred_user':
            # Get preferred user for this service
            preferred_user = self.preferred_users.get(service, '')
            if not preferred_user:
                # If no preferred user set for service, fall back to first_active behavior
                return not os.path.exists('/app/data/current_movie.json')

            # If this is the preferred user, they always take over
            return username == preferred_user

        return False

    def _check_authorization(self, username, service):
        """Internal method to check if user is authorized without logging"""
        if not username:
            return False

        if service == 'plex':
            # Get canonical username if it exists in our mapping
            canonical_username = self.plex_user_mapping.get(username.lower(), username)
            authorized_users = [user.lower() for user in self.plex_poster_users]
            # Check both username and any mapped names
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

        # First check if they're in authorized poster users
        if service == 'plex':
            # Get canonical username if it exists in our mapping
            canonical_username = self.plex_user_mapping.get(username.lower(), username)
            authorized_users = [user.lower() for user in self.plex_poster_users]
            # Check both username and any mapped names
            is_authorized = (canonical_username.lower() in authorized_users or 
                           any(mapped_name.lower() in authorized_users 
                               for mapped_name, mapped_user in self.plex_user_mapping.items() 
                               if mapped_user.lower() == canonical_username.lower()))
        elif service == 'jellyfin':
            is_authorized = username in self.jellyfin_poster_users
        elif service == 'emby':
            is_authorized = username in self.emby_poster_users
        else:
            is_authorized = False

        if not is_authorized:
            logger.info(f"Unauthorized {service} playback by user {username}")
            return False

        # Get current display mode
        features_settings = self.settings.get('features', {})
        display_mode = features_settings.get('poster_display', {}).get('mode', 'first_active')

        # Get all active sessions once
        active_sessions = self.get_all_sessions()
        authorized_sessions = []

        # Count authorized sessions and collect their details
        for service_name, service_sessions in active_sessions.items():
            for session in service_sessions:
                # First check if this is a movie session
                if service_name == 'plex':
                    if not hasattr(session, 'type') or session.type != 'movie':
                        continue  # Skip non-movie sessions
                else:  # Jellyfin/Emby
                    now_playing = session.get('NowPlayingItem', {})
                    if now_playing.get('Type') != 'Movie':
                        continue  # Skip non-movie sessions

                session_username = self.get_username(session, service_name)
                if self._check_authorization(session_username, service_name):
                    authorized_sessions.append({
                        'username': session_username,
                        'service': service_name
                    })

        # If only one authorized session, allow it
        if len(authorized_sessions) <= 1:
            logger.info(f"Single authorized playback from {username}, allowing display")
            return True

        # Multiple authorized sessions - check mode
        if display_mode == 'preferred_user':
            preferred = features_settings.get('poster_display', {}).get('preferred_user')

            # Check if this is the preferred user (handling Plex username/full name)
            is_preferred = False
            if service == 'plex':
                preferred_username = preferred.get('username', '').lower()
                canonical_username = self.plex_user_mapping.get(username.lower(), username)
                is_preferred = (canonical_username.lower() == preferred_username or 
                              any(mapped_name.lower() == preferred_username 
                                  for mapped_name, mapped_user in self.plex_user_mapping.items() 
                                  if mapped_user.lower() == canonical_username.lower()))
            else:
                is_preferred = preferred.get('username') == username

            # Check if preferred user is among active sessions
            preferred_active = any(session['username'] == preferred.get('username') and
                                 session['service'] == preferred.get('service')
                                 for session in authorized_sessions)

            # If this is the preferred user, they take over
            if preferred and is_preferred and preferred.get('service') == service:
                logger.info(f"Multiple sessions active, preferred user {username} ({service}) takes precedence")
                if os.path.exists('/app/data/current_movie.json'):
                    os.remove('/app/data/current_movie.json')  # Force new poster
                return True

            # If preferred user is active, block others
            if preferred_active:
                logger.info(f"Multiple sessions active, user {username} not preferred")
                return False

            # If no preferred user is active, use first_active behavior
            should_update = not os.path.exists('/app/data/current_movie.json')
            if should_update:
                logger.info(f"Preferred user not active, first active user {username} takes display")
            return should_update

        else:  # first_active mode
            should_update = not os.path.exists('/app/data/current_movie.json')
            if should_update:
                logger.info(f"Multiple sessions, first active user {username} takes display")
            else:
                logger.info(f"Multiple sessions, display already active")
            return should_update

    def run(self):
        last_state = None  # Track last logged state
        last_movie_id = None  # Track last movie ID
        last_log_time = {}  # Track last log time for each type of message
        log_interval = 60  # Only log same message every 60 seconds

        while self.running:
            try:
                with self.app.app_context():
                    playback_info = None
                    service = None
                    username = None
                    default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')

                    # Check Jellyfin first
                    if self.jellyfin_available and self.jellyfin_service:
                        jellyfin_sessions = self.jellyfin_service.get_active_sessions()

                        for session in jellyfin_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie':
                                if self.is_poster_user(username, 'jellyfin'):
                                    playback_info = {
                                        'id': now_playing.get('Id'),
                                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000
                                    }
                                    service = 'jellyfin'
                                    break

                    # Check Emby if no Jellyfin playback
                    if not playback_info and self.emby_available and self.emby_service:
                        emby_sessions = self.emby_service.get_active_sessions()

                        for session in emby_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie':
                                if self.is_poster_user(username, 'emby'):
                                    playback_info = {
                                        'id': now_playing.get('Id'),
                                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000
                                    }
                                    service = 'emby'
                                    break

                    # Check Plex if no other playback found
                    if not playback_info and self.plex_available and self.plex_service:
                        sessions = self.plex_service.plex.sessions()

                        for session in sessions:
                            username = session.usernames[0] if session.usernames else None
                            if session.type == 'movie':
                                if self.is_poster_user(username, 'plex'):
                                    playback_info = self.plex_service.get_playback_info(session.ratingKey)
                                    service = 'plex'
                                    break

                    if playback_info:
                        movie_id = playback_info.get('id')
                        if movie_id:
                            movie_data = None
                            if service == 'jellyfin':
                                movie_data = self.jellyfin_service.get_movie_by_id(movie_id)
                            elif service == 'emby':
                                movie_data = self.emby_service.get_movie_by_id(movie_id)
                            elif service == 'plex':
                                movie_data = self.plex_service.get_movie_by_id(movie_id)

                            if movie_data:
                                current_state = f"{service}_{movie_id}_{playback_info.get('status')}"
                                current_time = time.time()

                                # Only update poster if:
                                # - We're showing default, OR
                                # - No current movie, OR
                                # - Current movie.json doesn't exist, OR
                                # - Current movie is stopped
                                can_update = (
                                    self.is_showing_default or
                                    self.current_movie_id is None or
                                    not os.path.exists('/app/data/current_movie.json') or
                                    (default_poster_manager and default_poster_manager.last_state == 'STOPPED')
                                )

                                # Update if we can update AND (different movie OR missing state file)
                                if can_update and (movie_id != self.current_movie_id or not os.path.exists('/app/data/current_movie.json')):
                                    logger.info(f"New movie or missing state file detected, updating poster: {movie_data.get('title')} ({service})")
                                    set_current_movie(movie_data, service=service,
                                                resume_position=playback_info.get('position', 0),
                                                username=username)
                                    self.current_movie_id = movie_id
                                    self.is_showing_default = False
                                    last_log_time['state'] = current_time
                                    last_state = current_state

                    elif self.current_movie_id is not None:
                        current_time = time.time()
                        if current_time - last_log_time.get('no_playback', 0) > log_interval:
                            logger.info("No active authorized playback detected")
                            last_log_time['no_playback'] = current_time

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
            username = session.usernames[0] if session.usernames else None
            # For Plex, try to get canonical username from mapping
            if username:
                return self.plex_user_mapping.get(username.lower(), username)
            return None
        return session.get('UserName')  # For Jellyfin/Emby

    def update_plex_user_mapping(self):
        """Update the mapping between Plex usernames and full names"""
        try:
            if self.plex_service and self.plex_available:
                # Always map the server owner
                account = self.plex_service.plex.myPlexAccount()
                self.plex_user_mapping[account.username.lower()] = account.username
                if account.title:  # Map the owner's full name
                    self.plex_user_mapping[account.title.lower()] = account.username

                # Map all shared users
                for user in account.users():
                    self.plex_user_mapping[user.username.lower()] = user.username
                    if user.title:  # Map each user's full name
                        self.plex_user_mapping[user.title.lower()] = user.username
                
                logger.info(f"Updated Plex user mapping: {self.plex_user_mapping}")
        except Exception as e:
            logger.error(f"Error updating Plex user mapping: {e}")

    def stop(self):
        self.running = False
