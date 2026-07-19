import os
from urllib.parse import urlencode

from flask import has_request_context, request, session

from utils.auth.manager import auth_manager
from utils.settings import settings
from utils.version import VERSION


VALID_TRACKING_PROVIDERS = ('none', 'trakt', 'simkl')
PROVIDER_LABELS = {
    'none': 'None',
    'trakt': 'Trakt',
    'simkl': 'Simkl',
}


def get_current_user_id():
    """Return the authenticated internal username, or global when auth is disabled."""
    if not auth_manager.auth_enabled:
        return 'global'

    if has_request_context():
        token = request.cookies.get('auth_token')
        if token:
            user_data = auth_manager.verify_auth(token)
            if user_data:
                return user_data['username']

        username = session.get('username')
        if username:
            return username

    return 'global'


def _get_user_data(user_id):
    if not user_id or user_id == 'global':
        return None
    return (
        auth_manager.db.get_managed_user_by_username(user_id)
        or auth_manager.db.get_user(user_id)
    )


def _normalize_provider(provider):
    provider = str(provider or 'none').strip().lower()
    return provider if provider in VALID_TRACKING_PROVIDERS else 'none'


def get_tracking_provider(user_id=None):
    """Resolve one active tracking provider, retaining compatibility with Trakt settings."""
    user_id = user_id or get_current_user_id()

    env_provider = os.getenv('TRACKING_PROVIDER')
    if env_provider:
        return _normalize_provider(env_provider)

    if user_id == 'global':
        provider = _normalize_provider(settings.get('tracking', {}).get('provider'))
        if provider != 'none':
            return provider

        # Existing installations have no tracking.provider value on disk.
        if settings.get('trakt', {}).get('enabled'):
            return 'trakt'
        if os.getenv('TRAKT_ACCESS_TOKEN'):
            return 'trakt'
        if os.getenv('SIMKL_ACCESS_TOKEN'):
            return 'simkl'
        return 'none'

    user_data = _get_user_data(user_id)
    if not user_data:
        return 'none'

    provider = user_data.get('tracking_provider')
    if provider in VALID_TRACKING_PROVIDERS:
        return provider
    return 'trakt' if user_data.get('trakt_enabled') else 'none'


def is_tracking_env_controlled():
    return bool(os.getenv('TRACKING_PROVIDER'))


def set_tracking_provider(provider, user_id=None):
    """Select the sole active tracker without deleting either provider's token."""
    provider = _normalize_provider(provider)
    user_id = user_id or get_current_user_id()

    if is_tracking_env_controlled():
        return False, 'Tracking provider is controlled by TRACKING_PROVIDER'

    if user_id == 'global':
        settings.update('tracking', {'provider': provider})
        settings.update('trakt', {'enabled': provider == 'trakt'})
        return True, 'Tracking provider updated'

    user_data = _get_user_data(user_id)
    if not user_data:
        return False, 'User not found'

    update_data = {
        'tracking_provider': provider,
        'trakt_enabled': provider == 'trakt',
    }
    if auth_manager.db.get_managed_user_by_username(user_id):
        return auth_manager.db.update_managed_user_data(user_id, update_data)
    return auth_manager.db.update_user_data(user_id, update_data)


def is_tracking_enabled(user_id=None):
    user_id = user_id or get_current_user_id()
    provider = get_tracking_provider(user_id)
    if provider == 'trakt':
        from utils.trakt_service import get_user_trakt_tokens
        return bool(get_user_trakt_tokens(user_id))
    if provider == 'simkl':
        from utils.simkl_service import get_user_simkl_token, get_simkl_client_id
        return bool(get_simkl_client_id() and get_user_simkl_token(user_id))
    return False


def get_tracking_status(user_id=None):
    user_id = user_id or get_current_user_id()
    provider = get_tracking_provider(user_id)

    from utils.trakt_service import get_user_trakt_tokens, is_trakt_env_controlled
    from utils.simkl_service import (
        get_simkl_client_id,
        get_user_simkl_token,
        is_simkl_env_controlled,
    )

    trakt_connected = bool(get_user_trakt_tokens(user_id))
    simkl_connected = bool(get_user_simkl_token(user_id))
    return {
        'provider': provider,
        'provider_label': PROVIDER_LABELS[provider],
        'enabled': is_tracking_enabled(user_id),
        'env_controlled': is_tracking_env_controlled(),
        'providers': {
            'trakt': {
                'connected': trakt_connected,
                'configured': True,
                'env_controlled': is_trakt_env_controlled(),
            },
            'simkl': {
                'connected': simkl_connected,
                'configured': bool(get_simkl_client_id()),
                'env_controlled': is_simkl_env_controlled(),
            },
        },
    }


def get_local_watched_movies(user_id=None):
    user_id = user_id or get_current_user_id()
    provider = get_tracking_provider(user_id)
    if provider == 'trakt':
        from utils.trakt_service import get_local_watched_movies as get_trakt_watched
        return get_trakt_watched(user_id)
    if provider == 'simkl':
        from utils.simkl_service import get_local_watched_movies as get_simkl_watched
        return get_simkl_watched(user_id)
    return []


def sync_watched_status(user_id=None, force=False):
    user_id = user_id or get_current_user_id()
    provider = get_tracking_provider(user_id)
    if provider == 'trakt':
        from utils.trakt_service import sync_watched_status as sync_trakt_watched
        return sync_trakt_watched(user_id)
    if provider == 'simkl':
        from utils.simkl_service import sync_watched_status as sync_simkl_watched
        return sync_simkl_watched(user_id, force=force)
    return []


def get_watched_movies(user_id=None):
    return sync_watched_status(user_id)


def is_movie_watched(tmdb_id, user_id=None):
    try:
        normalized_id = int(tmdb_id)
    except (TypeError, ValueError):
        return False
    return normalized_id in set(get_local_watched_movies(user_id))


def get_tracking_rating(tmdb_id, user_id=None):
    user_id = user_id or get_current_user_id()
    provider = get_tracking_provider(user_id)
    if provider == 'trakt':
        from utils.trakt_service import get_trakt_rating
        return get_trakt_rating(tmdb_id, user_id)
    if provider == 'simkl':
        from utils.simkl_service import get_simkl_rating
        return get_simkl_rating(tmdb_id)
    return 0


def get_movie_ratings(tmdb_id, user_id=None):
    provider = get_tracking_provider(user_id)
    rating = get_tracking_rating(tmdb_id, user_id) if provider != 'none' else 0
    return {
        'tracking_provider': provider,
        'tracking_rating_label': PROVIDER_LABELS[provider],
        'tracking_rating': rating or None,
        # Compatibility for clients using the old response shape.
        'trakt_rating': rating if provider == 'trakt' else None,
        'simkl_rating': rating if provider == 'simkl' else None,
        'imdb_rating': None,
    }


def get_tracking_url(tmdb_id, trakt_url=None, user_id=None):
    provider = get_tracking_provider(user_id)
    if provider == 'trakt':
        return trakt_url
    if provider != 'simkl':
        return None

    from utils.simkl_service import get_simkl_client_id
    client_id = get_simkl_client_id()
    if not client_id:
        return None
    query = urlencode({
        'to': 'simkl',
        'type': 'movie',
        'tmdb': tmdb_id,
        'client_id': client_id,
        'app-name': 'movie-roulette',
        'app-version': VERSION,
    })
    return f'https://api.simkl.com/redirect?{query}'


def add_tracking_metadata(payload, tmdb_id, trakt_url=None, user_id=None):
    provider = get_tracking_provider(user_id)
    payload['tracking_provider'] = provider
    payload['tracking_provider_label'] = PROVIDER_LABELS[provider]
    payload['tracking_rating'] = get_tracking_rating(tmdb_id, user_id)
    payload['tracking_url'] = get_tracking_url(tmdb_id, trakt_url, user_id)
    return payload
