Forked from https://github.com/Akasiek/Random-Plex-Movie

# Movie Roulette
Docker container which chooses a random movie from your Plex and/or Jellyfin movie library. 

# Tested Players 
## Plex
- Apple TV - with turn on function
- Plex HTPC MacOS Client
- iPhone
- Plex for LGTV (WebOS) - with turn on function
- Xiaomi MI TV Box S (Android)
## Jellyfin
- All cast capable devices

# Functions
- Fetch Random unwatched movies from Plex and/or Jellyfin server.
- Filter by genre, year, and/or rating. Genre and years display only existing movies.
- See movie info.
- URLs to TMDB, Trakt and IMDB.
- Trailers on Youtube.
- Play movie on above tested players.
- Turn on Apple TV and LGTV ((webOS) directly in Plex or Jellyfin app).
- PWA support.
- Seamless switch between the two services. 

<img width="1728" alt="image" src="https://github.com/user-attachments/assets/7181ebc1-b909-4e7a-b7e0-a30472515c82">
<img width="1727" alt="image" src="https://github.com/user-attachments/assets/ff5b33f4-d632-41e3-a4a2-1dc33ef2eff6">

# DISCLAIMER
I am no programmer! Code is expanded with help of ChatGPT. Feel free to modify the code as you please. Also open to criticism ;)

# docker-compose.yml
How to get the Plex token: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

How to get the Jellyfin API: Administration - Dashboard - API Keys - +

How to get the Jellyfin UserID: Profile - check the URL - copy the userId string


```
services:
  plex-random-movie:
    image: ghcr.io/sahara101/random-plex-movie:latest

    environment:
      PLEX_URL: "Your-Plex-URL" #FQDN preferred. Do not use if you only want Jellyfin function.
      PLEX_TOKEN: "TOKEN" #Do not use if you only want Jellyfin function.
      MOVIES_LIBRARY_NAME: 'Filme' #Option for Plex. Default 'Movies'. Used for IMDB, Trakt and TMDB links. Do not use if you only want Jellyfin function.
      JELLYFIN_URL: "Your-Jellyfin-URL" #Do not use if you only want Plex function.
      JELLYFIN_API_KEY: "API" #Do not use if you only want Plex function.
      JELLYFIN_USER_ID: "USERID" #Do not use if you only want Plex function.
      APPLE_TV_ID: "ID" #Optional
      LGTV_IP: "IP" #Optional
      LGTV_MAC: "MAC_Address" #Optional
      
    network_mode: host
    restart: unless-stopped
```
If you do not have an Apple TV you can  also change network host mode to use other external port.

Default container port is 4000

The power button displays the devices dynamically, meaning you HAVE to add the ```APPLE_TV_ID``` ENV in order to see the corresponding button and both ```LGTV_IP``` and ```LGTV_MAC``` for LG.

A switch between services is displayed if both ```Jellyfin``` and ```Plex``` are configured. Last used service will be remembered. 

# PWA Support
Since version 1.3.1 you can 'install' as a webapp. On iOS go to share - add to homescreen. On Mac go to Safari File - add to dock. In Chrome you will see an install button.

![image](https://github.com/user-attachments/assets/ffb29414-8886-4376-952c-2949af401b68)

# First Use 
!important! - Your client devices and plex need to be in the same network.
## Plex Client Config

Navigate to settings and set 'Advertise as player' to 'On'

## Plex Server Config
Navigate to settings - network and activate 'Enable local network discovery (GDM)'

# Apple TV
## Get the Apple TV ID 

First start the container without adding the ID ENV since you do not have it yet.

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
# LGTV (WebOS
Get the TV IP and MAC and set them up in the ENV. You can see both in the TV settings. If you want to copy the MAC just ping the TV followed by the linux command ```ip neigh show```

Press the ```TURN ON DEVICE``` button and select your ```LGTV (webOS)```. A magic packet will be sent and the TV will turn on. Accept the new connection. This will store the connection details in the container. 

# Troubleshooting
## Plex
Issue: Pressing the WATCH button does not show any client.

- Plex: Check above Plex and Plex client config. Restart your client.
- If Plex API does not find any players, neither will this App. You can get a list of active clients using:
```
curl -X GET "http://PLEXIP:32400/clients?X-Plex-Token=PLEXTOKEN"
```
- (Apple TV) Plex Apple TV is buggy and often it forgets it has the ```Advertise as player``` option active. You will need to deactivate it, force close the app, start the app and activate the option again, restart Plex app.
- (Apple TV) You will need to deactivate the option, logoff and force close the app. Start the app, skip login and activate the option. Then you can login back. 
## Jellfin
- Jellyfin: The client you expect does not support cast.

# General
Issue: Pressing the WATCH button does nothing. 

- Check the docker logs, if you get an access denied error, check your Plex Token, it might've changed.
- Inspect the page. Collect the errors and open an issue.

Issue: Apple TV does not turn on

- You need to re-pair. This needs to be done each time you recreate the container.

Issue: Browser does not load the poster and background.

- You are probably using RPM with a reverse proxy URL but configured the container with the Plex/Jellyin IP. Change the ENV to Plex/Jellyfin FQDN.
