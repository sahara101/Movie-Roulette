import os

from utils.settings import settings


HARDCODED_CLIENT_ID = '2203f1d6e97f5f8fcbfc3dcd5a6942ad03559831695939a01f9c44a1c685c4d1'
HARDCODED_CLIENT_SECRET = '3e5c2b9163264d8e9b50b8727c827b49a5ea8cc6cf0331bca931a697c243f508'


def get_trakt_client_id():
    """Return the configured Trakt client ID, falling back to the built-in app."""
    return (
        os.getenv('TRAKT_CLIENT_ID')
        or settings.get('trakt', {}).get('client_id')
        or HARDCODED_CLIENT_ID
    )


def get_trakt_client_secret():
    """Return the server-side secret required by Trakt's device and refresh flows.

    Trakt has no public-client mode: the device, authorization-code and refresh
    grants all require a secret. The built-in secret is therefore only usable
    together with the built-in client ID; a custom client ID must bring its own.
    """
    configured = (
        os.getenv('TRAKT_CLIENT_SECRET')
        or settings.get('trakt', {}).get('client_secret')
    )
    if configured:
        return configured
    if get_trakt_client_id() == HARDCODED_CLIENT_ID:
        return HARDCODED_CLIENT_SECRET
    return None
