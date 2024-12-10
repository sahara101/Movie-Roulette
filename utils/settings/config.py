DEFAULT_SETTINGS = {
    'plex': {
        'enabled': False,
        'url': '',
        'token': '',
        'movie_libraries': []
    },
    'jellyfin': {
        'enabled': False,
        'url': '',
        'api_key': '',
        'user_id': ''
    },
    'clients': {
        'apple_tv': {
            'enabled': False,
            'id': ''
        },
        'lg_tv': {
            'enabled': False,
            'ip': '',
            'mac': ''
        }
    },
    'features': {
        'use_links': True,
        'use_filter': True,
        'use_watch_button': True,
        'use_next_button': True,
        'homepage_mode': False,
        'timezone': 'UTC',
        'default_poster_text': '',
        'poster_users': {
            'plex': [],
            'jellyfin': []
        }
    },
    'overseerr': {
        'enabled': False,
        'url': '',
        'api_key': ''
    },
    'tmdb': {
        'enabled': False,  # If False, use built-in key
        'api_key': ''     # Optional user-provided key
    },
    'trakt': {
        'enabled': False,
        'client_id': '',
        'client_secret': '',
        'access_token': '',
        'refresh_token': ''
    }
}

ENV_MAPPINGS = {
    # Homepage ENV
    'HOMEPAGE_MODE': ('features', 'homepage_mode', lambda x: x.upper() == 'TRUE'),
    'TZ': ('features', 'timezone', str),
    'DEFAULT_POSTER_TEXT': ('features', 'default_poster_text', str),
    'PLEX_POSTER_USERS': ('features.poster_users', 'plex', lambda x: [s.strip() for s in x.split(',')]),
    'JELLYFIN_POSTER_USERS': ('features.poster_users', 'jellyfin', lambda x: [s.strip() for s in x.split(',')]),
    
    # Plex ENV
    'PLEX_URL': ('plex', 'url', str),
    'PLEX_TOKEN': ('plex', 'token', str),
    'PLEX_MOVIE_LIBRARIES': ('plex', 'movie_libraries', lambda x: [s.strip() for s in x.split(',')]),
    
    # Jellyfin ENV
    'JELLYFIN_URL': ('jellyfin', 'url', str),
    'JELLYFIN_API_KEY': ('jellyfin', 'api_key', str),
    'JELLYFIN_USER_ID': ('jellyfin', 'user_id', str),
    
    # Client ENV
    'APPLE_TV_ID': ('clients.apple_tv', 'id', str),
    'LGTV_IP': ('clients.lg_tv', 'ip', str),
    'LGTV_MAC': ('clients.lg_tv', 'mac', str),
    
    # Feature flags
    'USE_LINKS': ('features', 'use_links', lambda x: x.upper() == 'TRUE'),
    'USE_FILTER': ('features', 'use_filter', lambda x: x.upper() == 'TRUE'),
    'USE_WATCH_BUTTON': ('features', 'use_watch_button', lambda x: x.upper() == 'TRUE'),
    'USE_NEXT_BUTTON': ('features', 'use_next_button', lambda x: x.upper() == 'TRUE'),
    
    # Overseerr
    'OVERSEERR_URL': ('overseerr', 'url', str),
    'OVERSEERR_API_KEY': ('overseerr', 'api_key', str),
    
    # TMDB
    'TMDB_API_KEY': ('tmdb', 'api_key', str),
    
    # Trakt
    'TRAKT_CLIENT_ID': ('trakt', 'client_id', str),
    'TRAKT_CLIENT_SECRET': ('trakt', 'client_secret', str),
    'TRAKT_ACCESS_TOKEN': ('trakt', 'access_token', str),
    'TRAKT_REFRESH_TOKEN': ('trakt', 'refresh_token', str),
}
