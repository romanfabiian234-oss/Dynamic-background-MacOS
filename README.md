# Dynamic Background for macOS

Change your Mac wallpaper using local photos, season and time of day, or manually selected Pexels photos. This is a Python terminal application, not a menu-bar app.

## Requirements and first start

- macOS; Python **3.10 or later** from [python.org](https://www.python.org/downloads/macos/).
- Internet access for the first dependency installation and Pexels searches. Local photos work offline after installation.

Download this repository with **Code → Download ZIP**, unzip it into a writable folder, then open Terminal in that folder:

```sh
bash START.command
```

The launcher creates a local `.venv`, installs Pillow when needed, and opens the wallpaper menu. It does not install a login service. To use an existing Python installation explicitly: `DYNAMIC_BACKGROUND_PYTHON=/path/to/python3 bash START.command`.

Choose **Background source → local**, then put your own JPG/PNG/WebP images into:

```text
~/Library/Application Support/DynamicBackground/backgrounds/local/
```

Choose **Change background now**. Use **Status** and **Activity** to inspect the result. An empty local folder cannot produce a wallpaper. Other options let you choose style, browse candidates and enable automatic changes. Automatic mode runs while the process remains open; quit with Ctrl+C. The current wallpaper remains set when the process stops.

```sh
bash START.command --status
bash START.command --auto
```

macOS may ask to let Terminal control System Events when changing wallpaper. Grant that permission only if you want to use this feature. Windows and Linux wallpaper changes are not supported.

## Pexels (optional)

Obtain your own API key from [Pexels](https://www.pexels.com/api/). In Terminal, enter it without displaying it or saving it in shell history, then start the app in that same Terminal:

```sh
read -rs PEXELS_API_KEY
export PEXELS_API_KEY
bash START.command
unset PEXELS_API_KEY
```

Select Pexels and browse candidates to choose a photo. Never commit your key. Photographer attribution is displayed during manual selection. Unattended Pexels selection requires a persistent attribution callback; the standalone `--auto` command does not provide that display and therefore does not use Pexels for automatic/random choices. Local images remain available without an API key. Pexels photographs remain subject to Pexels' terms, not this code's MIT license.

## Data, updates and removal

Settings, rules and downloaded images are stored under `~/Library/Application Support/DynamicBackground`, outside the source folder. `DYNAMIC_BACKGROUND_DATA_DIR` overrides this location; `--data-dir` overrides only the engine's backgrounds folder.

Before updating an older checkout, back up its `main/backgrounds/` and `config/` folders. To migrate, stop the program and copy those folders to `backgrounds/` and `config/` inside the new data directory. Keep the backup; metadata may refer to old absolute image paths, so reselect the wallpaper if needed. New installations start empty and do not download the author's image cache.

To update, replace the source folder and rerun the launcher. After a requirements change, run `.venv/bin/python -m pip install -r requirements.txt`. Stop with Ctrl+C before updating. To uninstall, stop the process and delete the source folder. Delete the data folder in Finder only if you also want to remove saved preferences and images. This application does not register automatic login startup.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'
```

Tests use temporary data and mock wallpaper/network operations. A passing test suite does not replace testing a real wallpaper change on your macOS version. The season calculation follows Northern Hemisphere calendar seasons.

## License

Code: [MIT](LICENSE), copyright romanfabiian234-oss. Supply your own photos or follow the source provider's image license.
