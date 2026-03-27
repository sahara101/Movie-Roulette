from flask import Blueprint, jsonify, request, g
import logging
import os
from utils.auth.manager import auth_manager
from utils.plex_service import PlexService
from utils.settings import settings

logger = logging.getLogger(__name__)
watchlist_bp = Blueprint('watchlist_bp', __name__)


@watchlist_bp.route('/api/plex/app_users')
@auth_manager.require_auth
def get_plex_app_users():
    """Legacy endpoint — kept for backward compatibility."""
    admin_token = settings.get('plex', {}).get('token', '')
    if not admin_token:
        return jsonify({'users': []})
    try:
        import requests as _req
        resp = _req.post(
            'https://community.plex.tv/api',
            json={'query': 'query { allFriendsV2 { user { id username } } }'},
            headers={'X-Plex-Token': admin_token, 'Content-Type': 'application/json'},
            timeout=10
        )
        resp.raise_for_status()
        friends = resp.json().get('data', {}).get('allFriendsV2', [])
        users = [{'username': f['user']['id'], 'display_name': f['user']['username']}
                 for f in friends]
        return jsonify({'users': users})
    except Exception as e:
        logger.error("Failed to fetch Plex friends: %s", e)
        return jsonify({'users': []})


@watchlist_bp.route('/api/plex/watch_partners')
@auth_manager.require_auth
def get_watch_partners():
    """
    Return combined list of watchlist partners (plex.tv friends) and library partners
    (app users with a built Plex cache). Each entry includes which modes are available.
    """
    admin_token = settings.get('plex', {}).get('token', '')
    current_internal = (g.user or {}).get('internal_username', '')
    partners = {}

    # For local admin, find their Plex identity via the is_plex_owner flag
    current_plex_internal = current_internal
    if not current_internal.startswith('plex_'):
        for uname, udata in auth_manager.db.users.items():
            if uname.startswith('plex_') and udata.get('is_plex_owner'):
                current_plex_internal = uname
                break

    if admin_token:
        try:
            import requests as _req
            resp = _req.post(
                'https://community.plex.tv/api',
                json={'query': 'query { allFriendsV2 { user { id username } } }'},
                headers={'X-Plex-Token': admin_token, 'Content-Type': 'application/json'},
                timeout=10
            )
            resp.raise_for_status()
            friends = (resp.json().get('data') or {}).get('allFriendsV2', [])
            for f in friends:
                name = f['user']['username']
                if name == current_internal or f'plex_{name}' in (current_internal, current_plex_internal):
                    continue
                partners[name] = {
                    'display_name': name,
                    'modes': ['watchlist'],
                    'watchlist_id': f['user']['id'],
                    'library_id': None,
                }
        except Exception as e:
            logger.error("watch_partners: failed to fetch Plex friends: %s", e)

    user_data_dir = '/app/data/user_data'
    if os.path.exists(user_data_dir):
        for entry in os.listdir(user_data_dir):
            if not entry.startswith('plex_'):
                continue
            if entry in (current_internal, current_plex_internal, f'plex_{current_internal}'):
                continue
            cache_path = os.path.join(user_data_dir, entry, 'plex_all_movies.json')
            if not os.path.exists(cache_path):
                continue
            plex_username = entry[len('plex_'):]
            if plex_username in partners:
                partners[plex_username]['modes'].append('library')
                partners[plex_username]['library_id'] = entry
            else:
                partners[plex_username] = {
                    'display_name': plex_username,
                    'modes': ['library'],
                    'watchlist_id': None,
                    'library_id': entry,
                }

    return jsonify({'partners': list(partners.values())})


@watchlist_bp.route('/api/shared_watchlist_movie')
@auth_manager.require_auth
def shared_watchlist_movie():
    """Return a random movie from a shared pool based on partner_mode (watchlist or library)."""
    plex_service = g.media_service
    if not isinstance(plex_service, PlexService):
        return jsonify({'error': 'Plex not available or not the active service'}), 400

    partner_id   = request.args.get('partner_username', '')
    partner_mode = request.args.get('partner_mode', 'watchlist')
    if not partner_id:
        return jsonify({'error': 'No partner selected'}), 400

    genres      = [x for x in request.args.get('genres',      '').split(',') if x]
    years       = [x for x in request.args.get('years',       '').split(',') if x]
    pg_ratings  = [x for x in request.args.get('pg_ratings',  '').split(',') if x]
    watch_status = request.args.get('watch_status', 'unwatched')
    session_key  = request.args.get('session_key', '')
    count_only   = request.args.get('count_only', '').lower() == 'true'

    from movie_selector import _get_seen_ids, _add_seen_id, _reset_seen, _merge_enrichment

    try:
        if partner_mode == 'library':
            pool = plex_service.get_library_intersection_pool(partner_id, watch_status)
        else:
            admin_token = settings.get('plex', {}).get('token', '')
            if not admin_token:
                return jsonify({'error': 'Plex admin token not configured'}), 400
            pool = plex_service.get_shared_watchlist_pool(admin_token, partner_id)
    except Exception as e:
        logger.error("Watch partner pool error (%s): %s", partner_mode, e)
        return jsonify({'error': 'Could not fetch partner data'}), 500

    if not pool:
        if count_only:
            return jsonify({'count': 0})
        msg = 'No movies in your shared library' if partner_mode == 'library' else 'No movies on both watchlists in your library'
        return jsonify({'error': msg}), 404

    if count_only:
        all_filtered = plex_service.filter_movies(
            genres=genres, years=years, pg_ratings=pg_ratings,
            watch_status=watch_status, movies_pool=pool, get_all=True
        )
        return jsonify({'count': len(all_filtered) if all_filtered else 0})

    seen_ids = _get_seen_ids(session_key)
    pool_reset = False
    seen_count = len(seen_ids)

    movie = plex_service.filter_movies(
        genres=genres, years=years, pg_ratings=pg_ratings,
        watch_status=watch_status, movies_pool=pool, exclude_ids=seen_ids
    )
    if not movie and seen_ids:
        seen_count = len(seen_ids)
        _reset_seen(session_key)
        seen_ids = set()
        pool_reset = True
        movie = plex_service.filter_movies(
            genres=genres, years=years, pg_ratings=pg_ratings,
            watch_status=watch_status, movies_pool=pool
        )

    if not movie:
        return jsonify({'error': 'No matching movies'}), 404

    movie_id = str(movie.get('id', ''))
    _add_seen_id(session_key, movie_id)
    movie = _merge_enrichment(movie)

    return jsonify({'service': 'plex', 'movie': movie, 'pool_reset': pool_reset, 'seen_count': seen_count})
