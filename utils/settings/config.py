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
        'homepage_mode': False,
        'timezone': 'UTC',
        'default_poster_text': '',
        'poster_users': {
            'plex': [],
            'jellyfin': []
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
    }
}

ENV_MAPPINGS = {
    # Homepage ENV
    'HOMEPAGE_MODE': ('features', 'homepage_mode', lambda x: x.upper() == 'TRUE'),
    'TZ': ('features', 'timezone', str),
    'DEFAULT_POSTER_TEXT': ('features', 'default_poster_text', str),
    'PLEX_POSTER_USERS': ('features.poster_users', 'plex', lambda x: [s.strip() for s in x.split(',')]),
    'JELLYFIN_POSTER_USERS': ('features.poster_users', 'jellyfin', lambda x: [s.strip() for s in x.split(',')]),
    'EMBY_POSTER_USERS': ('features.poster_users', 'emby', lambda x: [s.strip() for s in x.split(',')]),
    
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

    # AppleTV ENV
    'APPLE_TV_ID': ('clients.apple_tv', 'id', str),

    # Dynamic TV Configuration ENV
    'TV_(.+)_TYPE': ('clients.tvs.instances.$1', 'type', str),
    'TV_(.+)_IP': ('clients.tvs.instances.$1', 'ip', str),
    'TV_(.+)_MAC': ('clients.tvs.instances.$1', 'mac', str),

    # Feature flags
    'USE_LINKS': ('features', 'use_links', lambda x: x.upper() == 'TRUE'),
    'USE_FILTER': ('features', 'use_filter', lambda x: x.upper() == 'TRUE'),
    'USE_WATCH_BUTTON': ('features', 'use_watch_button', lambda x: x.upper() == 'TRUE'),
    'USE_NEXT_BUTTON': ('features', 'use_next_button', lambda x: x.upper() == 'TRUE'),
    
    # utils/settings/manager.pyTMDB
    'TMDB_API_KEY': ('tmdb', 'api_key', str),
    
    # Trakt
    'TRAKT_CLIENT_ID': ('trakt', 'client_id', str),
    'TRAKT_CLIENT_SECRET': ('trakt', 'client_secret', str),
    'TRAKT_ACCESS_TOKEN': ('trakt', 'access_token', str),
    'TRAKT_REFRESH_TOKEN': ('trakt', 'refresh_token', str),
}
