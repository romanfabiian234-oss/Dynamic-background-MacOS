from __future__ import annotations

import copy
import datetime as DT
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main.sensors import start_system_information
from main.rules import start_rules_informaton, rules_data
from main.actions import start_actions
from main.activity_logs import log_activity, set_activity
from main.background_engine import (
    BackgroundContext, BackgroundEngine, BackgroundError, DEFAULT_DIRECTORY,
)


def start_connector(): # связывает данные системы, правила и действия
    start_system_information()
    start_rules_informaton()
    start_actions()


def start_dynamic_interface(): # запускает динамический интерфейс
    thread = threading.Thread(
        target=start_connector,
        daemon=True
    )

    thread.start()

    set_activity("running", True)
    log_activity("Dynamic interface started")

    print("Dynamic interface started")


# Public API — ленивый singleton; import не запускает меню и потоки.
_default_engine = None
_default_lock = threading.Lock()


def configure_background_engine(
    directory=DEFAULT_DIRECTORY, context_provider=None, wallpaper_setter=None,
    attribution_display=None, providers=None,
): # настраивает общий экземпляр Background Engine
    """Configure the singleton before starting integration with Dynamic Interface.

    context_provider: returns BackgroundContext or a dict containing season/current_season
                      and time_of_day.
    wallpaper_setter: receives a prepared local image path and returns True on success.
    attribution_display: receives a Pexels attribution dict (or None to clear) and must
                         return True after persistent attribution is visible.
    """
    global _default_engine
    with _default_lock:
        if _default_engine is not None:
            running = (_default_engine._thread is not None
                       and _default_engine._thread.is_alive())
            if running:
                raise BackgroundError("Stop Background Engine before reconfiguring it")
        _default_engine = BackgroundEngine(
            directory=directory, providers=providers, wallpaper_setter=wallpaper_setter,
            context_provider=context_provider, attribution_display=attribution_display,
        )
        return _default_engine


def get_engine(): # получает общий экземпляр Background Engine
    global _default_engine
    with _default_lock:
        if _default_engine is None:
            _default_engine = BackgroundEngine()
        return _default_engine


def get_background_context(when: DT.datetime | None = None) -> dict: # получает данные для выбора фона
    return get_engine().get_context(when).to_dict() # type: ignore


def get_background_path() -> str | None: # получает путь к текущему фону
    return get_engine().get_path()


def get_background_attribution() -> dict | None: # получает информацию об авторе фотографии
    current = get_engine().get_status().get("current")
    if not isinstance(current, dict):
        return None
    attribution = current.get("attribution")
    return copy.deepcopy(attribution) if isinstance(attribution, dict) else None


def change_background(context: BackgroundContext | dict | None = None) -> str | None: # меняет текущий задний фон
    """Random/manual-one-click change; Pexels requires persistent display attribution."""
    return get_engine().change_background(context)


def start_background_engine() -> bool: # запускает автоматическую смену фона
    return get_engine().start()


def stop_background_engine(timeout: float = 2.0) -> bool: # останавливает автоматическую смену фона
    # Не создавать runtime-файлы ради stop() до первого запуска.
    with _default_lock:
        engine = _default_engine
    return True if engine is None else engine.stop(timeout=timeout)


def get_background_status() -> dict: # получает состояние Background Engine
    return get_engine().get_status()
