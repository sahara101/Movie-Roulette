import json
import logging
import os
from functools import lru_cache
from threading import Lock
from urllib.parse import urlparse

import requests

from utils.auth.manager import auth_manager
from utils.settings import settings
from utils.version import VERSION


logger = logging.getLogger(__name__)

SIMKL_API_URL = 'https://api.simkl.com'
APP_NAME = 'movie-roulette'
HARDCODED_SIMKL_CLIENT_ID = '27c9377d5286895a5cb9265bf68a2adc6d3ef00b36c8a0296d93f6235766a4fd'
DATA_DIR = '/app/data'
USER_DATA_DIR = os.path.join(DATA_DIR, 'user_data')
DEFAULT_WATCHED_FILE = os.path.join(DATA_DIR, 'simkl_watched_movies.json')
DEFAULT_STATE_FILE = os.path.join(DATA_DIR, 'simkl_sync_state.json')

_sync_locks = {}
_sync_locks_guard = Lock()


def get_simkl_client_id():
    return (
        os.getenv('SIMKL_CLIENT_ID')
        or settings.get('simkl', {}).get('client_id')
        or HARDCODED_SIMKL_CLIENT_ID
    )


def is_simkl_env_controlled():
    return bool(os.getenv('SIMKL_ACCESS_TOKEN'))


def _get_user_data(user_id):
    if user_id == 'global':
        return None
    return (
        auth_manager.db.get_managed_user_by_username(user_id)
        or auth_manager.db.get_user(user_id)
    )


def get_user_simkl_token(user_id=None):
    if user_id is None:
        from utils.tracking_service import get_current_user_id
        user_id = get_current_user_id()

    env_token = os.getenv('SIMKL_ACCESS_TOKEN')
    if env_token:
        return env_token
    if user_id == 'global':
        return settings.get('simkl', {}).get('access_token') or None

    user_data = _get_user_data(user_id)
    return user_data.get('simkl_access_token') if user_data else None


def save_simkl_token(access_token, user_id=None):
    if user_id is None:
        from utils.tracking_service import get_current_user_id
        user_id = get_current_user_id()

    if is_simkl_env_controlled():
        return False, 'Simkl credentials are controlled by environment variables'
    if not access_token:
        return False, 'Missing Simkl access token'

    if user_id == 'global':
        settings.update('simkl', {'access_token': access_token})
        settings.update('tracking', {'provider': 'simkl'})
        settings.update('trakt', {'enabled': False})
        return True, 'Simkl connected'

    update_data = {
        'simkl_access_token': access_token,
        'tracking_provider': 'simkl',
        'trakt_enabled': False,
    }
    if auth_manager.db.get_managed_user_by_username(user_id):
        return auth_manager.db.update_managed_user_data(user_id, update_data)
    return auth_manager.db.update_user_data(user_id, update_data)


def clear_simkl_token(user_id=None):
    if user_id is None:
        from utils.tracking_service import get_current_user_id
        user_id = get_current_user_id()

    if is_simkl_env_controlled():
        return False, 'Simkl credentials are controlled by environment variables'

    if user_id == 'global':
        settings.update('simkl', {'access_token': None})
        if settings.get('tracking', {}).get('provider') == 'simkl':
            settings.update('tracking', {'provider': 'none'})
        return True, 'Simkl disconnected'

    user_data = _get_user_data(user_id)
    if not user_data:
        return False, 'User not found'
    update_data = {'simkl_access_token': None}
    if user_data.get('tracking_provider') == 'simkl':
        update_data['tracking_provider'] = 'none'
    if auth_manager.db.get_managed_user_by_username(user_id):
        return auth_manager.db.update_managed_user_data(user_id, update_data)
    return auth_manager.db.update_user_data(user_id, update_data)


def _request_params(params=None):
    combined = dict(params or {})
    combined.setdefault('client_id', get_simkl_client_id())
    combined.setdefault('app-name', APP_NAME)
    combined.setdefault('app-version', VERSION)
    return combined


def make_simkl_request(method, endpoint, user_id=None, authenticated=True, **kwargs):
    client_id = get_simkl_client_id()
    if not client_id:
        logger.warning('Cannot call Simkl API without a client ID')
        return None

    headers = dict(kwargs.pop('headers', {}) or {})
    headers.setdefault('User-Agent', f'Movie-Roulette/{VERSION}')
    if method.upper() == 'POST':
        headers.setdefault('Content-Type', 'application/json')

    if authenticated:
        token = get_user_simkl_token(user_id)
        if not token:
            return None
        headers['Authorization'] = f'Bearer {token}'

    kwargs['headers'] = headers
    kwargs['params'] = _request_params(kwargs.pop('params', None))
    kwargs.setdefault('timeout', 20)

    try:
        response = requests.request(method, f'{SIMKL_API_URL}/{endpoint.lstrip("/")}', **kwargs)
    except requests.RequestException as exc:
        logger.warning('Simkl request failed for %s: %s', endpoint, exc)
        return None

    if authenticated and response.status_code == 401 and not is_simkl_env_controlled():
        logger.warning('Simkl token was revoked for user %s', user_id)
        clear_simkl_token(user_id)
    return response


def _directory_key(user_id):
    if user_id == 'global':
        return None
    managed_user = auth_manager.db.get_managed_user_by_username(user_id)
    if managed_user and managed_user.get('plex_user_id'):
        return f"plex_managed_{managed_user['plex_user_id']}"
    return user_id


def _cache_paths(user_id):
    directory_key = _directory_key(user_id)
    if directory_key is None:
        return DEFAULT_WATCHED_FILE, DEFAULT_STATE_FILE
    user_dir = os.path.join(USER_DATA_DIR, directory_key)
    return (
        os.path.join(user_dir, 'simkl_watched_movies.json'),
        os.path.join(user_dir, 'simkl_sync_state.json'),
    )


def _read_json(path, default):
    try:
        with open(path, 'r') as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f'{path}.tmp'
    with open(temp_path, 'w') as handle:
        json.dump(data, handle)
    os.replace(temp_path, path)


def get_local_watched_movies(user_id=None):
    if user_id is None:
        from utils.tracking_service import get_current_user_id
        user_id = get_current_user_id()
    watched_path, _ = _cache_paths(user_id)
    values = _read_json(watched_path, [])
    return values if isinstance(values, list) else []


def _extract_movie_changes(payload):
    if not isinstance(payload, dict):
        return []
    changes = []
    for item in payload.get('movies', []) or []:
        movie = item.get('movie') or {}
        ids = movie.get('ids') or {}
        tmdb_id = ids.get('tmdb')
        try:
            tmdb_id = int(tmdb_id)
        except (TypeError, ValueError):
            continue
        changes.append((tmdb_id, item.get('status')))
    return changes


def _activity_state(payload):
    movies = payload.get('movies', {}) if isinstance(payload, dict) else {}
    return {
        'movies_all': movies.get('all'),
        'movies_removed': movies.get('removed_from_list'),
    }


def _fetch_activities(user_id):
    response = make_simkl_request('GET', 'sync/activities', user_id)
    if not response or not response.ok:
        return None
    payload = response.json()
    return _activity_state(payload)


def _full_completed_sync(user_id):
    response = make_simkl_request(
        'GET',
        'sync/all-items/movies/completed',
        user_id,
        params={'extended': 'ids_only'},
    )
    if not response or not response.ok:
        return None
    return sorted({tmdb_id for tmdb_id, _ in _extract_movie_changes(response.json())})


def _get_sync_lock(user_id):
    with _sync_locks_guard:
        return _sync_locks.setdefault(user_id, Lock())


def sync_watched_status(user_id=None, force=False):
    if user_id is None:
        from utils.tracking_service import get_current_user_id
        user_id = get_current_user_id()

    from utils.tracking_service import get_tracking_provider
    if get_tracking_provider(user_id) != 'simkl' or not get_user_simkl_token(user_id):
        return []

    watched_path, state_path = _cache_paths(user_id)
    with _get_sync_lock(user_id):
        watched = set(get_local_watched_movies(user_id))
        previous_state = _read_json(state_path, {})
        current_state = _fetch_activities(user_id)
        if current_state is None:
            return sorted(watched)

        needs_initial = force or not os.path.exists(watched_path) or not previous_state.get('movies_all')
        removed_changed = (
            previous_state.get('movies_removed') != current_state.get('movies_removed')
        )

        if needs_initial or removed_changed:
            refreshed = _full_completed_sync(user_id)
            if refreshed is None:
                return sorted(watched)
            watched = set(refreshed)
        elif previous_state.get('movies_all') != current_state.get('movies_all'):
            response = make_simkl_request(
                'GET',
                'sync/all-items/movies',
                user_id,
                params={
                    'date_from': previous_state['movies_all'],
                    'extended': 'ids_only',
                },
            )
            if not response or not response.ok:
                return sorted(watched)
            for tmdb_id, status in _extract_movie_changes(response.json()):
                if status == 'completed':
                    watched.add(tmdb_id)
                else:
                    watched.discard(tmdb_id)

        result = sorted(watched)
        _write_json(watched_path, result)
        _write_json(state_path, current_state)
        return result


@lru_cache(maxsize=1000)
def _resolve_simkl_movie(tmdb_id):
    response = make_simkl_request(
        'GET',
        'redirect',
        authenticated=False,
        allow_redirects=False,
        params={'to': 'simkl', 'type': 'movie', 'tmdb': tmdb_id},
    )
    if not response or response.status_code not in (301, 302, 307, 308):
        return None, None
    location = response.headers.get('Location')
    if not location:
        return None, None
    parts = [part for part in urlparse(location).path.split('/') if part]
    if len(parts) < 2 or parts[0] != 'movies':
        return None, location
    try:
        return int(parts[1]), location
    except ValueError:
        return None, location


def get_simkl_rating(tmdb_id):
    simkl_id, _ = _resolve_simkl_movie(str(tmdb_id))
    if not simkl_id:
        return 0
    response = make_simkl_request('GET', f'movies/{simkl_id}', authenticated=False)
    if not response or not response.ok:
        return 0
    rating = (((response.json().get('ratings') or {}).get('simkl') or {}).get('rating'))
    try:
        return int(round(float(rating) * 10))
    except (TypeError, ValueError):
        return 0
