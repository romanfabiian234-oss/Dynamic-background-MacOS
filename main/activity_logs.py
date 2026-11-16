from collections import deque
import os
from datetime import datetime
from threading import Lock


_lock = Lock()

activity_log = deque(maxlen=50)

activity_state = {
    "running": False,
    "season": None,
    "time_of_day": None,
    "active_app": None,
    "active_rule": None,
    "wallpaper": None,
    "background_attribution": None,
    "last_action": None,
}


def log_activity(message): # записывает событие в журнал
    time_now = datetime.now().strftime("%H:%M:%S")

    with _lock:
        activity_log.append({
            "time": time_now,
            "message": message
        })

        activity_state["last_action"] = message


def set_activity(name, value): # обновляет состояние действия
    with _lock:
        activity_state[name] = value


def get_activity(): # получает состояние и события журнала
    with _lock:
        return activity_state.copy(), list(activity_log)


def clean_text(value, limit=1500): # убирает секреты и управляющие символы из текста
    """Не выводить секреты и управляющие последовательности из metadata."""
    text = str(value)
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if key:
        text = text.replace(key, "[REDACTED]")
    return "".join(c for c in text if c.isprintable())[:limit]


class ActivityLog:
    def __init__(self): # создаёт отдельный журнал движка
        self._events = deque(maxlen=50)
        self._log_lock = Lock()

    def log_activity(self, message): # записывает событие движка
        with self._log_lock:
            self._events.append({"time": datetime.now().strftime("%H:%M:%S"),
                                 "message": clean_text(message, 3000)})

    def get_activity(self): # получает события движка
        with self._log_lock:
            return list(self._events)
