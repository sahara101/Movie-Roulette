# Movie Roulette for macOS

Native macOS application for Movie Roulette, a random movie picker for Plex and Jellyfin.

## Download

Download the latest version from the [Releases](https://github.com/sahara101/Movie-Roulette/releases/tag/v1.0-macos) page.

## Installation

1. Download the Movie-Roulette.dmg file
2. Open the DMG file
3. Drag Movie Roulette to your Applications folder
4. Right-click > Open (first time only)
5. Follow the setup instructions in the app

## Features

For a complete README check the [default-docker](https://github.com/sahara101/Movie-Roulette/tree/main) page:

> **Note**: The MacOS Version does not support ENV variables.

- Native macOS application
- Supports both Intel and Apple Silicon Macs
- Integration with Plex and Jellyfin
- Random movie selection with filters
- Movie poster display
- Playback control

## Building from Source

### Requirements
- Python 3.10 or higher
- pip
- virtualenv (recommended)

### Build Instructions

```bash
# Clone the repository
git clone https://github.com/yourusername/Movie-Roulette-MacOS.git
cd Movie-Roulette-MacOS

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Build the app
python setup.py py2app

# Sign the app (if you have a developer certificate)
codesign --force --deep --sign "YOUR_CERTIFICATE_ID" "dist/Movie Roulette.app"
