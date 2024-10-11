import time
import json
import os
import logging
from threading import Thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, plex_service, cache_file_path, socketio, app, update_interval=600):
        self.plex_service = plex_service
        self.cache_file_path = cache_file_path
        self.socketio = socketio
        self.app = app
        self.update_interval = update_interval
        self.running = False

    def start(self):
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _update_loop(self):
        while self.running:
            self.update_cache(emit_progress=False)
            time.sleep(self.update_interval)

    def update_cache(self, emit_progress=False):
        with self.app.app_context():  
            try:
                def progress_callback(progress):
                    if emit_progress:
                        self.socketio.emit('loading_progress', {'progress': progress}, namespace='/')
                        logger.debug(f"Emitted loading_progress: {progress}")

                new_unwatched_movies = self.plex_service.get_all_unwatched_movies(progress_callback=progress_callback)

                # Read the current cache
                if os.path.exists(self.cache_file_path):
                    with open(self.cache_file_path, 'r') as f:
                        current_cache = json.load(f)
                else:
                    current_cache = []

                # Check for changes
                if len(new_unwatched_movies) != len(current_cache):
                    logger.info(f"Updating cache. Old count: {len(current_cache)}, New count: {len(new_unwatched_movies)}")
                    with open(self.cache_file_path, 'w') as f:
                        json.dump(new_unwatched_movies, f)
                else:
                    logger.info("No changes in unwatched movies. Cache remains the same.")

            except Exception as e:
                logger.error(f"Error updating cache: {str(e)}")

    def get_cached_movies(self):
        if os.path.exists(self.cache_file_path):
            with open(self.cache_file_path, 'r') as f:
                return json.load(f)
        return []
