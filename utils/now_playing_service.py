import logging
from datetime import datetime, timedelta

from utils.settings import settings
from utils.poster_view import get_poster_proxy_url, get_backdrop_proxy_url, get_current_timezone

logger = logging.getLogger(__name__)

_plex_owner_username = None
_plex_owner_account_id = None


def get_now_playing(user_data, app):
    """Main entry point. Returns a dict with now-playing info, or None."""
    try:
        if _is_admin_or_global(user_data):
            return _get_owner_session(app)
        return _get_user_session(user_data, app)
    except Exception as e:
        logger.error(f"Error in get_now_playing: {e}", exc_info=True)
        return None


def _is_admin_or_global(user_data):
    """Return True if global (no auth) or local admin."""
    if user_data is None:
        return True
    return user_data.get('service_type', 'local') == 'local'


def _get_owner_session(app):
    """Branch A: fetch primary owner's active movie session across all services."""
    plex_service = app.config.get('PLEX_SERVICE')
    jellyfin_service = app.config.get('JELLYFIN_SERVICE')
    emby_service = app.config.get('EMBY_SERVICE')

    if plex_service:
        result = _get_plex_owner_session(plex_service)
        if result:
            return result

    if jellyfin_service:
        result = _get_jellyfin_owner_session(jellyfin_service)
        if result:
            return result

    if emby_service:
        result = _get_emby_owner_session(emby_service)
        if result:
            return result

    return None


def _get_user_session(user_data, app):
    """Branch B: fetch the logged-in service user's own session."""
    service_type = user_data.get('service_type', 'local')
    internal_username = user_data.get('username', '')

    media_username = _strip_service_prefix(internal_username, service_type)

    plex_service = app.config.get('PLEX_SERVICE')
    jellyfin_service = app.config.get('JELLYFIN_SERVICE')
    emby_service = app.config.get('EMBY_SERVICE')

    if service_type in ('plex', 'plex_managed') and plex_service:
        return _find_plex_session_by_username(plex_service, media_username)

    if service_type == 'jellyfin' and jellyfin_service:
        return _find_jellyfin_session_by_username(jellyfin_service, media_username)

    if service_type == 'emby' and emby_service:
        return _find_emby_session_by_username(emby_service, media_username)

    return None


def _strip_service_prefix(internal_username, service_type):
    """Strip the service prefix from an internal username.

    E.g. 'jellyfin_alice' -> 'alice', 'plex_john' -> 'john'.
    For plex_managed users, the username may or may not have a prefix.
    """
    prefix_map = {
        'plex': 'plex_',
        'plex_managed': 'plex_managed_',
        'jellyfin': 'jellyfin_',
        'emby': 'emby_',
    }
    prefix = prefix_map.get(service_type, '')
    if prefix and internal_username.startswith(prefix):
        return internal_username[len(prefix):]
    return internal_username


def _compute_status(position_seconds, total_seconds, is_paused):
    """Compute playback status from position, duration and pause state."""
    if is_paused:
        return 'PAUSED'
    if total_seconds > 0 and position_seconds > 0 and (position_seconds / total_seconds) >= 0.90:
        return 'ENDING'
    return 'PLAYING'


def _parse_imdb_id(imdb_url):
    """Extract tt-ID from a full IMDb URL."""
    if imdb_url and '/title/' in imdb_url:
        return imdb_url.split('/title/')[-1].strip('/')
    return ''


def _build_response(movie_data, service, position_seconds, total_seconds, is_paused, username):
    """Build the standard response dict from movie_data and playback state."""
    tz = get_current_timezone()
    start_time = (datetime.now(tz) - timedelta(seconds=position_seconds)).isoformat()
    status = _compute_status(position_seconds, total_seconds, is_paused)

    return {
        'active': True,
        'status': status,
        'title': movie_data.get('title', ''),
        'year': movie_data.get('year', ''),
        'poster': movie_data.get('poster', ''),
        'service': service,
        'start_time': start_time,
        'total_seconds': int(total_seconds),
        'username': username,
        'tmdb_id': movie_data.get('tmdb_id', ''),
        'imdb_id': _parse_imdb_id(movie_data.get('imdb_url', '')),
        'poster_proxy': get_poster_proxy_url(movie_data.get('poster', ''), service),
        'backdrop_proxy': get_backdrop_proxy_url(movie_data.get('background', ''), service),
    }

def _get_plex_owner_info(plex_service):
    """Fetch and cache the primary Plex account owner's @username and numeric account ID.

    Returns (username, account_id) — either value may be None on API failure.
    Both values are cached module-level after the first successful call.
    """
    global _plex_owner_username, _plex_owner_account_id
    if _plex_owner_username is not None or _plex_owner_account_id is not None:
        return _plex_owner_username, _plex_owner_account_id
    try:
        account = plex_service.plex.myPlexAccount()
        _plex_owner_username = account.username
        _plex_owner_account_id = str(account.id)
        logger.info(
            "Cached Plex owner info: username='%s', account_id=%s",
            _plex_owner_username, _plex_owner_account_id,
        )
    except Exception as e:
        logger.warning("Could not fetch Plex owner info: %s", e)
    return _plex_owner_username, _plex_owner_account_id


def _get_plex_session_account_id(session):
    """Extract the User id attribute from a Plex session's XML element.

    In Plex, each <Video> session carries a <User id="…" title="…"/> child.
    The id is the plex.tv account ID — unique and stable, unlike display titles.
    """
    try:
        user_elem = session._data.find('User')
        if user_elem is not None:
            return user_elem.get('id')
    except Exception:
        pass
    return None


def _get_plex_owner_session(plex_service):
    """Find the Plex session belonging to the primary account owner.

    Matching priority:
      1. Numeric account ID (most reliable — immune to display-name changes)
      2. @username match (fallback when XML id is unavailable)
    Returns None when the owner is not actively watching a movie.
    """
    try:
        sessions = plex_service.plex.sessions()
        movie_sessions = [s for s in sessions if s.type == 'movie']
        if not movie_sessions:
            return None

        owner_username, owner_account_id = _get_plex_owner_info(plex_service)
        if not owner_username and not owner_account_id:
            logger.warning(
                "Could not determine Plex owner info; no session returned for admin/global view"
            )
            return None

        for s in movie_sessions:
            session_account_id = _get_plex_session_account_id(s)
            if owner_account_id and session_account_id and session_account_id == owner_account_id:
                logger.info("Matched Plex owner session by account ID %s", owner_account_id)
                return _build_plex_response(plex_service, s)
            session_user = s.usernames[0] if s.usernames else None
            if owner_username and session_user and session_user.lower() == owner_username.lower():
                logger.info("Matched Plex owner session by username '%s'", owner_username)
                return _build_plex_response(plex_service, s)

        logger.info(
            "Plex owner (username='%s', id=%s) has no active movie session",
            owner_username, owner_account_id,
        )
        return None
    except Exception as e:
        logger.error("Error fetching Plex owner session: %s", e, exc_info=True)
        return None


def _find_plex_session_by_username(plex_service, media_username):
    """Find a Plex session by media server username."""
    try:
        sessions = plex_service.plex.sessions()
        for s in sessions:
            if s.type != 'movie':
                continue
            session_user = s.usernames[0] if s.usernames else None
            if session_user and session_user.lower() == media_username.lower():
                return _build_plex_response(plex_service, s)
        return None
    except Exception as e:
        logger.error(f"Error fetching Plex session for user {media_username}: {e}", exc_info=True)
        return None


def _build_plex_response(plex_service, session):
    """Build a response dict from a Plex session object."""
    try:
        username = session.usernames[0] if session.usernames else ''
        position_ms = getattr(session, 'viewOffset', 0) or 0
        duration_ms = getattr(session, 'duration', 0) or 0
        position_seconds = position_ms / 1000
        total_seconds = duration_ms / 1000
        player_state = getattr(getattr(session, 'player', None), 'state', 'playing') or 'playing'
        is_paused = player_state == 'paused'

        movie_data = plex_service.get_movie_by_id(session.ratingKey)
        if not movie_data:
            logger.warning(f"Could not fetch movie data for Plex ratingKey {session.ratingKey}")
            return None

        return _build_response(movie_data, 'plex', position_seconds, total_seconds, is_paused, username)
    except Exception as e:
        logger.error(f"Error building Plex response: {e}", exc_info=True)
        return None

def _get_jellyfin_owner_session(jellyfin_service):
    """Find the Jellyfin session belonging to the configured admin user."""
    try:
        sessions = jellyfin_service.get_active_sessions()
        movie_sessions = [
            s for s in sessions
            if s.get('NowPlayingItem', {}).get('Type') == 'Movie'
        ]
        if not movie_sessions:
            return None

        jellyfin_user_id = settings.get('jellyfin', {}).get('user_id', '')
        if not jellyfin_user_id:
            logger.warning("Jellyfin user_id not configured; no session returned for admin/global view")
            return None

        for s in movie_sessions:
            if s.get('UserId') == jellyfin_user_id:
                return _build_jellyfin_emby_response(jellyfin_service, s, 'jellyfin')

        logger.info("Jellyfin primary user (ID=%s) has no active movie session", jellyfin_user_id)
        return None
    except Exception as e:
        logger.error(f"Error fetching Jellyfin owner session: {e}", exc_info=True)
        return None


def _find_jellyfin_session_by_username(jellyfin_service, media_username):
    """Find a Jellyfin session by media server username."""
    try:
        sessions = jellyfin_service.get_active_sessions()
        for s in sessions:
            if s.get('NowPlayingItem', {}).get('Type') != 'Movie':
                continue
            if s.get('UserName', '').lower() == media_username.lower():
                return _build_jellyfin_emby_response(jellyfin_service, s, 'jellyfin')
        return None
    except Exception as e:
        logger.error(f"Error fetching Jellyfin session for user {media_username}: {e}", exc_info=True)
        return None

def _get_emby_owner_session(emby_service):
    """Find the Emby session belonging to the configured admin user."""
    try:
        sessions = emby_service.get_active_sessions()
        movie_sessions = [
            s for s in sessions
            if s.get('NowPlayingItem', {}).get('Type') == 'Movie'
        ]
        if not movie_sessions:
            return None

        emby_user_id = settings.get('emby', {}).get('user_id', '')
        if not emby_user_id:
            logger.warning("Emby user_id not configured; no session returned for admin/global view")
            return None

        for s in movie_sessions:
            if s.get('UserId') == emby_user_id:
                return _build_jellyfin_emby_response(emby_service, s, 'emby')

        logger.info("Emby primary user (ID=%s) has no active movie session", emby_user_id)
        return None
    except Exception as e:
        logger.error(f"Error fetching Emby owner session: {e}", exc_info=True)
        return None


def _find_emby_session_by_username(emby_service, media_username):
    """Find an Emby session by media server username."""
    try:
        sessions = emby_service.get_active_sessions()
        for s in sessions:
            if s.get('NowPlayingItem', {}).get('Type') != 'Movie':
                continue
            if s.get('UserName', '').lower() == media_username.lower():
                return _build_jellyfin_emby_response(emby_service, s, 'emby')
        return None
    except Exception as e:
        logger.error(f"Error fetching Emby session for user {media_username}: {e}", exc_info=True)
        return None

def _build_jellyfin_emby_response(service, session, service_name):
    """Build a response dict from a Jellyfin or Emby session dict."""
    try:
        username = session.get('UserName', '')
        play_state = session.get('PlayState', {})
        position_ticks = play_state.get('PositionTicks', 0) or 0
        position_seconds = position_ticks / 10_000_000
        is_paused = play_state.get('IsPaused', False)

        now_playing = session.get('NowPlayingItem', {})
        movie_id = now_playing.get('Id')
        if not movie_id:
            return None

        movie_data = service.get_movie_by_id(movie_id)
        if not movie_data:
            logger.warning(f"Could not fetch movie data for {service_name} movie ID {movie_id}")
            return None

        total_seconds = (
            movie_data.get('duration_hours', 0) * 3600
            + movie_data.get('duration_minutes', 0) * 60
        )

        return _build_response(movie_data, service_name, position_seconds, total_seconds, is_paused, username)
    except Exception as e:
        logger.error(f"Error building {service_name} response: {e}", exc_info=True)
        return None
