Forked from https://github.com/Akasiek/Random-Plex-Movie

# Random Plex Movie
Docker container which chooses a random movie from your Plex Library. 

# Tested Players 
- Apple TV - with turn on function
- Plex HTPC MacOS Client
- iPhone
- Plex for LGTV (WebOS)
- Xiaomi MI TV Box S

# Functions
- Fetch Random unwatched movies from Plex server
- See movie info
- URLs to TMDB, Trakt and IMDB
- Trailers on Youtube
- Play movie on above tested players
- Turn on Apple TV

<img width="1403" alt="image" src="https://github.com/user-attachments/assets/75057458-4b3a-4f91-9da6-9efb748ce28e">
<img width="1358" alt="image" src="https://github.com/user-attachments/assets/27961635-439c-45a2-8e61-6654ca5f15de">


# DISCLAIMER
I am no programmer! Code is expanded with help of ChatGPT. Feel free to modify the code as you please. Also open to criticism ;)


# docker-compose.yml
How to get the token: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

```
version: '3.8'

services:
  plex-random-movie:
    image: ghcr.io/sahara101/random-plex-movie:latest

    environment:
      PLEX_URL: "http://IP:32400"
      PLEX_TOKEN: "TOKEN"
      MOVIES_LIBRARY_NAME: 'Filme' #Default 'Movies'. Used for IMDB, Trakt and TMDB links. 
      APPLE_TV_ID: "ID"
      
    network_mode: host
    restart: unless-stopped
```
If you do not have an Apple TV you can  also change the port.

Default container port is 4000

# First Use 
!important! - Your client devices and plex need to be in the same network.
## Plex Client Config

Navigate to settings and set 'Advertise as player' to 'On'

## Plex Server Config
Navigate to settings - network and activate 'Enable local network discovery (GDM)'

#Apple TV
## Get the Apple TV ID 

First start the container without adding an ID since you do not have it yet.

```
docker exec -ti random-plex-movie /bin/sh
atvremote scan
```
Note down the Apple TV Identifier, usually the first long one: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Add it to the container ENV and restart it with docker-compose up -d

## Pair with Apple TV
You will see a PIN on the Apple TV which you need to type in the docker sh

```
docker exec -ti random-plex-movie /bin/sh
atvremote --id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx --protocol companion pair
Enter PIN on screen: 
Pairing seems to have succeeded, yey!
```


# Troubleshooting
Issue: Pressing the WATCH button does not show any client.

- Check above Plex and Plex client config. Restart your client.
- If Plex API does not find any players, neither will this App. You can get a list of active clients using:
```
curl -X GET "http://PLEXIP:32400/clients?X-Plex-Token=PLEXTOKEN"
```
- (Only Apple TV) Plex Apple TV is buggy and often it forgets it has the option active. You will need to deactivate the option, force close the app, start the app and activate the option again, restart Plex app.
- (Only Apple TV) You will need to deactivate the option, logoff and force close the app. Start the app, skip login and activate the option. Then you can login back. 

Issue: Pressing the WATCH button does nothing. 

- Check the docker logs, if you get an access denied error, check your Plex Token, it might've changed.

Issue: Apple TV does not turn on

- You need to re-pair. This needs to be done each time you recreate the container. 



