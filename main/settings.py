import argparse
import datetime as DT
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main.connector import start_dynamic_interface, get_engine
from main.activity_logs import clean_text, get_activity, set_activity 
from main.background_engine import (
    BackgroundEngine, BackgroundError, DEFAULT_DIRECTORY, NUMBER_LIMITS,
    PEXELS_URL, PEXELS_WALLPAPER_HELP, STYLES, build_background_query,
    __doc__ as BACKGROUND_HELP,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "rules.json"


def load_rules(): # позволяет загрузить задний фон под определённым значением
    if not CONFIG_FILE.exists():
        return []

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def save_rules(rules): # сохраняет задний фон в Json файле (config.rules.json)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(rules, file, indent=4, ensure_ascii=False)


def show_rules(): # показывает сохранённые задний фон 
    rules = load_rules()

    print("\nWALLPAPER RULES")
    print("-" * 60)

    if not rules:
        print("No rules")
        return

    for index, rule in enumerate(rules, start=1):
        print(
            f"{index}. "
            f"{rule['event']} = {rule['value']} "
            f"-> {rule['wallpaper']}"
        )

    print("-" * 60)
def show_background_attribution(attribution): # показывает автора текущего фона Pexels
    set_activity("background_attribution", attribution)

    if attribution is None:
        return True

    text = attribution.get("text", "")

    if not text:
        return False

    print()
    print(text)

    photo_url = attribution.get("photo_url", "")

    if photo_url:
        print(photo_url)

    return True

def add_rule(): # добавить значение
    print("\nADD RULE")
    print()
    print("Event types:")
    print("1. season")
    print("2. time")
    print("3. application")

    choice = input("\nEvent: ").strip()

    event_types = {
        "1": "season",
        "2": "time",
        "3": "application",
    }

    event = event_types.get(choice)

    if event is None:
        print("Unknown event")
        return

    if event == "season":
        print("Values: spring, summer, fall, winter")

    elif event == "time":
        print("Values: morning, day, evening, night")

    elif event == "application":
        print("Example: Terminal, Finder, Visual Studio Code")

    value = input("Value: ").strip()

    print("Drag an image from Finder into Terminal")
    wallpaper = input("Image: ").strip()

    # Terminal may put quotes around a dragged path
    wallpaper = wallpaper.strip("'\"")

    if not Path(wallpaper).exists():
        print("Image not found")
        return

    priority_text = input("Priority [50]: ").strip()

    try:
        priority = int(priority_text) if priority_text else 50
    except ValueError:
        priority = 50

    rules = load_rules()

    rules.append({
        "event": event,
        "value": value,
        "wallpaper": wallpaper,
        "priority": priority,
        "enabled": True,
    })

    save_rules(rules)

    print("\nRule saved.")


def delete_rule(): # удалить значение
    show_rules()

    rules = load_rules()

    if not rules:
        return

    number = input("\nRule number to delete: ").strip()

    try:
        index = int(number) - 1
    except ValueError:
        print("Invalid number")
        return

    if index < 0 or index >= len(rules):
        print("Rule not found")
        return

    removed = rules.pop(index)
    save_rules(rules)

    print(
        f"Deleted: {removed['event']} = {removed['value']}"
    )

def show_activity(): # показать активные действия и log 
    state, events = get_activity()

    print()
    print("-" * 60)
    print("ACTIVITY")
    print("-" * 60)

    print("System:", "RUNNING" if state["running"] else "STOPPED")
    print("Season:", state["season"] or "-")
    print("Time:", state["time_of_day"] or "-")
    print("Active app:", state["active_app"] or "-")
    print("Active rule:", state["active_rule"] or "-")
    print("Wallpaper:", state["wallpaper"] or "-")

    print()
    print("RECENT ACTIONS")
    print("-" * 60)

    if not events:
        print("No activity yet")
    else:
        for event in reversed(events[-10:]):
            print(f'{event["time"]}  {event["message"]}')

    print("-" * 60)


# Terminal — простое меню в стиле main/settings.py.
def print_header(title): # показывает заголовок меню
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def show_current(engine): # показывает текущий задний фон
    print_header("CURRENT BACKGROUND")
    current = engine.get_status()["current"]
    if not current:
        print("No background has been selected yet")
        return
    candidate = current["candidate"]
    for label, value in (
        ("Title", candidate["title"]), ("Path", current["path"]),
        ("Source", candidate["provider"]), ("Photographer", candidate["photographer"] or "-"),
        ("Photo URL", candidate["photo_url"] or "-"), ("Photo ID", candidate["photo_id"] or "-"),
        ("Original query", candidate["query"]), ("Last change", current["changed_at"]),
    ):
        print(label + ":", clean_text(value))
    if not engine.get_path():
        print("Current file is missing; use Change background now")


def show_status(engine): # показывает состояние Background Engine
    state = engine.get_status()
    context = state["context"]
    print_header("BACKGROUND ENGINE STATUS")
    for label, value in (
        ("Version", state["version"]),
        ("Engine", state["engine"]), ("Auto mode", "ON" if state["auto_mode"] else "OFF"),
        ("Season", context["season"]), ("Time", context["time_of_day"]),
        ("Style", context["style"]), ("Provider", state["provider"]),
        ("Screen", f'{context["width"]}x{context["height"]} — {state["screen_source"]}'),
        ("Internet", state["internet"]), ("Last network check", state["internet_last_check"] or "-"),
        ("Pexels API", state["pexels_api"]),
        ("Pexels manual selection", state["pexels_manual_selection"]),
        ("Pexels automatic", state["pexels_automatic"]),
        ("Pillow", state["pillow"]), ("Cache", f'{state["cache_count"]} / {state["cache_limit"]}'),
        ("Last error", state["last_error"] or "-"),
    ):
        print(label + ":", clean_text(value))
    show_current(engine)


def show_background_activity(engine): # показывает действия Background Engine
    print_header("RECENT ACTIVITY")
    for event in reversed(engine.get_activity()[-15:]):
        print(event["time"], event["message"])


def show_context(engine, context=None): # показывает данные для выбора фона
    context = context or engine.get_context()
    print_header("BACKGROUND CONTEXT")
    print(json.dumps(context.to_dict(), indent=4, ensure_ascii=False))
    print("Query:", build_background_query(context))


def show_cache(engine): # показывает сохранённые изображения
    print_header("BACKGROUND CACHE")
    try:
        files = engine.storage.cache_files()
        print(f"Images: {len(files)} / {engine.settings['cache_limit']}")
        for index, path in enumerate(files, 1):
            print(f"{index}. {path.name}  ({path.stat().st_size / 1024 / 1024:.1f} MiB)")
        print("Local images:", engine.storage.local_dir)
    except (OSError, BackgroundError) as error:
        print(clean_text(error))


def choose_setting(engine, name, choices): # позволяет выбрать значение настройки
    print_header(name.upper())
    choices = list(choices)
    for index, value in enumerate(choices, 1):
        print(f"{index}. {value}")
    choice = input("Number (Enter to cancel): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(choices):
        value = choices[int(choice) - 1]
        print("Saved" if engine.update_settings(**{name: value}) else "Not saved; see Activity")


def edit_settings(engine): # позволяет изменить настройки фона
    print_header("SETTINGS")
    names = list(NUMBER_LIMITS) + ["debug", "pexels_auto_enabled"]
    for index, name in enumerate(names, 1):
        print(f"{index}. {name}: {engine.settings[name]}")
    print("Pexels API:", engine.get_status()["pexels_api"])
    print("Screen: 0 and 0 = detect automatically. Set both dimensions together.")
    choice = input("Setting number (Enter to cancel): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(names):
        return
    name = names[int(choice) - 1]
    if name == "pexels_auto_enabled":
        print("Automatic/random Pexels use also requires persistent attribution display.")
        print(PEXELS_WALLPAPER_HELP)
        value = input("ON / OFF: ").strip().lower()
        if value not in {"on", "off"}:
            return
        changes = {name: value == "on"}
    elif name in ("screen_width", "screen_height"):
        width = int(input("Screen width [0 = auto]: ").strip())
        height = int(input("Screen height [0 = auto]: ").strip())
        changes = {"screen_width": width, "screen_height": height}
    elif name == "debug":
        value = input("ON / OFF: ").strip().lower()
        if value not in {"on", "off"}:
            return
        changes = {name: value == "on"}
    else:
        low, high = NUMBER_LIMITS[name]
        changes = {name: int(input(f"Value ({low}–{high}): ").strip())}
    print("Saved" if engine.update_settings(**changes) else "Not saved; see Activity")


def show_candidates(engine, context=None, interactive=True): # показывает и выбирает подходящий фон
    context = context or engine.get_context()
    print_header("BACKGROUND CANDIDATES")
    print("Photos provided by Pexels:", PEXELS_URL)
    candidates = engine.get_candidates(context)
    if not candidates:
        print("No suitable candidates. See Status / Activity; add images to", engine.storage.local_dir)
        return
    for index, candidate in enumerate(candidates, 1):
        print(f"{index}. {clean_text(candidate.title)}")
        print(f"   {candidate.width}x{candidate.height} | {candidate.storage} | {candidate.provider}")
        if candidate.photographer:
            print("   Photo by", clean_text(candidate.photographer), "on Pexels")
            print("  ", clean_text(candidate.photo_url))
    if interactive:
        choice = input("Apply number (Enter to cancel): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            path = engine.change_background(
                context, candidates[int(choice) - 1], selection_attributed=True
            )
            print("Wallpaper changed" if path else "No change; see Activity")
            if path:
                show_current(engine)


def terminal_menu(engine=None): # открывает меню Background Engine
    if engine is None:
        engine = get_engine()

    engine.attribution_display = show_background_attribution

    if engine.settings["auto_mode"]:
        engine.start()
    while True:
        print_header("DYNAMIC BACKGROUND ENGINE")
        print("""
                1. Status
                2. Change background now
                3. Auto mode ON / OFF
                4. Background style
                5. Background source
                6. Show current context
                7. Show current background
                8. Show candidates / choose background
                9. Show cache
                10. Clear cache
                11. Settings
                12. Activity
                13. Back""")

        print("")
        print("Photos provided by Pexels:", PEXELS_URL)
        try:
            command = input("\nCommand: ").strip()
            if command == "1":
                show_status(engine)

            elif command == "2":
                if engine.change_background():
                    show_current(engine)
                else:
                    show_background_activity(engine)

            elif command == "3":
                if engine.get_status()["auto_mode"]:
                    print("Stopped" if engine.stop() else "Stopping; see Activity")
                else:
                    print("Started" if engine.start() else "Previous thread is still stopping")

            elif command == "4":
                choose_setting(engine, "style", STYLES)

            elif command == "5":
                choose_setting(engine, "provider", ["auto", "local", "cache", *engine.providers])

            elif command == "6":
                show_context(engine)

            elif command == "7":
                show_current(engine)

            elif command == "8":
                show_candidates(engine)

            elif command == "9":
                show_cache(engine)

            elif command == "10":
                if input("Delete downloaded cache images? Type CLEAR: ").strip() == "CLEAR":
                    with engine._operation_lock:
                        print("Removed:", engine.storage.trim_cache(clear=True))
                    print("Current wallpaper and local images are kept")

            elif command == "11":
                edit_settings(engine)

            elif command == "12":
                show_background_activity(engine)

            elif command == "13":
                return
            else:
                print("Unknown command")

        except ValueError:
            print("Invalid value; enter a number in the displayed range")

        except (EOFError, KeyboardInterrupt):
            print("\nExit")
            return
        
        except Exception as error:
            engine.report_error(error)
            print(clean_text(error))

def background_main(argv=None): # запускает Background Engine из терминала
    parser = argparse.ArgumentParser(description=BACKGROUND_HELP)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--context", action="store_true")
    modes.add_argument("--change", action="store_true", help="Change wallpaper once, then exit")
    modes.add_argument("--candidates", action="store_true", help="List candidates without changing wallpaper")
    modes.add_argument("--auto", action="store_true", help="Run until Ctrl+C")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--style", choices=STYLES)
    parser.add_argument("--provider", choices=("auto", "local", "cache", "pexels"))
    parser.add_argument("--screen", help="Save screen size, e.g. 2880x1800; 0x0 = detect")
    parser.add_argument("--at", help="Override local date/time for context, candidates or change")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    when = None
    if args.at:
        if not (args.context or args.candidates or args.change):
            parser.error("--at requires --context, --candidates or --change")
        try:
            when = DT.datetime.fromisoformat(args.at)
        except ValueError:
            parser.error("--at expects an ISO date/time, e.g. 2026-12-15T22:00:00")
    engine = BackgroundEngine(args.data_dir)
    changes = {k: getattr(args, k) for k in ("style", "provider") if getattr(args, k)}
    if args.debug:
        changes["debug"] = True
    if args.screen:
        match = re.fullmatch(r"(\d+)x(\d+)", args.screen)
        if not match:
            parser.error("--screen expects WIDTHxHEIGHT")
        changes.update(screen_width=int(match[1]), screen_height=int(match[2]))
    if changes and not engine.update_settings(**changes):
        show_background_activity(engine)
        return 1
    try:
        if args.status:
            show_status(engine)
        elif args.context:
            show_context(engine, engine.get_context(when))
        elif args.candidates:
            show_candidates(engine, engine.get_context(when), interactive=False)
        elif args.change:
            if not engine.change_background(engine.get_context(when)):
                show_background_activity(engine)
                return 1
            show_current(engine)
        elif args.auto:
            print("Auto mode started. Press Ctrl+C to exit.")
            print("Photos provided by Pexels:", PEXELS_URL)
            engine.start()
            previous = None
            while engine._thread is not None and engine._thread.is_alive():
                events = engine.get_activity()
                if events and events[-1] != previous:
                    previous = events[-1]
                    print(previous["time"], previous["message"], flush=True)
                engine._stop_event.wait(1)
        else:
            terminal_menu(engine)
    except (KeyboardInterrupt, EOFError):
        print("\nExit")
    except Exception as error:
        engine.report_error(error)
        print(clean_text(error))
        return 1
    finally:
        # Сохранить выбор auto_mode для следующего запуска меню.
        engine.stop(save_preference=False)
    return 0


def main(): # собрать настройки вместе
    while True:
        print("\n")
        print("-" * 60)
        print("DYNAMIC INTERFACE SETTINGS")
        print("-" * 60)

        print("""
        1. Show rules
        2. Add wallpaper rule
        3. Delete rule
        4. Activity
        5. background_engine
        6. Start
        7. Exit 
        """)

        command = input("Command: ").strip()

        state, events = get_activity()

        attribution = state.get("background_attribution")

        if attribution:
            print()
            print(attribution.get("text", ""))

        if command == "1":
            show_rules()

        elif command == "2":
            add_rule()

        elif command == "3":
            delete_rule()

        elif command == "4":
            show_activity() 

        elif command == "5":
            terminal_menu()

        elif command == "6":
            start_dynamic_interface()

        elif command == "7":
            print("Exit")
            break


        else:
            print("Unknown command")


if __name__ == "__main__":
    main()
