import time
import threading
import json
import os
import logging
from flask_socketio import SocketIO

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class DefaultPosterManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self.default_poster_timer = None
        self.last_state = None
        self.state_change_time = None
        self.lock = threading.Lock()
        self.current_movie_file = '/app/data/current_movie.json'
        self.default_poster = '/static/images/default_poster.png'
        self.is_default_poster_active = False
        logger.info("DefaultPosterManager initialized")

    def start_default_poster_timer(self, state):
        with self.lock:
            if self.last_state == state:
                logger.debug(f"State '{state}' unchanged, ignoring update")
                return

            if self.default_poster_timer:
                self.default_poster_timer.cancel()

            self.last_state = state
            self.state_change_time = time.time()
            self.default_poster_timer = threading.Timer(300, self.set_default_poster)
            self.default_poster_timer.start()

    def cancel_default_poster_timer(self):
        with self.lock:
            if self.default_poster_timer:
                self.default_poster_timer.cancel()
                self.default_poster_timer = None
            self.last_state = None
            self.state_change_time = None
            self.is_default_poster_active = False

    def set_default_poster(self):
        logger.debug("Setting default poster")
        with self.lock:
            if self.last_state in ['STOPPED', 'ENDED'] and time.time() - self.state_change_time >= 300:
                self.clear_current_movie()
                self.is_default_poster_active = True
                self.socketio.emit('set_default_poster', {'poster': self.default_poster}, namespace='/poster')
                logger.info("Default poster set and emitted")

    def clear_current_movie(self):
        logger.debug("Clearing current movie")
        if os.path.exists(self.current_movie_file):
            os.remove(self.current_movie_file)
            logger.info(f"Removed current movie file: {self.current_movie_file}")

    def handle_playback_state(self, state):
        if state in ['STOPPED', 'ENDED']:
            self.start_default_poster_timer(state)
        else:
            if self.last_state != state:
                self.cancel_default_poster_timer()

    def get_current_poster(self):
        logger.debug("Getting current poster")
        with self.lock:
            if self.is_default_poster_active:
                logger.info("Returning default poster")
                return self.default_poster
            if os.path.exists(self.current_movie_file):
                with open(self.current_movie_file, 'r') as f:
                    current_movie = json.load(f)
                logger.info(f"Returning movie poster: {current_movie['movie']['poster']}")
                return current_movie['movie']['poster']
            logger.info("No current movie, returning default poster")
            return self.default_poster

    def reset_state(self):
        logger.debug("Resetting DefaultPosterManager state")
        self.cancel_default_poster_timer()
        self.is_default_poster_active = False
        self.last_state = None
        self.state_change_time = None
        logger.info("DefaultPosterManager state reset")

default_poster_manager = None

def init_default_poster_manager(socketio):
    global default_poster_manager
    if default_poster_manager is None:
        default_poster_manager = DefaultPosterManager(socketio)
        logger.info("DefaultPosterManager initialized")
    return default_poster_manager
