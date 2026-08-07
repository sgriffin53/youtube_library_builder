# youtube_library_builder
Builds an offline library of your favourite YouTube songs automatically by tracking what you watch and automatically downloading your most watched songs via Soulseek.

The server can be run on either a VPS or your local PC.

If running on a VPS, make sure the following files are copied to the VPS:

server.py
config.txt
music.db

# Installation

Download the source code and extract it into a project folder

Download the song database from https://metabrainz.org/datasets/postgres-dumps#musicbrainz

- Click JSON data dumps
- Sign up or proceed without signing up if eligible
- Click MusicBrainz JSON data dumps
- Click 20260801-001001/
- Click release.tar.xz
- Extract the 'release' file into the project folder

To install dependencies:

Run:

```python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

To install the extension:

Go to about:debugging in Firefox and click 'Add Temporary Extension' and click the manifest.json file.
The extension will now be loaded.

To build the database:

Run:

```python build_database.py```

This may take a long time (over an hour) and should produce an 11GB music.db file.

Edit the config with your Soulseek username, preferred save directory, and server IP, click_threshold, and day_threshold.

Click threshold and day threshold are how many times you have to click a video in how many days for it to download the song.

For example, click_threshold=3 and day_threshold=5 will download any video's songs that you click 3 times within 5 days.

If you're running the server on a VPS, set the server IP to your VPS's IP. If you're running the server locally, set it to 127.0.0.1.

Run (either on your server or locally):

```python server.py```

Now the server will listen for requests from the extension. If you watch a video 3 times in 3 days, the server will download the song from Soulseek and save it to your save directory.

If you're running the server on a VPS and want it to automatically sync the songs to your local PC, create a scheduled task with this command (WSL must be installed if using Windows):

@echo off
wsl rsync -av --remove-source-files [user]@[vps ip]:[save dir] [local dir (replace C:\ with /mnt/c/ and use forward slashes]
