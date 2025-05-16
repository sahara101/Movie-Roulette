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
        'user_id': '',
        'connect_enabled': False
    },
    'emby': {
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
        'tvs': {
            'blacklist': {
                'mac_addresses': []
            },
            'instances': {}
        }
    },
    'features': {
        'use_links': True,
        'use_filter': True,
        'use_watch_button': True,
        'use_next_button': True,
        'mobile_truncation': False,
        'homepage_mode': False,
        'enable_movie_logos': True, 
        'load_movie_on_start': False,
        'login_backdrop': {
            'enabled': False
        },
        'timezone': 'UTC',
        'poster_mode': 'default',  # 'default' or 'screensaver'
        'screensaver_interval': 300,
        'default_poster_text': '',
        'poster_users': {
            'plex': [],
            'jellyfin': [],
            'emby': []
        },
        'poster_display': {
            'mode': 'first_active',  # 'first_active' or 'preferred_user'
            'preferred_user': {}
        }
    },
    'request_services': {
        'default': 'auto',  # Values: auto, overseerr, jellyseerr, ombi
        'plex_override': 'auto',  # Values: auto, overseerr, jellyseerr, ombi
        'jellyfin_override': 'auto',  # Values: auto, jellyseerr, ombi
        'emby_override': 'auto'  # Values: auto, jellyseerr, ombi
    },
    'overseerr': {
        'enabled': False,
        'url': '',
        'api_key': ''
    },
    'jellyseerr': {
        'enabled': False,
        'url': '',
        'api_key': ''
    },
    'ombi': {
        'enabled': False,
        'url': '',
        'api_key': ''
    },
    'tmdb': {
        'enabled': False,
        'api_key': ''
    },
    'trakt': {
        'enabled': False,
        'client_id': '',
        'client_secret': '',
        'access_token': '',
        'refresh_token': ''
    },
    'system': {
        'disable_settings': False
    }
}

AUTH_SETTINGS = {
    'auth': {
        'enabled': False,
        'session_lifetime': 86400,
        'passkey_enabled': False,
        'relying_party_id': '',  # e.g., 'localhost' or 'yourdomain.com' - Should match the domain users use.
        'relying_party_origin': '' # e.g., 'https://yourdomain.com' or 'http://localhost:4000' - Full origin.
    }
}

ENV_MAPPINGS = {
    # Features ENV
    'HOMEPAGE_MODE': ('features', 'homepage_mode', lambda x: x.upper() == 'TRUE'),
    'TZ': ('features', 'timezone', str),
    'DEFAULT_POSTER_TEXT': ('features', 'default_poster_text', str),
    'POSTER_MODE': ('features', 'poster_mode', str),
    'SCREENSAVER_INTERVAL': ('features', 'screensaver_interval', int),
    'PLEX_POSTER_USERS': ('features.poster_users', 'plex', lambda x: [s.strip() for s in x.split(',')]),
    'JELLYFIN_POSTER_USERS': ('features.poster_users', 'jellyfin', lambda x: [s.strip() for s in x.split(',')]),
    'EMBY_POSTER_USERS': ('features.poster_users', 'emby', lambda x: [s.strip() for s in x.split(',')]),
    'POSTER_DISPLAY_MODE': ('features.poster_display', 'mode', str),
    'PREFERRED_POSTER_USER': ('features.poster_display.preferred_user', 'username', str),
    'PREFERRED_POSTER_SERVICE': ('features.poster_display.preferred_user', 'service', str),

    # Plex ENV
    'PLEX_URL': ('plex', 'url', str),
    'PLEX_TOKEN': ('plex', 'token', str),
    'PLEX_MOVIE_LIBRARIES': ('plex', 'movie_libraries', lambda x: [s.strip() for s in x.split(',')]),

    # Jellyfin ENV
    'JELLYFIN_URL': ('jellyfin', 'url', str),
    'JELLYFIN_API_KEY': ('jellyfin', 'api_key', str),
    'JELLYFIN_USER_ID': ('jellyfin', 'user_id', str),

    # Emby ENV
    'EMBY_URL': ('emby', 'url', str),
    'EMBY_API_KEY': ('emby', 'api_key', str),
    'EMBY_USER_ID': ('emby', 'user_id', str),

    # Overseerr/Jellyseerr ENV
    'OVERSEERR_URL': ('overseerr', 'url', str),
    'OVERSEERR_API_KEY': ('overseerr', 'api_key', str),
    'JELLYSEERR_URL': ('jellyseerr', 'url', str),
    'JELLYSEERR_API_KEY': ('jellyseerr', 'api_key', str),

    # Ombi ENV
    'OMBI_URL': ('ombi', 'url', str),
    'OMBI_API_KEY': ('ombi', 'api_key', str),

    # Request Services ENV
    'REQUEST_SERVICE_DEFAULT': ('request_services', 'default', str),
    'REQUEST_SERVICE_PLEX': ('request_services', 'plex_override', str),
    'REQUEST_SERVICE_JELLYFIN': ('request_services', 'jellyfin_override', str),
    'REQUEST_SERVICE_EMBY': ('request_services', 'emby_override', str),

    # Feature flags
    'USE_LINKS': ('features', 'use_links', lambda x: x.upper() == 'TRUE'),
    'USE_FILTER': ('features', 'use_filter', lambda x: x.upper() == 'TRUE'),
    'USE_WATCH_BUTTON': ('features', 'use_watch_button', lambda x: x.upper() == 'TRUE'),
    'USE_NEXT_BUTTON': ('features', 'use_next_button', lambda x: x.upper() == 'TRUE'),
    'ENABLE_MOBILE_TRUNCATION': ('features', 'mobile_truncation', lambda x: x.upper() == 'TRUE'),
    'ENABLE_MOVIE_LOGOS': ('features', 'enable_movie_logos', lambda x: x.upper() == 'TRUE'),
    'LOAD_MOVIE_ON_START': ('features', 'load_movie_on_start', lambda x: x.upper() == 'TRUE'),
    'LOGIN_BACKDROP_ENABLED': ('features.login_backdrop', 'enabled', lambda x: x.upper() == 'TRUE'),
    # AppleTV ENV
    'APPLE_TV_ID': ('clients.apple_tv', 'id', str),

    # Dynamic TV Configuration ENV
    'TV_(.+)_TYPE': ('clients.tvs.instances.$1', 'type', str),
    'TV_(.+)_IP': ('clients.tvs.instances.$1', 'ip', str),
    'TV_(.+)_MAC': ('clients.tvs.instances.$1', 'mac', str),

    # TMDB
    'TMDB_API_KEY': ('tmdb', 'api_key', str),

    # Trakt
    'TRAKT_CLIENT_ID': ('trakt', 'client_id', str),
    'TRAKT_CLIENT_SECRET': ('trakt', 'client_secret', str),
    'TRAKT_ACCESS_TOKEN': ('trakt', 'access_token', str),
    'TRAKT_REFRESH_TOKEN': ('trakt', 'refresh_token', str),

    # Settings
    'DISABLE_SETTINGS': ('system', 'disable_settings', lambda x: x.upper() == 'TRUE'),
}

AUTH_ENV_MAPPINGS = {
    'AUTH_ENABLED': ('auth', 'enabled', lambda x: x.upper() == 'TRUE'),
    'AUTH_SESSION_LIFETIME': ('auth', 'session_lifetime', int),
    'AUTH_PASSKEY_ENABLED': ('auth', 'passkey_enabled', lambda x: x.upper() == 'TRUE'),
    'AUTH_RELYING_PARTY_ID': ('auth', 'relying_party_id', str),
    'AUTH_RELYING_PARTY_ORIGIN': ('auth', 'relying_party_origin', str)
}
