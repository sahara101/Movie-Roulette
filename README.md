Forked from https://github.com/Akasiek/Random-Plex-Movie

I want to add it to docker and also to be able to start apple tv directly from it. 

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

# First Use - get the Apple TV ID

First start the docker without adding an ID since you do not have it yet.

```
docker exec -ti random-plex-movie /bin/sh
```
Note down the Apple TV Identifier, usually the first long one: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Add it to the docker ENV and docker compose up -d

#First Use - Pair with Apple TV

TBC





