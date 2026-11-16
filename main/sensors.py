import ctypes
import datetime as DT
import sys
import time as T
import subprocess
import plistlib
import threading



def now_text(): # получает текущее время для записей движка
    return DT.datetime.now().astimezone().isoformat(timespec="seconds")


def get_time_of_day(when=None): # узнать время

    current_time = when if when is not None else DT.datetime.now()
    hour = current_time.hour

    if 6 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 18:
        time_of_day = "day"
    elif 18 <= hour < 22:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    return time_of_day

# print (get_time_of_day()) 

def get_current_season(when=None): # узнаёт текущий сезон

    current_month = when if when is not None else DT.datetime.now()
    month = current_month.month

    if month in (12, 1, 2):
        season = "winter"

    if month in (3, 4, 5):
        season = "spring"

    if month in (6, 7, 8):
        season = "summer"

    if month in (9, 10, 11):
        season = "fall"

    return season

# print(get_current_month())

def get_active_app(): # узнать активное окно на экране 
    app = subprocess.check_output(
        """osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true'""",
        shell=True,
        text=True
    )

    return app.strip()

# print(get_active_app())

def get_dock_apps(): # найти приложения в Apple.Dock на Mac
    data = plistlib.loads(
        subprocess.check_output(["defaults", "export", "com.apple.dock", "-"])

    )

    apps = data.get("persistent-apps", []) + data.get("recent-apps", [])

    return [
        app["tile-data"]["file-label"]
        for app in apps
    ]

# for app in get_dock_apps():
#    print(f"[{app}],")

def get_screen_size(): # получить размер экрана
    """Retina pixels через CoreGraphics, без зависимости от PyObjC."""
    if sys.platform == "darwin":
        try:
            cg = ctypes.CDLL(
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
            )
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
            cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
            for name in ("CGDisplayModeGetPixelWidth", "CGDisplayModeGetPixelHeight"):
                fn = getattr(cg, name)
                fn.argtypes = [ctypes.c_void_p]
                fn.restype = ctypes.c_size_t
            cg.CGDisplayModeRelease.argtypes = [ctypes.c_void_p]
            cg.CGDisplayModeRelease.restype = None
            mode = cg.CGDisplayCopyDisplayMode(cg.CGMainDisplayID())
            if mode:
                try:
                    width = int(cg.CGDisplayModeGetPixelWidth(mode))
                    height = int(cg.CGDisplayModeGetPixelHeight(mode))
                    if width > 0 and height > 0:
                        return width, height, "CoreGraphics (main display pixels)"
                finally:
                    cg.CGDisplayModeRelease(mode)
        except (OSError, AttributeError, ValueError):
            return 1920, 1080, "Fallback; set your screen size in Settings"
    return 1920, 1080, "Fallback; set your screen size in Settings"

# print(get_screen_resolution())

system_data = {
    "active_app": None,
    "time_of_day": None,
    "dock_apps": [],
    "current_season": None,
    "screen_size": None

}

def print_every_sensors(seconds, sensor, name): # обновляет данные датчика через заданный интервал
    def run(): # выполняет работу в отдельном потоке
        while True:
            system_data[name] = sensor()
            T.sleep(seconds)

    threading.Thread(target=run, daemon=True).start()

def print_one_sensor(sensor, name): # получает данные датчика один раз
    def run(): # выполняет работу в отдельном потоке
        system_data[name] = sensor()

    threading.Thread(target=run, daemon=True).start()


def start_system_information(): # узнавать данные устройство каждое определённое время

    print_every_sensors(2, get_active_app, "active_app") # каждые 2 сек
    print_every_sensors(30, get_dock_apps, "dock_apps") # каждый час
    print_every_sensors(60, get_time_of_day, "time_of_day") # каждую минуту
    print_every_sensors(86400, get_current_season, "current_season") # раз в день
    print_one_sensor(get_screen_size, "screen_size") # Один раз


if __name__ == "__main__":
    start_system_information()

