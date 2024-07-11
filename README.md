Forked from https://github.com/Akasiek/Random-Plex-Movie

I want to add it to docker and also to be able to start Apple TV directly from it. 

# Random Plex Movie
Docker container which chooses a random movie from your Plex Library. You can send a watch request to Plex Client with the chosen movie. You can also turn on your Apple TV and each chosen movie has links to TMDB, Trakt and IMDB.

<img width="1307" alt="image" src="https://github.com/sahara101/Random-Plex-Movie/assets/22507692/1288b47e-a0f2-48af-93a9-e41f7a6f1bc8">

# DISCLAIMER
I am no programmer! Code is expanded with help of ChatGPT. Feel free to modify the code as you please. Also open to criticism ;)


# Docker-compose

```
version: '3.8'

services:
  plex-random-movie:
    image: ghcr.io/sahara101/random-plex-movie:latest

    environment:
      PLEX_URL: "http://IP:32400"
      PLEX_TOKEN: "TOKEN"
      MOVIES_LIBRARY_NAME: 'Filme' #Default 'Movies'. Used for TMDB, Trakt and TMDB links. 
      APPLE_TV_ID: "ID"
      
    network_mode: host
    restart: unless-stopped
```

# First Use 
## Get the Apple TV ID

First start the docker without adding an ID since you do not have it yet.

```
docker exec -ti random-plex-movie /bin/sh
atvremote scan
```
Note down the Apple TV Identifier, usually the first long one: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Add it to the docker ENV and restart the container with docker-compose up -d

## Pair with Apple TV
You will see a PIN on the Apple TV which you need to type in the docker sh

```
docker exec -ti random-plex-movie /bin/sh
atvremote --id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx --protocol companion pair
Enter PIN on screen: 
Pairing seems to have succeeded, yey!
```

# Plex Client Config

Navigate to Settings and set 'Advertise as player' to 'On'

# Troubleshooting
Issue: Pressing the WATCH button does not show the Apple TV.

Solution 1: Plex Apple TV is buggy and often it forgets it has the option active. You will need to deactivate the option, force close the app, start the app and activate the option again, restart Plex app. 

Solution 2: You will need to deactivate the option, logoff and force close the app. Start the app, skip login and activate the option. Then you can login back. 

Issue: Pressing the WATCH button does nothing. 

Solution: Check the docker logs, if you get an access denied error, check your Plex Token, it might've changed.

Issue: Apple TV does not turn on

Solution: You need to re-pair. This needs to be done each time you recreate the docker. 



