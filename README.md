Forked from https://github.com/Akasiek/Random-Plex-Movie
I want to add it to docker and also to be able to start apple tv directly from it. 

# Random Plex Movie
Python App which chooses a random movie from your Plex Library. Also you can send a watch request to Plex Client with the chosen movie.
[![GitHub Release](https://img.shields.io/github/v/release/Akasiek/Random-Plex-Movie?include_prereleases&label=Release&style=flat-square)](https://github.com/Akasiek/Random-Plex-Movie/releases)
[![GitHub](https://img.shields.io/github/license/Akasiek/random-plex-movie?style=flat-square)](https://github.com/Akasiek/random-plex-movie/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/PlexAPI?label=PlexAPI&style=flat-square)](https://pypi.org/project/PlexAPI/4.5.2/)
[![PyPI](https://img.shields.io/pypi/v/Eel?label=Eel&style=flat-square)](https://pypi.org/project/Eel/)

![alt text](https://i.imgur.com/CKplHDk.jpg "Example")

# Needed stuff

- Python 3
- Pip
- Google Chrome (You can access the app by any other browser on `localhost:4000`. But Chrome uses app module and it works out of the box)

# Installation

1. Clone repo with this command:

```
git clone https://github.com/Akasiek/Random-Plex-Movie.git
cd Random-Plex-Movie
```
    

2. Install required libraries:

    Windows 

    `pip install -r requirements.txt`

    MacOS and Linux

    `pip3 install -r requirements.txt`

3. Change config file with your Plex credentials. 

    ![alt text](https://i.imgur.com/Y7WjVLb.jpg "Third step of the installation")

4. Run Python file with this command

    Windows (CMD)

    `py randomPlexMovie.py`

    MacOS and Linux

    `python3 randomPlexMovie.py`

    This will start local web server on port 4000 and open Chrome App. If the port is colliding with something, you can change it in this line:

    ![alt text](https://i.imgur.com/ABLhaJh.jpg "Fourth step of the installation")

    After closing the app window, the program will stop running. You can change it by deleting argument "close_callback" in this line:

    ![alt text](https://i.imgur.com/kcaZZgR.jpg "Fourth step of the installation")
    
    If you run into the `OSError: Can't find Google Chrome/Chromium installation` error, in the config file, change useCustomPath to `True` and specify the file path leading to your Chrome installation directory by changing `path`.
    
    ![alt text](https://i.imgur.com/wCoEHhh.png "Fourth step of the installation")

***

## Plans for the future






