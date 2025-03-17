import time
import threading
import json
import os
import logging
import random
from flask_socketio import SocketIO
from flask import current_app
from utils.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DefaultPosterManager:
    def __init__(self, socketio):
        """Constructor to initialize the DefaultPosterManager with socketio"""
        self.init(socketio)  # Call existing init method

    def init(self, socketio):
        """Initialize the DefaultPosterManager"""
        self.socketio = socketio
        self.default_poster_timer = None
        self.last_state = None
        self.state_change_time = None
        self.lock = threading.Lock()
        self.current_movie_file = '/app/data/current_movie.json'
        self.default_poster = '/static/images/default_poster.png'
        self.is_default_poster_active = False
        self.poster_mode = 'default'  # 'default' or 'screensaver'
        self.screensaver_interval = 300  # 5 minutes default
        self.movie_service = None
        self.current_state = None
        self.screensaver_event = threading.Event()

        self.current_screensaver_poster = None

        logger.info("DefaultPosterManager initialized with SocketIO")

    def configure(self, settings):
        """Configure poster settings from app settings"""
        with self.lock:
            old_mode = self.poster_mode
            old_interval = self.screensaver_interval

            # Get settings from features section
            features = settings.get('features', {})
            configured_mode = features.get('poster_mode', 'default')
            custom_text = features.get('default_poster_text', '')

            # Handle interval - could be string or int
            interval_value = features.get('screensaver_interval', 300)
            try:
                new_interval = int(str(interval_value))
                logger.info(f"Converted interval value '{interval_value}' to {new_interval}")
            except (ValueError, TypeError):
                logger.error(f"Invalid interval value: {interval_value}, using default")
                new_interval = 300

            logger.info(f"Configuring poster manager:")
            logger.info(f"- Old mode: {old_mode} -> New mode: {configured_mode}")
            logger.info(f"- Old interval: {old_interval} -> New interval: {new_interval}")
            logger.info(f"- Movie service available: {bool(self.movie_service)}")

            # Check if there's an active movie
            has_active_movie = os.path.exists(self.current_movie_file)

            # Reset state before changing modes
            self.stop_screensaver()

            if configured_mode == 'default':
                # Switching TO default mode
                self.poster_mode = 'default'
                # Force emit default poster with custom text
                self.socketio.emit('set_default_poster', {
                    'poster': self.default_poster,
                    'custom_text': custom_text
                }, namespace='/poster')

            elif configured_mode == 'screensaver' and not has_active_movie:
                # Switching TO screensaver mode
                self.screensaver_interval = new_interval
                self.poster_mode = 'screensaver'

                if self.movie_service:
                    logger.info("Starting screensaver immediately with first movie")
                    try:
                        # Get first random movie
                        random_movie = self.movie_service.get_random_movie()
                        if random_movie:
                            # Emit initial movie
                            self.socketio.emit('update_screensaver', {
                                'poster': random_movie.get('poster')
                            }, namespace='/poster')
                        self.start_screensaver()
                    except Exception as e:
                        logger.error(f"Error starting screensaver: {e}")
                        # If screensaver fails, revert to default poster
                        self.poster_mode = 'default'
                        self.socketio.emit('set_default_poster', {
                            'poster': self.default_poster,
                            'custom_text': custom_text
                        }, namespace='/poster')
                else:
                    logger.error("No movie service available for screensaver")
                    # Revert to default poster mode if no movie service
                    self.poster_mode = 'default'
                    self.socketio.emit('set_default_poster', {
                        'poster': self.default_poster,
                        'custom_text': custom_text
                    }, namespace='/poster')

    def set_movie_service(self, service):
        """Set the movie service for getting random movies"""
        with self.lock:  # Add lock for thread safety
            if service == self.movie_service:
                logger.info("Movie service already set, skipping initialization")
                return

            logger.info(f"Setting movie service to {service.__class__.__name__}")
            self.movie_service = service

            # If we're in screensaver mode, we need to reinitialize
            if self.poster_mode == 'screensaver':
                logger.info("Reinitializing screensaver with new service")
                # Store current state
                old_interval = self.screensaver_interval
                was_screensaver = True
            else:
                was_screensaver = False

            # Stop current screensaver
            self.stop_screensaver()

            # Reset and restart only if we were in screensaver mode
            if was_screensaver and service:
                self.screensaver_interval = old_interval
                self.poster_mode = 'screensaver'
                # Attempt to get a random movie immediately
                random_movie = self.movie_service.get_random_movie()
                if random_movie:
                    logger.info(f"Found initial movie for screensaver: {random_movie.get('title', 'Unknown')}")
                    self.socketio.emit('update_screensaver', {
                        'poster': random_movie.get('poster')
                    }, namespace='/poster')
                    self.start_screensaver()
                else:
                    logger.error("No movies available for screensaver, reverting to default poster")
                    self.poster_mode = 'default'
                    self.socketio.emit('set_default_poster', {
                        'poster': self.default_poster
                    }, namespace='/poster')

    def start_screensaver(self):
        """Start the screensaver loop"""
        if not self.movie_service:
            logger.error("Cannot start screensaver without movie service")
            self.poster_mode = 'default'
            self.socketio.emit('set_default_poster', {
                'poster': self.default_poster
            }, namespace='/poster')
            return

        current_time = time.strftime('%H:%M:%S')
        logger.info(f"[{current_time}] Starting screensaver...")

        # First verify we can get movies
        test_movie = self.movie_service.get_random_movie()
        if not test_movie:
            logger.error("Movie service not providing movies, reverting to default poster")
            self.poster_mode = 'default'
            self.socketio.emit('set_default_poster', {
                'poster': self.default_poster
            }, namespace='/poster')
            return

        # Clear any existing event and create new one
        if hasattr(self, 'screensaver_event'):
            self.screensaver_event.set()  # Stop any existing loop
            time.sleep(0.1)  # Give time for the old loop to clean up

        self.screensaver_event = threading.Event()
        current_instance = self.screensaver_event  # Track this instance

        def screensaver_loop():
            while not self.screensaver_event.is_set():
                try:
                    if not self.movie_service or self.poster_mode != 'screensaver':
                        current_time = time.strftime('%H:%M:%S')
                        logger.error(f"[{current_time}] No movie service available or not in screensaver mode")
                        return

                    current_time = time.strftime('%H:%M:%S')
                    logger.info(f"[{current_time}] Getting random movie for screensaver")
                    random_movie = self.movie_service.get_random_movie()
                    if random_movie:
                        current_time = time.strftime('%H:%M:%S')
                        logger.info(f"[{current_time}] Emitting movie: {random_movie.get('title')}")

                        # Only emit if we're still the current instance
                        if self.screensaver_event == current_instance:
                            self.socketio.emit('update_screensaver', {
                                'poster': random_movie.get('poster')
                            }, namespace='/poster')
                            current_time = time.strftime('%H:%M:%S')
                            logger.info(f"[{current_time}] Successfully emitted screensaver update")
                            logger.info(f"[{current_time}] Next update scheduled in {self.screensaver_interval} seconds")
                    else:
                        logger.error("Failed to get random movie, reverting to default poster")
                        self.poster_mode = 'default'
                        self.socketio.emit('set_default_poster', {
                            'poster': self.default_poster
                        }, namespace='/poster')
                        return

                    # Wait but check event every second
                    for _ in range(int(self.screensaver_interval)):
                        if self.screensaver_event.is_set() or self.screensaver_event != current_instance:
                            return
                        self.socketio.sleep(1)

                except Exception as e:
                    current_time = time.strftime('%H:%M:%S')
                    logger.error(f"[{current_time}] Error in screensaver loop: {e}", exc_info=True)

        # Start the screensaver loop
        self.socketio.start_background_task(screensaver_loop)

    def stop_screensaver(self):
        """Stop the screensaver"""
        logger.info("Stopping screensaver")
        if hasattr(self, 'screensaver_event'):
            self.screensaver_event.set()  # Signal loop to stop
        # Don't change poster_mode here - it should be set by the caller
        if not os.path.exists(self.current_movie_file):
            self.is_default_poster_active = True
            logger.info("Setting default poster after stopping screensaver")
            self.socketio.emit('set_default_poster',
                            {'poster': self.default_poster},
                            namespace='/poster')
        self.current_screensaver_poster = None

    def start_default_poster_timer(self, state):
        """Start timer for transitioning to default poster or screensaver"""
        with self.lock:
            # Skip if timer already exists
            if self.default_poster_timer:
                return
            self.last_state = state
            self.state_change_time = time.time()
            self.default_poster_timer = threading.Timer(300, self.set_default_poster)  # 5 minutes
            self.default_poster_timer.start()
            logger.info("Started 5-minute timer for default/screensaver transition")

    def cancel_default_poster_timer(self):
        with self.lock:
            if self.default_poster_timer:
                self.default_poster_timer.cancel()
                self.default_poster_timer = None
            self.last_state = None
            self.state_change_time = None
            self.is_default_poster_active = False
            self.stop_screensaver()

    def set_default_poster(self):
        """Set default poster or start screensaver after timer expires"""
        with self.lock:
            logger.info(f"Setting default poster - Mode: {self.poster_mode}, Movie Service: {bool(self.movie_service)}")
            if self.last_state == 'STOPPED' and time.time() - self.state_change_time >= 300:  # 5 minutes
                # Archive current movie state
                if os.path.exists(self.current_movie_file):
                    with open(self.current_movie_file, 'r') as f:
                        movie_data = json.load(f)
                    movie_data['session_type'] = 'STOP'
                    with open(self.current_movie_file, 'w') as f:
                        json.dump(movie_data, f)
                # Clear current movie
                self.clear_current_movie()
                self.is_default_poster_active = True
                # Get current settings mode
                settings_data = settings.get_all()
                features = settings_data.get('features', {})
                configured_mode = features.get('poster_mode', 'default')
                custom_text = features.get('default_poster_text', '')
                # Start screensaver or show default poster based on settings
                if configured_mode == 'screensaver' and self.movie_service:
                    logger.info("Starting screensaver mode after 5-minute timer")
                    self.poster_mode = 'screensaver'
                    self.start_screensaver()  # This will handle the configured interval (e.g., 1 minute)
                else:
                    logger.info("Setting default poster after 5-minute timer")
                    self.poster_mode = 'default'
                    self.socketio.emit('set_default_poster',
                                       {'poster': self.default_poster,
                                        'custom_text': custom_text},
                                       namespace='/poster')

    def clear_current_movie(self):
        if os.path.exists(self.current_movie_file):
            os.remove(self.current_movie_file)

    def handle_playback_state(self, state):
        """Handle playback state changes"""
        # Don't process if state hasn't changed
        if state == self.current_state:
            return
        logger.info(f"Handling playback state change: {state}")
        self.current_state = state
        if state == 'PLAYING':
            # For PLAYING, stop screensaver and show movie
            logger.info("Movie PLAYING - showing movie poster")
            if self.default_poster_timer:
                self.cancel_default_poster_timer()
            self.poster_mode = 'default'  # Force default mode for movie display
            self.is_default_poster_active = False  # Make sure we're not in default poster mode
            if self.current_screensaver_poster:  # Clear any screensaver state
                self.current_screensaver_poster = None
                logger.info("Cleared screensaver poster state")
            if os.path.exists(self.current_movie_file):
                with open(self.current_movie_file, 'r') as f:
                    current_movie = json.load(f)
                    logger.info(f"Maintaining current movie: {current_movie.get('movie', {}).get('title')}")
        elif state == 'STOPPED':
            # Only start timer if we don't already have one running
            if not self.default_poster_timer:
                logger.info("Movie STOPPED - starting 5-minute timer before default/screensaver")
                self.start_default_poster_timer(state)
        elif state in ['ENDING', 'PAUSED']:
            # For ENDING and PAUSED, keep current movie poster
            logger.info(f"Movie {state} - maintaining current movie poster")
            if self.default_poster_timer:
                self.cancel_default_poster_timer()
            self.poster_mode = 'default'  # Force default mode
            self.is_default_poster_active = False

    def get_current_poster(self):
        with self.lock:
            # First check if a movie JSON file exists (this takes priority)
            if os.path.exists(self.current_movie_file):
                try:
                    with open(self.current_movie_file, 'r') as f:
                        current_movie = json.load(f)
                        poster_url = current_movie['movie']['poster']

                        # If we have a movie file, default poster should not be active
                        self.is_default_poster_active = False

                        # Proxy the URL if needed
                        jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
                        emby_service = current_app.config.get('EMBY_SERVICE')

                        if '/library/metadata' in poster_url:  # Plex
                            parts = poster_url.split('/library/metadata/')[1].split('?')[0]
                            return f"/proxy/poster/plex/{parts}"
                        elif '/Items/' in poster_url:  # Both Jellyfin and Emby
                            item_id = poster_url.split('/Items/')[1].split('/Images')[0]
                            if jellyfin_service and jellyfin_service.server_url in poster_url:
                                return f"/proxy/poster/jellyfin/{item_id}"
                            elif emby_service and emby_service.server_url in poster_url:
                                return f"/proxy/poster/emby/{item_id}"
                        return poster_url
                except Exception as e:
                    logger.error(f"Error reading current movie file: {e}")
                    # Fall through to other checks on error

            # Then check screensaver mode
            if self.poster_mode == 'screensaver' and self.current_screensaver_poster:
                url = self.current_screensaver_poster
                # Process URL for screensaver as before...
                jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
                emby_service = current_app.config.get('EMBY_SERVICE')

                if '/library/metadata' in url:  # Plex
                    parts = url.split('/library/metadata/')[1].split('?')[0]
                    return f"/proxy/poster/plex/{parts}"
                elif '/Items/' in url:  # Both Jellyfin and Emby use /Items/ pattern
                    item_id = url.split('/Items/')[1].split('/Images')[0]  # Get ID before /Images
                    if jellyfin_service and jellyfin_service.server_url in url:
                        return f"/proxy/poster/jellyfin/{item_id}"
                    elif emby_service and emby_service.server_url in url:
                        return f"/proxy/poster/emby/{item_id}"
                return url

            # Finally, default poster if nothing else matched
            if self.is_default_poster_active:
                return self.default_poster

            return self.default_poster

    def reset_state(self):
        self.cancel_default_poster_timer()
        self.stop_screensaver()
        self.is_default_poster_active = False
        self.last_state = None
        self.state_change_time = None

default_poster_manager = None

def init_default_poster_manager(socketio):
    global default_poster_manager
    if default_poster_manager is None:
        default_poster_manager = DefaultPosterManager(socketio)
        logger.info("DefaultPosterManager initialized")
    return default_poster_manager

