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
    if data.get('lg_tv', {}).get('enabled'):
        if not all([data['lg_tv'].get('ip'), data['lg_tv'].get('mac')]):
            raise ValueError("LG TV IP and MAC address are required when enabled")
    if data.get('apple_tv', {}).get('enabled'):
        if not data['apple_tv'].get('id'):
            raise ValueError("Apple TV ID is required when enabled")
    return True

VALIDATORS = {
    'plex': validate_plex,
    'jellyfin': validate_jellyfin,
    'overseerr': validate_overseerr,
    'trakt': validate_trakt,
    'clients': validate_clients
}
