# Movie Roulette

Can't decide what to watch? Movie Roulette helps you pick random movies from your Plex and/or Jellyfin libraries, with features like cinema poster mode, service integrations, and device control.

[![Release](https://img.shields.io/badge/release-v4.0-blue)]()
[![Docker Pulls](https://img.shields.io/docker/pulls/sahara101/movie-roulette)](https://hub.docker.com/r/sahara101/movie-roulette)
[![GHCR Downloads](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fipitio.github.io%2Fbackage%2Fsahara101%2FMovie-Roulette%2Fmovie-roulette.json&query=%24.downloads&label=GHCR%20Downloads)](https://github.com/sahara101/Movie-Roulette/pkgs/container/movie-roulette)
[![GitHub Sponsor](https://img.shields.io/github/sponsors/sahara101?label=Sponsor&logo=GitHub)](https://github.com/sponsors/sahara101)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Development-yellow?logo=ko-fi)](https://ko-fi.com/sahara101/donate)

## Main Interface
<div align="center">
  <a href=".github/screenshots/main-interface.png">
    <img src=".github/screenshots/main-interface.png" width="800" alt="Main Interface">
  </a>
</div>

## Additional Views
- [Cinema Poster Mode](.github/screenshots/poster-mode.png)
- [Homepage Widget](.github/screenshots/homepage-mode-iframe.png)
- [PWA on Mobile](.github/screenshots/pwa-interface-mobile.png)
- [Login Page](.github/screenshots/login-page.png)
- [Cache Admin](.github/screenshots/cache-admin.png)
- [Test Theme](.github/screenshots/test-theme.png)

## Rich Information
- [Cast & Crew Details](.github/screenshots/cast-example.png)
- [Movie Details](.github/screenshots/movie-details-example.png)
- [Filmography View](.github/screenshots/filmography-example.png)
- [Collection View](.github/screenshots/collection-view.png)

## Star History

<a href="https://www.star-history.com/#sahara101/Movie-Roulette&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=sahara101/Movie-Roulette&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=sahara101/Movie-Roulette&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=sahara101/Movie-Roulette&type=Date" />
 </picture>
</a>

## Contributing

This project was extended with the assistance of AI tools. The core functionality is based on [Random-Plex-Movie](https://github.com/Akasiek/Random-Plex-Movie) and has been expanded with additional features and integrations.

## Features

- 🎬 **Media Server Support**: Get random movies with Plex, Jellyfin, Emby
- 🎫 **Cinema Poster Mode**: Digital movie poster display with real-time progress
- 🔍 **Smart Discovery**: Filter by watch status, genre, year, and rating
- 📱 **PWA Support**: Install as app on mobile and desktop
- 🎮 **Device Control**: Power on Apple TV and TV devices directly in the selected service application
- 🔄 **Service Integration**: 
  - Trakt for global watch status
  - Overseerr/Jellyseerr/Ombi for requests
  - YouTube for trailers
 
> **Note**: Ensure your client devices and Plex server are on the same network. On the first run, a Plex cache file will be created to enhance movie loading speeds.
 
## Tested Players
### Plex
- Apple TV - with turn on function and app start
- Plex HTPC MacOS Client
- iPhone
- Plex for LGTV (WebOS) - with turn on function and app start
- Xiaomi MI TV Box S (Android)
### Jellyfin
- All cast capable devices
- Apple TV - with turn on function and app start
- Jellyfin for LGTV (WebOS) - with turn on function and app start
### Emby
- All cast capable devices
- Apple TV - with turn on function and app start
- Emby for LGTV (WebOS) - with turn on function and app start

## Quick Start

## Container Images

| Registry | Architecture | Version | Image Path |
|----------|--------------|----------|------------|
| Docker Hub | AMD64 | Latest | `sahara101/movie-roulette:latest` |
| Docker Hub | ARM64/ARMv7 | Latest | `sahara101/movie-roulette:arm-latest` |
| GHCR | AMD64 | Latest | `ghcr.io/sahara101/movie-roulette:latest` |
| GHCR | ARM64/ARMv7 | Latest | `ghcr.io/sahara101/movie-roulette:arm-latest` |

Instead of latest you can also use the version number. 

```yaml
services:
  movie-roulette:
    image: #See above
    container_name: movie-roulette
    ports:
      - "4000:4000"
    volumes:
      - ./movie_roulette_data:/app/data
    restart: unless-stopped
```

Visit `http://your-server:4000` and configure your services.

> **Note**: For device control (Apple TV/LG TV), use `network_mode: host` instead of port mapping.

## Native Clients

For MacOS non-docker application please check [here](https://github.com/sahara101/Movie-Roulette/tree/macOS)

## First Run

1. Automatically redirects to settings if no services are configured
2. Set up at least one media server (Plex/Jellyfin/Emby)
3. Optional: Enable Auth
4. Automatic redirection to admin user setup page
5. Wait for initial cache building for Plex
6. Optional: Configure additional services (Trakt, Overseerr, etc.)

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

#### Emby
- Server URL
- API Key
- User ID

### Integrations
- TMDb (built-in key provided or custom API)
- Trakt (built-in app or custom credentials)
- Overseerr/Jellyseerr/Ombi (optional, for requests)

### Devices
- Apple TV (auto-discovery available)
- LG WebOS, Samusng Tizen (pre-alpha), Android Sony (pre-alpha) (network scanning available)

See [sample-compose.yml](sample-compose.yml) for full configuration options.

## Features in Action

1. **Standard Mode**
   - Random movie selection
   - Filter options
   - Search movies
   - Movie details and trailers
   - Cast/crew filmographies

2. **Cinema Poster Mode**
   - Real-time playback status
   - Now Playing display
   - Screensaver Mode
   - Custom default text in Default Poster Mode
   - Multiple user monitoring

3. **Homepage Mode**
   - Minimalist widget

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
| `EMBY_URL` | Emby server URL | - | ✅ Settings |
| `EMBY_API_KEY` | Emby API key | - | ✅ Settings |
| `EMBY_USER_ID` | Emby user ID | - | ✅ Settings |

### Optional, but highly recommended
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `FLASK_SECRET_KEY` | Securely sign the session cookie | Random on startup | ❌ Automatic |

### Optional Features
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `AUTH_ENABLED` | Authentication | FALSE | ✅ Settings |
| `AUTH_SESSION_LIFETIME` | Auth session lifetime in s | 86400 | ✅ Settings |
| `ENABLE_MOVIE_LOGOS` | Show TMDB title logos | FALSE | ✅ Settings |
| `LOAD_MOVIE_ON_START` | Directly show a movie or show a button | TRUE | ✅ Settings |
| `DISABLE_SETTINGS` | Lock Settings page | FALSE | - |
| `HOMEPAGE_MODE` | Homepage widget mode | FALSE | ✅ Settings |
| `TMDB_API_KEY` | Custom TMDb key | Built-in key | ✅ Settings |
| `USE_LINKS` | Show links buttons | TRUE | ✅ Settings |
| `USE_FILTER` | Show filter button | TRUE | ✅ Settings |
| `USE_WATCH_BUTTON` | Show Watch button | TRUE | ✅ Settings |
| `USE_NEXT_BUTTON` | Show next button | TRUE | ✅ Settings |
| `ENABLE_MOBILE_TRUNCATION` | Choose if descriptions are truncated on mobile | FALSE | ✅ Settings |

### Request Service (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `OVERSEERR_URL` | Overseerr URL | - | ✅ Settings |
| `OVERSEERR_API_KEY` | Overseerr API key | - | ✅ Settings |
| `JELLYSEERR_URL` | Jellyseerr URL | - | ✅ Settings |
| `JELLYSEERR_API_KEY` | Jellyseerr API key | - | ✅ Settings |
| `OMBI_URL` | Ombi server URL | - | ✅ Settings |
| `OMBI_API_KEY` | Ombi API key | - | ✅ Settings |
| `REQUEST_SERVICE_DEFAULT` | Default request service | "auto" | ✅ Settings |
| `REQUEST_SERVICE_PLEX` | Plex request service override | "auto" | ✅ Settings |
| `REQUEST_SERVICE_JELLYFIN` | Jellyfin request service override | "auto" | ✅ Settings |
| `REQUEST_SERVICE_EMBY` | Emby request service override | "auto" | ✅ Settings |

### Device Control (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `APPLE_TV_ID` | Apple TV identifier | - | ✅ Auto-discovery |
| `TV_<NAME>_TYPE` | TV type (`webos`, `tizen`, `android`) | - | ✅ Auto-discovery |
| `TV_<NAME>_IP` | TV IP address | - | ✅ Auto-discovery |
| `TV_<NAME>_MAC` | TV MAC address | - | ✅ Auto-discovery |
> Note: Replace <NAME> with your chosen TV identifier (e.g., TV_LIVING_ROOM_TYPE: "webos"). Only use letters, numbers, and underscores.

### Cinema Poster (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `TZ` | Poster timezone | UTC | ✅ Settings |
| `DEFAULT_POSTER_TEXT` | Default text | - | ✅ Settings |
| `PLEX_POSTER_USERS` | Plex users to monitor | - | ✅ User selector |
| `JELLYFIN_POSTER_USERS` | Jellyfin users to monitor | - | ✅ User selector |
| `EMBY_POSTER_USERS` | Emby users to monitor | - | ✅ User selector |
| `POSTER_MODE` | Type of poster to show when no movie playing | Default | ✅ Settings |
| `POSTER_DISPLAY_MODE` | When playing a movie, what to show first | first_active| ✅ Settings |
| `SCREENSAVER_INTERVAL` | How often to update the screensaver | 300 | ✅ Settings |
| `PREFERRED_POSTER_USER` | Define an user that should always be visible | - | ✅ User selector |
| `PREFERRED_POSTER_SERVICE` | To which service te above user belongs to | - | ❌ Automatic |
> Note: `POSTER_MODE` options: `default` or `screensaver` ; 
> `POSTER_DISPLAY_MODE` options: `first_active` or `preferred_user`

### Custom Trakt (Optional)
| Variable | Description | Default | UI Alternative |
|----------|-------------|---------|----------------|
| `TRAKT_CLIENT_ID` | Custom Trakt app ID | Built-in app | ✅ Built-in auth |
| `TRAKT_CLIENT_SECRET` | Custom Trakt secret | Built-in app | ✅ Built-in auth |
| `TRAKT_ACCESS_TOKEN` | Custom access token | - | ✅ Built-in auth |
| `TRAKT_REFRESH_TOKEN` | Custom refresh token | - | ✅ Built-in auth |

## Plex Configuration
### Plex Client

Navigate to settings and enable Advertise as Player.

### Plex Server

Go to settings → Network and activate Enable Local Network Discovery (GDM).

## Advanced Configuration

### Apple TV Setup with ENV
1. Get Apple TV ID:
   ```
   docker exec -ti movie-roulette /bin/sh
   atvremote scan
   ```

2. Note the Apple TV Identifier (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
3. Add to environment:
  environment:
  APPLE_TV_ID: "your-apple-tv-identifier"

4. Pair with Apple TV:
   ```
   docker exec -ti movie-roulette /bin/sh
   atvremote --id YOUR-ID --protocol companion pair
   ```
5. Enter PIN shown on Apple TV

### TV Device Setup
Movie Roulette supports multiple TV instances using a dynamic naming pattern. Each TV is configured with a name and its required parameters. The application supports multiple TV platforms:

Supported TV Types:
- `webos`: LG WebOS TVs
- `tizen`: Samsung Tizen TVs
- `android`: Android-based TVs

Configuration example:
```yaml
environment:
  # Example for LG WebOS TV in living room
  TV_LIVING_ROOM_TYPE: "webos"
  TV_LIVING_ROOM_IP: "192.168.1.100"
  TV_LIVING_ROOM_MAC: "AA:BB:CC:DD:EE:FF"
  
  # Example for Samsung TV in bedroom
  TV_BEDROOM_TYPE: "tizen"
  TV_BEDROOM_IP: "192.168.1.101"
  TV_BEDROOM_MAC: "11:22:33:44:55:66"
  
  # Example for Android TV in kitchen
  TV_KITCHEN_TYPE: "android"
  TV_KITCHEN_IP: "192.168.1.102"
  TV_KITCHEN_MAC: "CC:DD:EE:FF:00:11"
```

### Homepage Integration
Add to <a href="http://gethomepage.dev" target="_blank" rel="noopener noreferrer">Homepage</a>'s services.yaml:
```
- Movie Roulette:
    - Movie Roulette:
        icon: /images/icons/movie-roulette.png
        widget:
          type: iframe
          src: "http://your-server:4000"
          classes: h-96 w-full
          referrerPolicy: same-origin
```

## Troubleshooting

### Plex
Issue: Pressing the "WATCH" button doesn’t show any client.

- Verify Advertise as Player is enabled on the Plex client and restart the app.
- Check for active clients using:
```curl -X GET "http://PLEXIP:32400/clients?X-Plex-Token=PLEXTOKEN"```
- (Apple TV) Disable and re-enable Advertise as Player, force close the app, and restart.
  
Issue: Apple TV doesn’t turn on.

- You need to re-pair the Apple TV after recreating the container.
  
Issue: Browser doesn’t load the poster or background.

- Use the FQDN (Fully Qualified Domain Name) for Plex/Jellyfin in the environment variables/settings instead of the IP address.

## Support

If you find Movie Roulette useful, consider supporting development:

[![GitHub Sponsor](https://img.shields.io/github/sponsors/sahara101?label=Sponsor&logo=GitHub)](https://github.com/sponsors/sahara101)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Development-yellow?logo=ko-fi)](https://ko-fi.com/sahara101/donate)
