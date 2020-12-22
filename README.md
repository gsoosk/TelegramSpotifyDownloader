# TelegramSpotifyDownloader

## What is it?
This is a simple bot to download songs from YouTube in an MP3 format by using Spotify's HTTP link.

<img src="https://github.com/gsoosk/TelegramSpotifyDownloader/blob/master/demo.png" width="450" />

## How to run?

At first, you should add your bot `TOKEN` to the config file.

Then install requirements:
```
pip install requirements
sudo apt install ffmpeg
npm install -g spotify-dl
```

Then you can run program with this command:
```
python main.py
```
## Authentication
For a simple authentication you can enable it in config file by setting `ENABLE` to `true`. You also should set `PASSWORD` which users can authentican with. Bot uses config file to save users also. 

## Downloader
This bot can use one of bellow spotify downloaders to download the song/album/playlist. You should select one of them in the config file. 
* [SpotDL(Python)](https://github.com/spotDL/spotify-downloader)
* [SpotifyDL(JS)](https://github.com/SwapnilSoni1999/spotify-dl)

_NOTE: spotdl has released a new version(3) which has so many bugs and is unreliable. Therefore, I recommend spotify-dl._

## TODO
- [ ] Update Dockerfile
- [ ] Add Progress Bar
