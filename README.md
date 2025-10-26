# cunty-scrobbler ✨💅

serving pure cunt for your last.fm needs since today. period.

## it eats, it slays, it scrobbles 💋

- scrobble tracks like the bad bitch you are
- serve entire albums in one go
- batch that shit because who has time?
- hot pink aesthetic that will make the girls gag
- no messy .env files because we're not basic

## how to get this shit on your computer

1. grab the latest release from [releases](https://github.com/jafarnz/swyft/releases)
2. extract wherever tf you want
3. double click and get your life
4. mac girlies: the app now ships as a notarization-friendly `.app` bundle. unzip and drag it wherever (~/Applications works). credentials live in your user config (`~/Library/Application Support/cunty-scrobbler/config.json`), so no more files cluttering the app folder.

## before you start being cunty

1. get a last.fm account if you don't already have one, duh
2. get your api credentials:
   - hit up [last.fm api](https://www.last.fm/api/account/create)
   - make an api account
   - snatch that api key and secret
3. launch the app
4. put your credentials in
5. start serving tracks

## user manual for the girls who can't read

### searching & scrobbling
1. type artist and track like you know what you're doing
2. hit search
3. click the correct track (if you can manage that)
4. scrobble and feel the fantasy

### album serve
1. artist + album name
2. search
3. click scrobble
4. gather your edges

### batch that shit
1. paste your list, format it cute:
   ```
   artist - track
   ```
2. click scrobble all
3. watch the other girls gag

## development for the tech girlies

1. clone:
   ```bash
   git clone https://github.com/yourusername/cunty-scrobbler.git
   ```

2. install:
   ```bash
   pip install -r requirements.txt
   ```

3. run:
   ```bash
   python gui.py
   ```

### building a mac release without crying

1. make yourself a venv and install deps:
   ```bash
   pip install -r requirements.txt pyinstaller
   ```
2. run:
   ```bash
   ./scripts/build_macos_release.sh
   ```
3. you'll get `dist/macos/CuntyScrobbler.app` plus a zipped `CuntyScrobbler-macos.zip` ready to drop into a GitHub release.

## requirements

- python 3.8+
- pyqt6
- requests
- that's it, don't be greedy

## license

mit license because we're generous like that.

## issues?

if you're having problems, that sounds like a personal issue. but fine, [open an issue](https://github.com/yourusername/cunty-scrobbler/issues) i guess.
