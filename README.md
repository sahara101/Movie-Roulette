# Movie Roulette

Can't decide what to watch? Movie Roulette helps you pick random movies from your Plex and/or Jellyfin libraries, with features like cinema poster mode, service integrations, and device control.

[![Latest Release](https://img.shields.io/github/v/release/sahara101/Random-Plex-Movie)](https://github.com/sahara101/Random-Plex-Movie/releases)
[![GHCR Downloads](https://img.shields.io/github/downloads/sahara101/Random-Plex-Movie/total?label=GHCR%20Pulls)](https://github.com/sahara101/Random-Plex-Movie/pkgs/container/movie-roulette)

<div align="center">
  <table>
    <tr>
      <td align="center">
        <a href=".github/screenshots/main-interface.png">
          <img src=".github/screenshots/standard-mode.png" width="200" alt="Main Interface">
          <br>
          <sub>Main Interface</sub>
        </a>
      </td>
      <td align="center">
        <a href=".github/screenshots/poster-mode.png">
          <img src=".github/screenshots/poster-mode.png" width="200" alt="Poster Mode">
          <br>
          <sub>Cinema Poster</sub>
        </a>
      </td>
      <td align="center">
        <a href=".github/screenshots/homepage-mode-iframe.png">
          <img src=".github/screenshots/homepage-mode.png" width="200" alt="Homepage Mode">
          <br>
          <sub>Homepage Widget</sub>
        </a>
      </td>
    </tr>
  </table>
</div>

## Features

- 🎬 **Media Server Support**: Works with both Plex and Jellyfin
- 🎫 **Cinema Poster Mode**: Digital movie poster display with real-time progress
- 🔍 **Smart Discovery**: Filter by genre, year, and rating
- 📱 **PWA Support**: Install as app on mobile and desktop
- 🎮 **Device Control**: Power on Apple TV and LG TV devices
- 🔄 **Service Integration**: 
  - Trakt for watch status
  - Overseerr for requests
  - YouTube for trailers

## Quick Start

```yaml
services:
  movie-roulette:
    image: ghcr.io/sahara101/movie-roulette:latest
    container_name: movie-roulette
    ports:
      - "4000:4000"
    volumes:
      - ./movie_roulette_data:/app/data
    restart: unless-stopped
```

Visit `http://your-server:4000` and follow the setup wizard.

> **Note**: For device control (Apple TV/LG TV), use `network_mode: host` instead of port mapping.

## First Run

1. Automatically redirects to settings if no services configured
2. Set up at least one media server (Plex/Jellyfin)
3. Wait for initial cache building
4. Optional: Configure additional services (Trakt, Overseerr)

## Key Configuration

### Media Servers

#### Plex
- Server URL
- Token (OAuth available)
- Movie Libraries (auto-scan available)

#### Jellyfin
- Server URL
- API Key
- User ID

### Integrations
- TMDb (built-in key provided)
- Trakt (built-in app or custom credentials)
- Overseerr (optional, for requests)

### Devices
- Apple TV (auto-discovery available)
- LG TV (network scanning available)

See [sample-compose.yml](sample-compose.yml) for full configuration options.

## Features in Action

1. **Standard Mode**
   - Random movie selection
   - Filter options
   - Movie details and trailers
   - Cast/crew filmographies

2. **Cinema Poster Mode**
   - Real-time playback status
   - Now Playing display
   - Custom default text
   - Multiple user monitoring

3. **Homepage Mode**
   - Minimalist widget
   - Basic controls
   - Quick selection


## Setup

### UI vs ENV Configuration

Movie Roulette offers two ways to configure the application:

1. **Settings UI** (Recommended)
   - Easy-to-use interface at `/settings`
   - Auto-discovery features
   - Real-time validation
   - Visual configuration

2. **Environment Variables**
   - Override UI settings
   - Lock settings in UI
   - Container-level configuration
   - CI/CD friendly

> ⚠️ **Important**: When a setting is configured through ENV variables, it will:
> - Take precedence over UI settings
> - Show as "Set by environment variable" in UI
> - Be locked/disabled in settings interface

### Environment Variables

### Required (if using service)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `PLEX_URL` | Plex server URL | - | ✅ Settings with test |
| `PLEX_TOKEN` | Plex auth token | - | ✅ OAuth flow |
| `PLEX_MOVIE_LIBRARIES` | Movie library names | "Movies" | ✅ Library scanner |
| `JELLYFIN_URL` | Jellyfin server URL | - | ✅ Settings |
| `JELLYFIN_API_KEY` | Jellyfin API key | - | ✅ Auto setup |
| `JELLYFIN_USER_ID` | Jellyfin user ID | - | ✅ Auto setup |

### Optional Features
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `HOMEPAGE_MODE` | Homepage widget mode | FALSE | ✅ Settings |
| `TMDB_API_KEY` | Custom TMDb key | Built-in key | ✅ Settings |
| `OVERSEERR_URL` | Overseerr URL | - | ✅ Settings |
| `OVERSEERR_API_KEY` | Overseerr API key | - | ✅ Settings |

### Device Control (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `APPLE_TV_ID` | Apple TV identifier | - | ✅ Auto-discovery |
| `LGTV_IP` | LG TV IP address | - | ✅ Auto-discovery |
| `LGTV_MAC` | LG TV MAC address | - | ✅ Auto-discovery |

### Cinema Poster (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `TZ` | Poster timezone | UTC | ✅ Settings |
| `DEFAULT_POSTER_TEXT` | Default text | - | ✅ Settings |
| `PLEX_POSTER_USERS` | Plex users to monitor | - | ✅ User selector |
| `JELLYFIN_POSTER_USERS` | Jellyfin users to monitor | - | ✅ User selector |

### Custom Trakt (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `TRAKT_CLIENT_ID` | Custom Trakt app ID | Built-in app | ✅ Built-in auth |
| `TRAKT_CLIENT_SECRET` | Custom Trakt secret | Built-in app | ✅ Built-in auth |
| `TRAKT_ACCESS_TOKEN` | Custom access token | - | ✅ Built-in auth |
| `TRAKT_REFRESH_TOKEN` | Custom refresh token | - | ✅ Built-in auth |

## Support

If you find Movie Roulette useful, consider supporting development:

[![GitHub Sponsor](https://img.shields.io/github/sponsors/sahara101?label=Sponsor&logo=GitHub)](https://github.com/sponsors/sahara101)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Development-yellow?logo=ko-fi)](https://ko-fi.com/sahara101/donate)

[Add License Information]
