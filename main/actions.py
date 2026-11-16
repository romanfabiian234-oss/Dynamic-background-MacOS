from main.rules import rules_data
from main.activity_logs import log_activity, set_activity
import time as T
from pathlib import Path
import subprocess

WALLPAPER_SCRIPT = '''on run argv
    set wallpaper_file to POSIX file (item 1 of argv)
    tell application "System Events"
        if (count of desktops) is 0 then error "No desktop is available"
        repeat with desktop_item in desktops
            set picture of desktop_item to wallpaper_file
        end repeat
    end tell
end run'''

def set_wallpaper(image_path): # устанавливает изображение на рабочий стол
    if not image_path:
        return False

    try:
        path = Path(image_path).expanduser().resolve(strict=True)

        if not path.is_file():
            return False

        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                WALLPAPER_SCRIPT,
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )

        set_activity("wallpaper", str(path))
        log_activity(f"Wallpaper changed: {path.name}")

        return True

    except subprocess.TimeoutExpired:
        log_activity("Wallpaper change timed out")
        return False

    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        log_activity(f"Wallpaper error: {error}")
        return False

    
def start_actions(): # применяет фон выбранного правила
    last_wallpaper = None

    while True:
        wallpaper = rules_data.get("season_background")

        if wallpaper and wallpaper != last_wallpaper:

            if set_wallpaper(wallpaper):
                last_wallpaper = wallpaper

        T.sleep(1)