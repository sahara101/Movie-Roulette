def validate_plex(data):
    """Validate Plex settings"""
    if data.get('enabled'):
        required_fields = ['url', 'token']
        missing_fields = [field for field in required_fields 
                         if not data.get(field)]
        
        if missing_fields:
            raise ValueError(f"Missing required Plex fields: {', '.join(missing_fields)}")
    return True

def validate_jellyfin(data):
    """Validate Jellyfin settings"""
    # Only validate required fields if service is being enabled
    if 'enabled' in data and data['enabled']:
        required_fields = ['url', 'api_key', 'user_id']
        missing_fields = [field for field in required_fields 
                         if not (data.get(field) or settings.get('jellyfin', field))]
        
        if missing_fields:
            raise ValueError(f"Missing required Jellyfin fields: {', '.join(missing_fields)}")
    return True

def validate_emby(data):
    """Validate Emby settings"""
    if data.get('enabled'):
        # Only require the fields if using direct auth (not Connect)
        if not data.get('connect_enabled'):
            required_fields = ['url', 'api_key', 'user_id']
            missing_fields = [field for field in required_fields
                            if not data.get(field)]
            if missing_fields:
                raise ValueError(f"Missing required Emby fields: {', '.join(missing_fields)}")
        else:
            # When using Connect, we only require the URL initially
            if not data.get('url'):
                raise ValueError("Emby server URL is required")
    return True

def validate_overseerr(data):
    if data.get('enabled'):
        if not data.get('url') or not data.get('api_key'):
            raise ValueError("Overseerr URL and API key are required when enabled")
    return True

def validate_trakt(data):
    if data.get('enabled'):
        required = ['client_id', 'client_secret', 'access_token', 'refresh_token']
        if not all(data.get(key) for key in required):
            raise ValueError("All Trakt credentials are required when enabled")
    return True

def validate_clients(data):
    if data.get('apple_tv', {}).get('enabled'):
        if not data['apple_tv'].get('id'):
            raise ValueError("Apple TV ID is required when enabled")

    # Validate smart TVs
    if 'tvs' in data and 'instances' in data['tvs']:
        for tv_id, tv_config in data['tvs']['instances'].items():
            if tv_config.get('enabled'):
                required_fields = ['ip', 'mac', 'type']
                missing = [f for f in required_fields if not tv_config.get(f)]
                if missing:
                    raise ValueError(f"TV '{tv_id}': Missing required fields: {', '.join(missing)}")

                # Validate TV type
                if tv_config['type'] not in ['webos', 'tizen', 'android']:
                    raise ValueError(f"TV '{tv_id}': Invalid type '{tv_config['type']}'")
    return True

def validate_jellyseerr(data):
    """Validate Jellyseerr settings"""
    if data.get('enabled'):
        if not data.get('url') or not data.get('api_key'):
            raise ValueError("Jellyseerr URL and API key are required when enabled")

        # force_use is optional and boolean, no validation needed
        if 'force_use' in data and not isinstance(data['force_use'], bool):
            raise ValueError("force_use must be a boolean value")
    return True

VALIDATORS = {
    'plex': validate_plex,
    'jellyfin': validate_jellyfin,
    'emby': validate_emby,
    'overseerr': validate_overseerr,
    'trakt': validate_trakt,
    'clients': validate_clients,
    'jellyseerr': validate_jellyseerr
}
