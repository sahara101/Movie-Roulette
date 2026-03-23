import os
import json
import logging
import time
from threading import Thread, RLock

logger = logging.getLogger(__name__)

ENRICHMENT_CACHE_FILE = '/app/data/enrichment_cache.json'
ENRICHMENT_TTL_DAYS = 30


class EnrichmentCache:
    def __init__(self):
        self._cache = {}
        self._lock = RLock()
        self._building = False
        self._pending = set()
        self._load_from_disk()

    def _should_cache_logo(self):
        from utils.settings import settings
        return settings.get('features', {}).get('enable_movie_logos', True)

    def _load_from_disk(self):
        if not os.path.exists(ENRICHMENT_CACHE_FILE):
            return
        try:
            if os.path.getsize(ENRICHMENT_CACHE_FILE) == 0:
                return
            with open(ENRICHMENT_CACHE_FILE, 'r') as f:
                self._cache = json.load(f)
            logger.info(f"Loaded {len(self._cache)} enriched entries from disk")
        except Exception as e:
            logger.error(f"Error loading enrichment cache: {e}")
            self._cache = {}

    def _save_to_disk(self):
        temp_path = ENRICHMENT_CACHE_FILE + '.tmp'
        try:
            with self._lock:
                data = dict(self._cache)
            with open(temp_path, 'w') as f:
                json.dump(data, f)
            os.replace(temp_path, ENRICHMENT_CACHE_FILE)
        except Exception as e:
            logger.error(f"Error saving enrichment cache: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def get(self, tmdb_id):
        with self._lock:
            return self._cache.get(str(tmdb_id))

    def set(self, tmdb_id, data):
        with self._lock:
            self._cache[str(tmdb_id)] = data

    def enrich_single(self, tmdb_id, title, year):
        """Fetch enrichment data for one movie. Returns dict."""
        from utils.tmdb_service import tmdb_service
        from utils.youtube_trailer import search_youtube_trailer

        credits = None
        try:
            credits = tmdb_service.get_movie_cast(tmdb_id)
        except Exception as e:
            logger.warning(f"Error getting credits for tmdb_id={tmdb_id}: {e}")

        tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
        trakt_url = None
        imdb_url = None
        try:
            tmdb_url, trakt_url, imdb_url = tmdb_service.get_movie_links(tmdb_id)
        except Exception as e:
            logger.warning(f"Error getting links for tmdb_id={tmdb_id}: {e}")

        trailer_url = None
        try:
            trailer_url = search_youtube_trailer(title, year)
        except Exception as e:
            logger.warning(f"Error getting trailer for '{title}': {e}")

        logo_url = None
        if self._should_cache_logo():
            try:
                logo_url = tmdb_service.get_movie_logo_url(tmdb_id)
            except Exception as e:
                logger.warning(f"Error getting logo for tmdb_id={tmdb_id}: {e}")

        return {
            'tmdb_id': str(tmdb_id),
            'tmdb_url': tmdb_url,
            'trakt_url': trakt_url,
            'imdb_url': imdb_url,
            'trailer_url': trailer_url,
            'logo_url': logo_url,
            'credits': credits,
            'enriched_at': time.time(),
        }

    def build_for_movies(self, movies, force=False):
        """Start background enrichment build for a list of movies."""
        if self._building and not force:
            logger.info("Enrichment build already in progress, skipping")
            return
        Thread(target=self._build_worker, args=(list(movies), force), daemon=True).start()

    def _build_worker(self, movies, force):
        self._building = True
        logger.info(f"Enrichment build starting for {len(movies)} movies")
        saved = 0
        errors = 0
        try:
            for i, movie in enumerate(movies):
                tmdb_id = movie.get('tmdb_id')
                if not tmdb_id:
                    continue

                if not force:
                    existing = self.get(tmdb_id)
                    if existing:
                        age_days = (time.time() - existing.get('enriched_at', 0)) / 86400
                        if age_days < ENRICHMENT_TTL_DAYS:
                            continue

                try:
                    entry = self.enrich_single(tmdb_id, movie.get('title', ''), movie.get('year', ''))
                    self.set(tmdb_id, entry)
                    saved += 1
                    if saved % 50 == 0:
                        self._save_to_disk()
                        logger.info(f"Enrichment progress: {i + 1}/{len(movies)}, {saved} new")
                    time.sleep(0.25)
                except Exception as e:
                    logger.error(f"Error enriching tmdb_id={tmdb_id}: {e}")
                    errors += 1

            self._save_to_disk()
            logger.info(f"Enrichment build done: {saved} enriched, {errors} errors")
        except Exception as e:
            logger.error(f"Enrichment build worker error: {e}")
        finally:
            self._building = False

    def enrich_on_demand(self, tmdb_id, title, year):
        """Trigger single-movie background enrichment if not already cached or pending."""
        tmdb_id_str = str(tmdb_id)
        with self._lock:
            if tmdb_id_str in self._cache or tmdb_id_str in self._pending:
                return
            self._pending.add(tmdb_id_str)
        Thread(target=self._on_demand_worker, args=(tmdb_id_str, title, year), daemon=True).start()

    def _on_demand_worker(self, tmdb_id_str, title, year):
        try:
            entry = self.enrich_single(tmdb_id_str, title, year)
            self.set(tmdb_id_str, entry)
            self._save_to_disk()
        except Exception as e:
            logger.error(f"On-demand enrichment error for tmdb_id={tmdb_id_str}: {e}")
        finally:
            with self._lock:
                self._pending.discard(tmdb_id_str)

    def build_logos_for_all(self):
        """Fetch missing logos for all cached entries (called when logo setting is enabled)."""
        Thread(target=self._logo_worker, daemon=True).start()

    def _logo_worker(self):
        from utils.tmdb_service import tmdb_service
        logger.info("Building missing logos for all enriched entries")
        updated = 0
        with self._lock:
            entries = list(self._cache.items())
        for tmdb_id_str, entry in entries:
            if entry.get('logo_url'):
                continue
            try:
                logo_url = tmdb_service.get_movie_logo_url(int(tmdb_id_str))
                if logo_url:
                    with self._lock:
                        if tmdb_id_str in self._cache:
                            self._cache[tmdb_id_str]['logo_url'] = logo_url
                    updated += 1
                time.sleep(0.25)
            except Exception as e:
                logger.warning(f"Error getting logo for tmdb_id={tmdb_id_str}: {e}")
        if updated > 0:
            self._save_to_disk()
        logger.info(f"Logo build done: {updated} logos added")


enrichment_cache = EnrichmentCache()
