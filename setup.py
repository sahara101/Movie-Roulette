from setuptools import setup
import os

def collect_static_files():
    static_files = []
    for root, dirs, files in os.walk('static'):
        for file in files:
            source = os.path.join(root, file)
            # Get the relative path from 'static' directory
            rel_dir = os.path.dirname(os.path.relpath(source, 'static'))
            # Construct the target directory path
            target_dir = os.path.join('static', rel_dir)
            static_files.append((target_dir, [source]))
    return static_files

APP = ['native_app.py']

# Collect all static files with their subdirectory structure
static_files = collect_static_files()

DATA_FILES = [
    ('web', ['web/index.html', 'web/settings.html', 'web/poster.html']),
] + static_files  # Add all static files with their proper paths

OPTIONS = {
    'argv_emulation': False,
    'arch': 'universal2',
    'packages': [
        'flask',
        'flask_socketio',
        'PyQt6',
        'requests',
        'eventlet',
        'plexapi',
        'configparser',
        'pyatv',
        'engineio',
        'socketio',
        'jinja2'
    ],
    'includes': ['jinja2.ext'],
    'iconfile': 'static/icons/icon.icns',
    'resources': ['static', 'web'],  # Add resources to include
    'plist': {
        'CFBundleName': 'Movie Roulette',
        'CFBundleDisplayName': 'Movie Roulette',
        'CFBundleIdentifier': 'com.movieroulette.app',
        'CFBundleVersion': "1.0.0",
        'CFBundleShortVersionString': "1.0.0",
        'LSMinimumSystemVersion': "10.10",
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,  # Support dark mode
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'NSAppleEventsUsageDescription': 'Movie Roulette uses Apple Events to communicate with media players.',
        'NSNetworkingUsageDescription': 'Movie Roulette requires network access to communicate with media servers.',
        'com.apple.security.cs.allow-jit': True,
        'com.apple.security.cs.allow-unsigned-executable-memory': True,
        'com.apple.security.cs.disable-library-validation': True,
        'com.apple.security.network.client': True,
        'com.apple.security.network.server': True,
    }
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
