import sys
import time as T

from main.connector import start_dynamic_interface, get_engine


def start_background(): # запускает динамический интерфейс в фоновом режиме
    start_dynamic_interface()

    engine = get_engine()

    if engine.settings["auto_mode"]:
        engine.start()

    try:
        while True:
            T.sleep(60)

    except KeyboardInterrupt:
        engine.stop()


def main(): # запускает обычный или фоновый режим
    if "--background" in sys.argv:
        start_background()
        return

    from main.settings import main as settings_main
    settings_main()


if __name__ == "__main__":
    main()