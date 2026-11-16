import threading
import time as T

from main.sensors import system_data
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
from main.paths import CONFIG_DIR
RULES_FILE = CONFIG_DIR / "rules.json"


def get_saved_wallpaper(event, value): # находит сохранённый фон для события
    if not RULES_FILE.exists():
        return None

    try:
        with open(RULES_FILE, "r", encoding="utf-8") as file:
            saved_rules = json.load(file)

        for rule in saved_rules:
            if (
                rule.get("enabled", True)
                and rule.get("event") == event
                and str(rule.get("value", "")).lower() == str(value).lower()
            ):
                return rule.get("wallpaper")

    except Exception as error:
        print("Rules error:", error)

    return None

def get_season_background(): # выбрать задний фон по сезону
    season = system_data["current_season"]

    return get_saved_wallpaper("season", season)

    # season = system_data["current_season"]

    # if season == "winter":
    #    return("winter background")

    # elif season == "spring":
    #    return("spring background")

    # elif season == "summer":
    #    return("summer background")

    # elif season == "fall":
    #    return("fall background")


# season_background()

def get_time_background(): # выбрать фон по времени суток

    time = system_data["time_of_day"]

    if time == "morning":
        return "morning background"

    elif time == "day":
        return "day background"

    elif time == "evening":
        return "evening background"

    else:
        return "night background"

# print(time_background())

def get_active_app_background(): # выбирает фон для активного приложения

    app = system_data["active_app"]

    if app is None:
        return None

    return f"{app} background"

# print(active_app_background())

rules_data = {
    "season_background": None,
    "time_background": None,
    "active_app_background": None

}

def print_every_rules(seconds, rule, name): # обновляет правило через заданный интервал
    def run(): # выполняет работу в отдельном потоке
        while True:
            rules_data[name] = rule()
            T.sleep(seconds)

    threading.Thread(target=run, daemon=True).start()

def start_rules_informaton(): # узнать выбранный задний фон каждое определённое время

    print_every_rules(2, get_active_app_background, "active_app_background" )
    print_every_rules(60, get_time_background, "time_background")
    print_every_rules(86400, get_season_background, "season_background")

if __name__ == "__main__":
    start_rules_informaton()


