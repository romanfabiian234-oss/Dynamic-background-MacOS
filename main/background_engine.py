#!/usr/bin/env python3
"""Dynamic Background Engine v1.1.0 — Python 3.10+, macOS.

Install: python3 -m pip install Pillow
Run:     python3 -m main.background_engine
Importing this module does not create files, start threads or change wallpaper.

Pexels can be used as a background-selection feature inside a broader product.
Manual Pexels selection shows attribution in the search flow. Automatic/random
Pexels backgrounds are allowed only when the host provides a persistent
attribution display callback. Without that callback, auto mode uses cache/local
images that do not require Pexels display attribution.
"""

from __future__ import annotations

import copy
import datetime as DT
import hashlib
import json
import math
import os
import random
import re
import socket
import sys
import tempfile
import threading
import time as T
import traceback
import uuid
import warnings
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main.actions import set_wallpaper
from main.activity_logs import ActivityLog, clean_text
from main.sensors import get_time_of_day, get_current_season, get_screen_size, now_text

try:
    from PIL import Image, ImageOps  # type: ignore 
except (ImportError, OSError):
    Image = None
    ImageOps = None


# Настройки и правила запросов — меняйте их здесь.
ENGINE_VERSION = "1.1.0"
PROJECT_DIR = Path(__file__).resolve().parent
from main.paths import BACKGROUND_DIR
DEFAULT_DIRECTORY = BACKGROUND_DIR
PEXELS_URL = "https://www.pexels.com"
PEXELS_WALLPAPER_HELP = "https://help.pexels.com/hc/en-us/articles/4405588861721"
PILLOW_HELP = "Pillow is required. Install: python3 -m pip install Pillow"

STYLES = {
    "natural": "nature realistic natural light",
    "minimal": "minimal simple clean composition negative space",
    "cinematic": "cinematic dramatic light atmospheric",
    "dark": "dark moody low light",
    "colorful": "colorful vibrant rich colors",
    "calm": "calm peaceful soft muted colors",
}
SEASON_QUERIES = {
    "spring": "spring green meadow blossoms",
    "summer": "summer lake mountains",
    "fall": "autumn forest lake golden leaves",
    "winter": "winter snowy mountains",
}
TIME_QUERIES = {
    "morning": "morning sunrise soft light",
    "day": "daylight clear sky",
    "evening": "evening sunset warm light",
    "night": "night stars dark sky",
}
TAG_ALIASES = {
    "spring": {"spring", "весна"},
    "summer": {"summer", "лето", "літо"},
    "fall": {"fall", "autumn", "осень", "осінь"},
    "winter": {"winter", "snow", "snowy", "зима"},
    "morning": {"morning", "sunrise", "утро", "ранок"},
    "day": {"day", "daylight", "день"},
    "evening": {"evening", "sunset", "вечер", "вечір"},
    "night": {"night", "stars", "ночь", "ніч"},
}
DEFAULT_SETTINGS = {
    "auto_mode": False,
    "style": "natural",
    "provider": "auto",
    "cache_limit": 50,
    "history_limit": 10,
    "check_interval": 60,
    "retry_interval": 300,
    "request_timeout": 10,
    "download_deadline": 30,
    "search_cache_hours": 24,
    "screen_width": 0,
    "screen_height": 0,
    "pexels_auto_enabled": True,
    "debug": False,
}
NUMBER_LIMITS = {
    "cache_limit": (1, 1000), "history_limit": (1, 100),
    "check_interval": (10, 86400), "retry_interval": (60, 86400),
    "request_timeout": (2, 30), "download_deadline": (5, 120),
    "search_cache_hours": (1, 168),
    "screen_width": (0, 16384), "screen_height": (0, 16384),
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "TIFF", "BMP"}
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000
MAX_JSON_BYTES = 8 * 1024 * 1024
CACHE_NAME = re.compile(r"image_[0-9a-f]{64}\.(?:jpg|png|webp|tiff|bmp)\Z")
CURRENT_NAME = re.compile(r"wallpaper_[0-9a-f]{32}\.jpg\Z")

@dataclass
class BackgroundCandidate:
    id: str
    provider: str
    title: str
    width: int
    height: int
    path: str = ""
    download_url: str = ""
    photographer: str = ""
    photographer_url: str = ""
    photo_url: str = ""
    photo_id: str = ""
    query: str = ""
    context: dict = field(default_factory=dict)
    storage: str = "remote"
    downloaded_at: float = 0.0
@dataclass(frozen=True)
class BackgroundContext:
    season: str
    time_of_day: str
    style: str = "natural"
    orientation: str = "landscape"
    width: int = 1920
    height: int = 1080
    extras: dict = field(default_factory=dict)

    def __post_init__(self): # проверяет параметры контекста фона
        if self.season not in SEASON_QUERIES or self.time_of_day not in TIME_QUERIES:
            raise BackgroundError("Unknown season or time of day")
        if self.style not in STYLES or self.orientation != "landscape":
            raise BackgroundError("Unknown style; orientation must be landscape")
        if not (0 < self.width <= 16384 and 0 < self.height <= 16384):
            raise BackgroundError("Invalid screen size")

    def to_dict(self): # преобразует контекст в словарь
        return asdict(self)

    def signature(self): # создаёт ключ контекста для выбора фона
        # Час/секунды не входят в ключ — фон не меняется каждую минуту.
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


class BackgroundError(Exception):
    """An error that can be shown without a Python traceback."""


class BackgroundStorage:
    def __init__(self, directory, log, providers): # подготавливает состояние и зависимости
        self.directory = Path(directory).expanduser().resolve()
        self.local_dir = self.directory / "local"
        self.cache_dir = self.directory / "cache"
        self.current_dir = self.directory / "current"
        self.log = log
        try:
            self.ensure_directories()
        except BackgroundError as error:
            log(str(error))
        settings_path = self.directory / "settings.json"
        self.settings, invalid = validated_settings(
            load_json(settings_path, DEFAULT_SETTINGS, log), providers
        )
        if invalid:
            log("Invalid settings restored: " + ", ".join(invalid))
        default = {"images": {}, "history": [], "current": None,
                   "searches": {}, "network": {}}
        self.data = load_json(self.directory / "metadata.json", default, log)
        for key, value in default.items():
            if key not in self.data or (
                value is not None and not isinstance(self.data[key], type(value))
            ):
                log("Metadata section restored: " + key)
                self.data[key] = copy.deepcopy(value)
        self.data["history"] = [
            item for item in self.data["history"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ][-self.settings["history_limit"]:]
        current = self.data["current"]
        if current is not None and not self.valid_current(current):
            self.log("Invalid current-background metadata ignored")
            self.data["current"] = None
        self.save_settings()

    def save_settings(self): # сохраняет настройки движка
        """Persist the current settings and report whether it succeeded."""
        return self.save("settings.json", self.settings)

    def ensure_directories(self): # создаёт папки для хранения фонов
        try:
            for path in (self.directory, self.local_dir, self.cache_dir, self.current_dir):
                if path in (self.cache_dir, self.current_dir) and path.is_symlink():
                    raise BackgroundError("Managed cache/current folder cannot be a symlink")
                path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BackgroundError("Cannot create background folders; check write access") from error

    def valid_current(self, current): # проверяет данные текущего фона
        try:
            candidate_from_dict(current["candidate"])
            return (isinstance(current["path"], str)
                    and isinstance(current["context"], dict)
                    and isinstance(current["signature"], str)
                    and isinstance(current["changed_at"], str))
        except (KeyError, TypeError, ValueError):
            return False

    def save_metadata(self): # сохраняет данные фонов и историю
        return self.save("metadata.json", self.data)

    def save(self, name, value): # сохраняет данные движка в JSON
        try:
            self.ensure_directories()
            atomic_json(self.directory / name, value)
            return True
        except (OSError, ValueError, BackgroundError):
            self.log(f"Cannot save {name}; changes remain in memory only")
            return False

    def managed_path(self, name, current=False): # проверяет путь внутри папок движка
        """Удаление возможно только внутри собственной папки и по своему имени."""
        root = self.current_dir if current else self.cache_dir
        pattern = CURRENT_NAME if current else CACHE_NAME
        if not isinstance(name, str) or not pattern.fullmatch(name):
            raise BackgroundError("Unrecognized managed image name")
        if root.is_symlink():
            raise BackgroundError("Managed image folder cannot be a symlink")
        path = root / name
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise BackgroundError("Unsafe managed image path")
        return path

    def cached_candidates(self, context): # получает подходящие фоны из кэша
        candidates = []
        # Если metadata потеряна, сами файлы кэша остаются полезны offline.
        try:
            for path in self.cache_files():
                if path.name not in self.data["images"]:
                    try:
                        width, height, _ = inspect_image(path)
                        recovered = BackgroundCandidate(
                            "recovered:" + path.name, "pexels", path.name, width, height,
                            path=str(path), storage="cache", downloaded_at=path.stat().st_mtime,
                        )
                        self.data["images"][path.name] = asdict(recovered)
                        self.log("Recovered cached image; original attribution metadata unavailable")
                    except (BackgroundError, OSError):
                        self.log("Damaged orphan cache image ignored")
        except (BackgroundError, OSError) as error:
            self.log("Cache unavailable: " + clean_text(error))
        for name, record in list(self.data["images"].items()):
            try:
                path = self.managed_path(name)
                candidate = candidate_from_dict(record)
                width, height, _ = inspect_image(path)
                candidate.path = str(path)
                candidate.storage = "cache"
                candidate.width, candidate.height = width, height
                if fits_screen(width, height, context):
                    candidates.append(candidate)
            except (BackgroundError, TypeError, ValueError, OSError):
                self.log("Cache entry ignored: " + clean_text(name))
        return candidates

    def cache_files(self): # получает файлы кэша по времени загрузки
        if self.cache_dir.is_symlink():
            raise BackgroundError("Cache folder cannot be a symlink")
        if not self.cache_dir.exists():
            return []
        files = []
        for path in self.cache_dir.iterdir():
            if CACHE_NAME.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                files.append(path)
        return sorted(files, key=lambda path: (path.stat().st_mtime, path.name))

    def trim_cache(self, clear=False): # удаляет лишние изображения из кэша
        try:
            files = self.cache_files()
            count = len(files) if clear else max(0, len(files) - self.settings["cache_limit"])
            removed = 0
            for path in files[:count]:
                try:
                    self.managed_path(path.name).unlink(missing_ok=True)
                    self.data["images"].pop(path.name, None)
                    removed += 1
                except (OSError, BackgroundError):
                    self.log("Could not remove cache image: " + path.name)
            if clear:
                self.data["searches"] = {}
            if removed or clear:
                self.save_metadata()
            return removed
        except (OSError, BackgroundError) as error:
            self.log("Cache cleanup failed: " + clean_text(error))
            return 0

    def store_download(self, temporary, candidate, context): # сохраняет загруженное изображение в кэш
        width, height, image_format = require_fitting_image(temporary, context)
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp",
                     "TIFF": "tiff", "BMP": "bmp"}[image_format]
        digest = hashlib.sha256(candidate.id.encode("utf-8")).hexdigest()
        name = f"image_{digest}.{extension}"
        path = self.managed_path(name)
        os.replace(temporary, path)
        candidate = copy.deepcopy(candidate)
        candidate.path = str(path)
        candidate.width, candidate.height = width, height
        candidate.storage = "cache"
        candidate.downloaded_at = T.time()
        candidate.context = context.to_dict()
        self.data["images"][name] = asdict(candidate)
        self.save_metadata()
        return path

    def prepare_wallpaper(self, source, context): # подготавливает изображение под размер экрана

        if Image is None or ImageOps is None:
            raise BackgroundError(PILLOW_HELP)

        self.ensure_directories()
        require_fitting_image(source, context)

        path = self.managed_path(
            "wallpaper_" + uuid.uuid4().hex + ".jpg",
            current=True,
        )

        try:
            with Image.open(source) as original:
                upright = ImageOps.exif_transpose(original)

                try:
                    rgb = upright.convert("RGB")

                    try:
                        fitted = ImageOps.fit(
                            rgb,
                            (context.width, context.height),
                            method=Image.Resampling.LANCZOS,
                        )

                        try:
                            fitted.save(
                                path,
                                "JPEG",
                                quality=95,
                            )
                        finally:
                            fitted.close()

                    finally:
                        rgb.close()

                finally:
                    upright.close()

            return path

        except Exception:
            path.unlink(missing_ok=True)
            raise

    def cleanup_current(self, keep): # удаляет прежние подготовленные фоны
        try:
            if self.current_dir.is_symlink():
                raise BackgroundError("Current folder cannot be a symlink")
            for path in self.current_dir.iterdir():
                if path != keep and CURRENT_NAME.fullmatch(path.name):
                    try:
                        self.managed_path(path.name, current=True).unlink(missing_ok=True)
                    except (OSError, BackgroundError):
                        self.log("Could not remove an old prepared wallpaper")
        except (OSError, BackgroundError) as error:
            self.log("Prepared wallpaper cleanup failed: " + clean_text(error))


def build_background_query(context: BackgroundContext) -> str: # собирает поисковый запрос для фона
    return " ".join((
        SEASON_QUERIES[context.season], TIME_QUERIES[context.time_of_day],
        STYLES[context.style], context.orientation,
    ))


def candidate_from_dict(data): # проверяет и восстанавливает данные изображения
    if not isinstance(data, dict):
        raise ValueError("Invalid image metadata")
    candidate = BackgroundCandidate(**data)
    if not isinstance(candidate.context, dict):
        raise ValueError("Invalid image context")
    if any(not isinstance(getattr(candidate, k), str) for k in (
        "id", "provider", "title", "path", "download_url", "photographer",
        "photographer_url", "photo_url", "photo_id", "query", "storage",
    )):
        raise ValueError("Invalid image text fields")
    if any(type(v) is not int or v <= 0 for v in (candidate.width, candidate.height)):
        raise ValueError("Invalid image dimensions")
    if (not isinstance(candidate.downloaded_at, (int, float))
            or not math.isfinite(candidate.downloaded_at) or candidate.downloaded_at < 0):
        raise ValueError("Invalid image timestamp")
    return candidate


# Images — проверка размера, повреждения, EXIF и отсутствие увеличения.
def inspect_image(image_path, full=False): # проверяет формат и размер изображения
    if Image is None:
        raise BackgroundError(PILLOW_HELP)
    path = Path(image_path)
    try:
        size = path.stat().st_size
        if not path.is_file() or not 0 < size <= MAX_IMAGE_BYTES:
            raise BackgroundError("Image is empty, missing or larger than 50 MiB")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                if img.format not in IMAGE_FORMATS or getattr(img, "n_frames", 1) != 1:
                    raise BackgroundError("Use a static JPEG, PNG, WebP, TIFF or BMP")
                width, height = img.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise BackgroundError("Image exceeds the 80 megapixel limit")
                if img.getexif().get(274, 1) in (5, 6, 7, 8):
                    width, height = height, width
                image_format = img.format
            if full:
                with Image.open(path) as img:
                    img.verify()
                with Image.open(path) as img:
                    img.load()
        return width, height, image_format
    except BackgroundError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise BackgroundError("Unreadable or damaged image: " + clean_text(path.name)) from error


def fits_screen(width, height, context): # Строго без upscale; кадрирование допускается, растягивание — нет.
    return width > height and width >= context.width and height >= context.height


def require_fitting_image(path, context): # проверяет соответствие изображения экрану
    width, height, image_format = inspect_image(path, full=True)
    if not fits_screen(width, height, context):
        raise BackgroundError(
            f"Image {width}x{height} is too small or not landscape; "
            f"need at least {context.width}x{context.height}"
        )
    return width, height, image_format

# Storage — JSON записывается через временный файл и os.replace.
def atomic_json(path, value): # сохраняет JSON через временный файл
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".json-", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(value, file, indent=4, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_json(path, default, log): # загружает JSON и восстанавливает повреждённые данные
    try:
        if not path.exists():
            return copy.deepcopy(default)
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError("JSON is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data
    except (ValueError, UnicodeError) as error:
        backup = path.with_name(path.stem + ".broken-" + uuid.uuid4().hex[:8] + ".json")
        try:
            path.replace(backup)
            log(f"Invalid {path.name}; defaults restored. Original: {backup.name}")
        except OSError:
            log(f"Invalid {path.name}; defaults loaded in memory; backup unavailable")
        return copy.deepcopy(default)
    except OSError:
        log(f"Cannot read {path.name}; defaults loaded in memory")
        return copy.deepcopy(default)


def validated_settings(data, providers): # проверяет настройки движка
    settings = DEFAULT_SETTINGS.copy()
    invalid = []
    for name, value in data.items():
        if name not in settings:
            continue  # Не сохранять неизвестные поля, в том числе API key.
        valid = False
        if name in NUMBER_LIMITS:
            low, high = NUMBER_LIMITS[name]
            valid = type(value) is int and low <= value <= high
        elif name == "style":
            valid = isinstance(value, str) and value in STYLES
        elif name == "provider":
            valid = isinstance(value, str) and value in providers
        else:
            valid = type(value) is bool
        if valid:
            settings[name] = value
        else:
            invalid.append(name)
    if bool(settings["screen_width"]) != bool(settings["screen_height"]):
        settings["screen_width"] = settings["screen_height"] = 0
        invalid.append("screen size (set both dimensions or both to zero)")
    return settings, invalid



# Providers — новый источник реализует только два метода.
class BackgroundProvider(ABC):
    @abstractmethod
    def search(self, context, query): # находит изображения по контексту и запросу
        """Return a list of BackgroundCandidate objects."""

    @abstractmethod
    def get_image(self, candidate, context, stop_event=None): # получает файл выбранного изображения
        """Return a validated local Path; raise BackgroundError on failure."""


class LocalProvider(BackgroundProvider):
    def __init__(self, storage, log): # подготавливает состояние и зависимости
        self.storage = storage
        self.log = log
        self._probes = {}

    def search(self, context, query): # находит изображения по контексту и запросу
        if Image is None:
            raise BackgroundError(PILLOW_HELP)
        candidates = []
        root = self.storage.local_dir
        if not root.exists():
            return candidates
        for path in root.rglob("*"):
            if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
                continue
            try:
                stat = path.stat()
                key = (str(path), stat.st_mtime_ns, stat.st_size)
                if key not in self._probes:
                    self._probes[key] = inspect_image(path)
                width, height, _ = self._probes[key]
                if not fits_screen(width, height, context):
                    continue
                relative = path.relative_to(root)
                tokens = set(re.findall(r"[^\W_]+", str(relative).lower()))
                tags = {}
                for field_name, values in (
                    ("season", SEASON_QUERIES), ("time_of_day", TIME_QUERIES), ("style", STYLES)
                ):
                    matched = [v for v in values if tokens & TAG_ALIASES.get(v, {v})]
                    if len(matched) == 1:
                        tags[field_name] = matched[0]
                identifier = "local:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()
                candidates.append(BackgroundCandidate(
                    identifier, "local", str(relative), width, height,
                    path=str(path.resolve()), context=tags, storage="local", query=query,
                ))
            except (OSError, BackgroundError):
                self.log("Local image skipped: " + clean_text(path.name))
        if len(self._probes) > 1000:
            self._probes.clear()
        return candidates

    def get_image(self, candidate, context, stop_event=None): # получает файл выбранного изображения
        path = Path(candidate.path).expanduser().resolve(strict=True)
        require_fitting_image(path, context)
        return path


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): # запрещает перенаправления запросов
        # Не передавать Authorization на другой адрес при redirect.
        raise BackgroundError("Unexpected HTTP redirect; request refused")


def validate_https_url(url, hosts): # проверяет адрес источника изображения
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in hosts
                or parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError("Untrusted address")
        return url
    except (TypeError, ValueError) as error:
        raise BackgroundError("Provider returned an untrusted HTTPS address") from error


def read_response(response, limit, seconds, destination=None, stop_event=None): # читает ответ с ограничением размера и времени
    end = T.monotonic() + seconds
    received = 0
    chunks = []
    reader = getattr(response, "read1", response.read)
    while True:
        if stop_event is not None and stop_event.is_set():
            raise BackgroundError("Background operation cancelled")
        if T.monotonic() >= end:
            raise BackgroundError("Download deadline exceeded")
        try:
            chunk = reader(65536)
        except (OSError, HTTPException) as error:
            raise BackgroundError("Response was interrupted or timed out") from error
        if not chunk:
            break
        received += len(chunk)
        if received > limit:
            raise BackgroundError("Response exceeds the size limit")
        if destination is None:
            chunks.append(chunk)
        else:
            destination.write(chunk)
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            if int(length) != received:
                raise BackgroundError("Incomplete download")
        except ValueError as error:
            raise BackgroundError("Invalid Content-Length") from error
    return b"".join(chunks)


class PexelsProvider(BackgroundProvider):
    def __init__(self, storage, log): # подготавливает состояние и зависимости
        self.storage = storage
        self.log = log
        self.opener = build_opener(NoRedirects())
        self.internet = "Unknown (Pexels has not been contacted)"
        self.last_check = None

    def require_access(self): # проверяет наличие ключа Pexels
        key = os.environ.get("PEXELS_API_KEY", "").strip()
        if not key:
            raise BackgroundError("Pexels API: not configured (PEXELS_API_KEY is missing)")
        return key

    def mark_network(self, reachable): # сохраняет состояние соединения с Pexels
        self.internet = ("Online to Pexels" if reachable
                         else "Pexels unreachable (offline, timeout or connection error)")
        self.last_check = now_text()

    def request(self, url, headers): # отправляет запрос к Pexels и обрабатывает ошибки
        request = Request(url, headers={"User-Agent": f"DynamicBackgroundEngine/{ENGINE_VERSION}",
                                        "Accept-Encoding": "identity", **headers})
        try:
            response = self.opener.open(
                request, timeout=self.storage.settings["request_timeout"]
            )
            self.mark_network(True)
            return response
        except HTTPError as error:
            self.mark_network(True)
            status = error.code
            if status == 429:
                retry_at = T.time() + 3600
                raw = error.headers.get("Retry-After", "") if error.headers else ""
                try:
                    retry_at = T.time() + max(1, int(raw))
                except (TypeError, ValueError):
                    try:
                        retry_at = max(retry_at, parsedate_to_datetime(raw).timestamp())
                    except (TypeError, ValueError, OverflowError):
                        self.log("Pexels rate limit: retry in at least one hour")
                network = self.storage.data["network"]
                network["retry_at"] = max(retry_at, self.retry_at())
                self.storage.save_metadata()
            error.close()
            if status in (401, 403):
                raise BackgroundError("Pexels rejected the API key or access (HTTP "
                                      + str(status) + ")") from None
            if status == 429:
                raise BackgroundError("Pexels API rate limit reached; using cache/local") from None
            raise BackgroundError(f"Pexels HTTP error {status}") from None
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException):
            self.mark_network(False)
            raise BackgroundError("Cannot reach Pexels; using cache/local") from None

    def retry_at(self): # получает время следующей попытки Pexels
        value = self.storage.data["network"].get("retry_at", 0)
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0

    def search(self, context, query): # находит изображения по контексту и запросу
        key = self.require_access()
        cache_key = hashlib.sha256((context.signature() + query).encode()).hexdigest()
        saved = self.storage.data["searches"].get(cache_key)
        ttl = self.storage.settings["search_cache_hours"] * 3600
        if isinstance(saved, dict):
            try:
                if 0 <= T.time() - float(saved["saved_at"]) < ttl:
                    return [candidate_from_dict(item) for item in saved["candidates"]]
            except (KeyError, ValueError, TypeError, OverflowError):
                self.log("Invalid cached search ignored")
        if T.time() < self.retry_at():
            raise BackgroundError("Pexels is in a retry cooldown; using cache/local")
        url = "https://api.pexels.com/v1/search?" + urlencode({
            "query": query, "orientation": context.orientation,
            "per_page": 30, "page": 1,
        })
        self.log("Searching Pexels: " + query)
        self.log("Photos provided by Pexels: " + PEXELS_URL)
        try:
            with self.request(url, {"Authorization": key, "Accept": "application/json"}) as response:
                body = read_response(response, 2 * 1024 * 1024,
                                     self.storage.settings["download_deadline"])
                if response.headers.get("X-Ratelimit-Remaining") == "0":
                    try:
                        reset = float(response.headers.get("X-Ratelimit-Reset", "0"))
                        if math.isfinite(reset):
                            self.storage.data["network"]["retry_at"] = max(T.time() + 60, reset)
                    except ValueError:
                        self.storage.data["network"]["retry_at"] = T.time() + 3600
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("photos"), list):
                raise BackgroundError("Pexels returned invalid photo data")
            candidates = []
            for photo in payload["photos"]:
                candidate = self.photo_candidate(photo, context, query)
                if candidate is not None:
                    candidates.append(candidate)
            self.storage.data["searches"][cache_key] = {
                "saved_at": T.time(), "candidates": [asdict(c) for c in candidates],
            }
            # Bounded search-result cache, independent of downloaded images.
            while len(self.storage.data["searches"]) > 32:
                self.storage.data["searches"].pop(next(iter(self.storage.data["searches"])))
            self.storage.save_metadata()
            if not candidates:
                self.log("Pexels: no suitable full-resolution landscape images")
            return candidates
        except (BackgroundError, ValueError, UnicodeError, OSError) as error:
            self.storage.data["network"]["retry_at"] = max(
                self.retry_at(), T.time() + self.storage.settings["retry_interval"]
            )
            self.storage.save_metadata()
            if isinstance(error, BackgroundError):
                raise
            raise BackgroundError("Pexels returned damaged or incomplete search data") from None

    def photo_candidate(self, photo, context, query): # преобразует ответ Pexels в данные изображения
        try:
            width, height = int(photo["width"]), int(photo["height"])
            photo_id = str(int(photo["id"]))
            if not fits_screen(width, height, context):
                return None
            # src.landscape is only ~1200x627; use the actual original.
            url = validate_https_url(photo["src"]["original"], {"images.pexels.com"})
            photo_url = validate_https_url(photo["url"], {"www.pexels.com", "pexels.com"})
            return BackgroundCandidate(
                "pexels:" + photo_id, "pexels", clean_text(photo.get("alt") or "Landscape"),
                width, height, download_url=url, photo_id=photo_id,
                photo_url=photo_url, photographer=clean_text(photo.get("photographer", "")),
                photographer_url=clean_text(photo.get("photographer_url", "")),
                query=query, context=context.to_dict(),
            )
        except (KeyError, TypeError, ValueError, OverflowError, BackgroundError):
            return None

    def get_image(self, candidate, context, stop_event=None): # получает файл выбранного изображения
        self.require_access()
        self.storage.ensure_directories()
        url = validate_https_url(candidate.download_url, {"images.pexels.com"})
        temporary = None
        try:
            with self.request(url, {"Accept": "image/*"}) as response:
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if not mime.startswith("image/"):
                    raise BackgroundError("Pexels download is not an image")
                with tempfile.NamedTemporaryFile(
                    dir=self.storage.cache_dir, prefix=".download-", suffix=".tmp", delete=False
                ) as file:
                    temporary = Path(file.name)
                    read_response(response, MAX_IMAGE_BYTES,
                                  self.storage.settings["download_deadline"], file, stop_event)
            path = self.storage.store_download(temporary, candidate, context)
            self.log("Background downloaded: " + path.name)
            return path
        except (OSError, ValueError) as error:
            raise BackgroundError("Image download failed or was interrupted") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


# Engine — управление выбором, состоянием и одним daemon-потоком.
class BackgroundEngine: # Для интеграции Dynamic Interface может передать свои sensors/actions.
    def __init__(
        self, directory=DEFAULT_DIRECTORY, providers=None, wallpaper_setter=None,
        context_provider=None, attribution_display=None,
    ): # подготавливает состояние и зависимости
        self._activity_log = ActivityLog()
        self._operation_lock = threading.RLock()
        self._thread_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._last_error = None
        self._retry_signature = None
        self._next_retry = 0.0
        self._seen_signature = None
        self._screen = None
        self._screen_checked = 0.0
        self._current_probe = None
        self._context_provider_error = None
        names = {"auto", "local", "cache", "pexels"} | set(providers or {})
        self.storage = BackgroundStorage(directory, self.log_activity, names)
        self.local_provider = LocalProvider(self.storage, self.log_activity)
        self.providers = {"pexels": PexelsProvider(self.storage, self.log_activity)}
        self.providers.update(providers or {})
        self.context_provider = context_provider
        self.attribution_display = attribution_display
        self.wallpaper_setter = wallpaper_setter or (lambda path: set_wallpaper(path))
        self.storage.trim_cache()
        if Image is None:
            self.log_activity(PILLOW_HELP)

    @property
    def settings(self): # получает копию настроек движка
        return self.storage.settings.copy()

    def log_activity(self, message): # записывает событие в журнал
        self._activity_log.log_activity(message)

    def report_error(self, error): # сохраняет ошибку движка в журнал
        self._last_error = clean_text(error)
        self.log_activity(self._last_error)
        if self.settings["debug"]:
            self.log_activity(traceback.format_exc())

    def get_activity(self): # получает события движка
        return self._activity_log.get_activity()

    def _screen_size(self, settings): # выбирает размер экрана из настроек или датчика
        if settings["screen_width"] and settings["screen_height"]:
            return settings["screen_width"], settings["screen_height"]
        if self._screen is None or T.monotonic() - self._screen_checked >= 60:
            self._screen = get_screen_size()
            self._screen_checked = T.monotonic()
        return self._screen[:2]

    def _context_from_host(self, value, settings, width, height): # собирает контекст из данных интерфейса
        if isinstance(value, BackgroundContext):
            season = value.season
            time_of_day = value.time_of_day
            extras = copy.deepcopy(value.extras)
        elif isinstance(value, dict):
            season = value.get("season", value.get("current_season"))
            time_of_day = value.get("time_of_day", value.get("time"))
            extras = copy.deepcopy(value.get("extras", {}))
            if not isinstance(extras, dict):
                extras = {}
        else:
            raise BackgroundError("Context provider must return BackgroundContext or dict")
        return BackgroundContext(
            season, time_of_day, settings["style"], # type: ignore
            width=width, height=height, extras=extras,
        )

    def get_context(self, when: DT.datetime | None = None) -> BackgroundContext: # собирает контекст для выбора фона
        settings = self.settings
        width, height = self._screen_size(settings)
        # Explicit --at/test datetime intentionally bypasses the host sensor provider.
        if when is None and self.context_provider is not None:
            try:
                context = self._context_from_host(
                    self.context_provider(), settings, width, height
                )
                self._context_provider_error = None
                return context
            except Exception as error:
                message = "Context provider unavailable; internal sensors used: " + clean_text(error)
                if message != self._context_provider_error:
                    self.log_activity(message)
                    self._context_provider_error = message
        return BackgroundContext(
            get_current_season(when), get_time_of_day(when), settings["style"],
            width=width, height=height,
        )

    def pexels_persistent_attribution_available(self): # проверяет подключение отображения авторства
        return self.settings["pexels_auto_enabled"] and callable(self.attribution_display)

    @staticmethod
    def attribution_for(candidate): # собирает сведения об авторе изображения
        if candidate.provider != "pexels":
            return None
        photographer = candidate.photographer.strip() if candidate.photographer else ""
        text = (f"Photo by {photographer} on Pexels" if photographer
                else "Photo provided by Pexels")
        return {
            "provider": "Pexels",
            "text": text,
            "photographer": photographer,
            "photo_url": candidate.photo_url,
            "pexels_url": PEXELS_URL,
        }

    def confirm_persistent_attribution(self, candidate): # подтверждает отображение авторства фона
        attribution = self.attribution_for(candidate)
        if attribution is None:
            return True
        if not self.pexels_persistent_attribution_available():
            raise BackgroundError(
                "Automatic/random Pexels backgrounds require persistent attribution in "
                "the Dynamic Interface. Use Show candidates to select a Pexels image "
                "manually, or connect an attribution_display callback."
            )
        try:
            confirmed = self.attribution_display(copy.deepcopy(attribution)) # type: ignore
        except Exception as error:
            raise BackgroundError(
                "Dynamic Interface could not display Pexels attribution"
            ) from error
        if confirmed is not True:
            raise BackgroundError(
                "Dynamic Interface did not confirm persistent Pexels attribution"
            )
        return True

    def clear_persistent_attribution(self): # очищает отображение авторства прошлого фона
        if not callable(self.attribution_display):
            return
        try:
            self.attribution_display(None)
        except Exception as error:
            self.log_activity("Could not clear attribution display: " + clean_text(error))

    def register_provider(self, name, provider): # подключает источник изображений
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in {"auto", "local", "cache"}:
            raise BackgroundError("Invalid or reserved provider name")
        if not isinstance(provider, BackgroundProvider):
            raise BackgroundError("Provider must implement BackgroundProvider")
        with self._operation_lock:
            self.providers[name] = provider # type: ignore

    def update_settings(self, **changes): # проверяет и применяет изменения настроек
        with self._operation_lock:
            if set(changes) - set(DEFAULT_SETTINGS):
                self.log_activity("Unknown setting; no settings changed")
                return False
            settings, invalid = validated_settings(
                {**self.settings, **changes}, {"auto", "local", "cache"} | set(self.providers)
            )
            if invalid:
                self.log_activity("Invalid settings: " + ", ".join(invalid))
                return False
            self.storage.settings = settings
            self.storage.data["history"] = self.storage.data["history"][-settings["history_limit"]:]
            saved = self.storage.save_settings()
            self.storage.trim_cache()
            self.storage.save_metadata()
            self._next_retry = 0.0
        if "auto_mode" in changes:
            if settings["auto_mode"]:
                self.start()
            else:
                self.stop()
        return saved

    def get_path(self): # получает путь к текущему изображению
        current = self.storage.data.get("current")
        if not current:
            return None
        try:
            path = Path(current["path"])
            return str(path) if path.is_file() else None
        except (OSError, ValueError):
            return None

    def current_is_valid(self): # проверяет файл текущего фона
        path = self.get_path()
        if path is None:
            return False
        try:
            stat = Path(path).stat()
            probe = (path, stat.st_size, stat.st_mtime_ns)
            if probe != self._current_probe:
                inspect_image(path, full=True)
                self._current_probe = probe
            return True
        except (OSError, BackgroundError):
            return False

    def score_candidate(self, candidate, context): # оценивает соответствие изображения контексту
        score = 0.0
        for name, weight in (("season", 40), ("time_of_day", 40), ("style", 20)):
            value = candidate.context.get(name)
            if value:
                score += weight if value == getattr(context, name) else -weight
        ratio = candidate.width / candidate.height
        score -= 15 * abs(math.log(ratio / (context.width / context.height)))
        if candidate.storage == "cache":
            score += 10
        elif candidate.storage == "local":
            score -= 5
        return score

    def order_candidates(self, candidates, context): # сортирует изображения с учётом контекста и истории
        # Удалить дубликаты; кэш всегда идёт раньше того же remote photo ID.
        unique = {}
        for candidate in candidates:
            unique.setdefault(candidate.id, candidate)
        recent = {h["id"] for h in self.storage.data["history"]}
        current = self.storage.data.get("current")
        current_id = current["candidate"]["id"] if current else None
        ordered = list(unique.values())
        random.shuffle(ordered)
        # Случайный порядок среди близких оценок, текущая картинка — последняя.
        ordered.sort(key=lambda c: (
            c.id == current_id, c.id in recent,
            -round(self.score_candidate(c, context) / 10),
        ))
        return ordered

    def collect_candidates(self, context, try_online=False, allow_pexels=True): # собирает изображения из выбранных источников
        if Image is None:
            raise BackgroundError(PILLOW_HELP)
        query = build_background_query(context)
        source = self.settings["provider"]
        if source == "pexels" and not allow_pexels:
            raise BackgroundError(
                "Pexels cannot be auto-selected without persistent attribution. "
                "Use Show candidates for manual selection."
            )
        if source == "local":
            return self.order_candidates(self.local_provider.search(context, query), context)
        cached = self.storage.cached_candidates(context)
        if not allow_pexels:
            cached = [candidate for candidate in cached if candidate.provider != "pexels"]
        if source == "cache":
            return self.order_candidates(cached, context)
        recent = {h["id"] for h in self.storage.data["history"]}
        current = self.storage.data.get("current")
        if current:
            recent.add(current["candidate"]["id"])
        fresh_match = any(
            c.id not in recent and all(c.context.get(k) == getattr(context, k)
                                      for k in ("season", "time_of_day", "style"))
            for c in cached
        )
        candidates = list(cached)
        if try_online or not fresh_match:
            names = list(self.providers) if source == "auto" else [source]
            for name in names:
                if name == "pexels" and not allow_pexels:
                    continue
                provider = self.providers.get(name)
                if provider is None:
                    continue
                try:
                    candidates.extend(provider.search(context, query))
                except Exception as error:
                    self.report_error(error)
        try:
            candidates.extend(self.local_provider.search(context, query))
        except (OSError, BackgroundError) as error:
            self.report_error(error)
        return self.order_candidates(candidates, context)

    def get_candidates(self, context=None, limit=5) -> list[BackgroundCandidate]: # получает список подходящих изображений
        """Return candidates for a visible selection/search flow.

        Pexels candidates are permitted here because the caller is expected to show
        Pexels/photographer attribution before the user selects an image.
        """
        with self._operation_lock:
            try:
                context = context or self.get_context()
                if isinstance(context, dict):
                    context = BackgroundContext(**context)
                return self.collect_candidates(context, allow_pexels=True)[:max(1, min(30, limit))]
            except Exception as error:
                self.report_error(error)
                return []

    def resolve_candidate(self, candidate, context, stop_event): # получает проверенный файл выбранного фона
        if candidate.storage == "cache":
            path = self.storage.managed_path(Path(candidate.path).name)
            try:
                require_fitting_image(path, context)
            except BackgroundError:
                # Удалять можно только собственный проверенный путь, не local.
                if Image is not None:
                    path.unlink(missing_ok=True)
                    self.storage.data["images"].pop(path.name, None)
                    self.storage.save_metadata()
                raise
            return path
        if candidate.storage == "local":
            return self.local_provider.get_image(candidate, context, stop_event)
        provider = self.providers.get(candidate.provider)
        if provider is None:
            raise BackgroundError("Image provider is no longer available")
        return provider.get_image(candidate, context, stop_event)

    def apply_candidate(
        self, candidate, context, stop_event=None, selection_attributed=False
    ): # применяет фон и сохраняет его данные
        persistent_credit = False
        if candidate.provider == "pexels" and not selection_attributed:
            # Automatic/random serving requires attribution worked into the host display.
            self.confirm_persistent_attribution(candidate)
            persistent_credit = True
        prepared = None
        try:
            source = self.resolve_candidate(candidate, context, stop_event)
            prepared = self.storage.prepare_wallpaper(source, context)
            if stop_event is not None and stop_event.is_set():
                raise BackgroundError("Background operation cancelled")
            try:
                applied = self.wallpaper_setter(str(prepared))
            except Exception as error:
                self.log_activity("Wallpaper setter error: " + clean_text(error))
                applied = False
            if not applied:
                # Setter failure is independent of the image; do not retry 30 photos.
                raise BackgroundError("Wallpaper was not changed; see Activity for the macOS error")
        except Exception:
            if prepared is not None:
                prepared.unlink(missing_ok=True)
            if persistent_credit:
                self.clear_persistent_attribution()
            raise

        attribution = self.attribution_for(candidate)
        current = {
            "path": str(prepared), "candidate": asdict(candidate),
            "context": context.to_dict(), "signature": self.selection_signature(context),
            "changed_at": now_text(), "attribution": attribution,
        }
        self.storage.data["current"] = current
        self.storage.data["history"].append({
            "id": candidate.id, "provider": candidate.provider,
            "title": candidate.title, "photo_url": candidate.photo_url,
            "photographer": candidate.photographer, "query": candidate.query,
            "changed_at": current["changed_at"],
        })
        self.storage.data["history"] = self.storage.data["history"][-self.settings["history_limit"]:]
        # Если запись JSON не удалась, сохранить и прежний файл для старой metadata.
        if self.storage.save_metadata():
            self.storage.cleanup_current(prepared)
        self.storage.trim_cache()
        self._last_error = None
        self._next_retry = 0.0
        self.log_activity("Wallpaper changed: " + candidate.title)
        if candidate.provider == "pexels":
            credit = attribution["text"] if attribution else "Photo provided by Pexels"
            self.log_activity(credit + ": " + (candidate.photo_url or PEXELS_URL))
        else:
            self.clear_persistent_attribution()
        return str(prepared)

    def change_background(
        self, context=None, candidate=None, stop_event=None, selection_attributed=False
    ) -> str | None: # выбирает и меняет текущий фон
        """Change wallpaper.

        selection_attributed=True is reserved for a visible manual-selection flow that
        already showed Pexels and photographer attribution for the chosen candidate.
        Random/automatic Pexels selection requires attribution_display instead.
        """
        with self._operation_lock:
            try:
                if stop_event is not None and stop_event.is_set():
                    return None
                context = context or self.get_context()
                if isinstance(context, dict):
                    context = BackgroundContext(**context)
                allow_pexels = (
                    selection_attributed or self.pexels_persistent_attribution_available()
                )
                if (candidate is None and self.settings["provider"] == "pexels"
                        and not allow_pexels):
                    raise BackgroundError(
                        "Pexels random/automatic change needs persistent attribution. "
                        "Use Show candidates and choose a Pexels image manually."
                    )
                attempted = set()
                downloads = 0
                # Повторный проход нужен, если подходящий кэш оказался повреждён.
                for online in (False, True):
                    candidates = ([candidate] if candidate else self.collect_candidates(
                        context, online, allow_pexels=allow_pexels
                    ))
                    for item in candidates:
                        attempt_id = (item.id, item.storage)
                        if attempt_id in attempted:
                            continue
                        attempted.add(attempt_id)
                        if stop_event is not None and stop_event.is_set():
                            return None
                        if item.storage == "remote":
                            if downloads >= 3:
                                continue
                            downloads += 1
                        try:
                            return self.apply_candidate(
                                item, context, stop_event,
                                selection_attributed=selection_attributed,
                            )
                        except BackgroundError as error:
                            self.report_error(error)
                            if str(error).startswith("Wallpaper was not changed"):
                                return None
                        except (OSError, ValueError) as error:
                            self.report_error(error)
                    if candidate is not None or self.settings["provider"] in ("local", "cache"):
                        break
                self.log_activity(
                    "No usable background. Add landscape images at least "
                    f"{context.width}x{context.height} to {self.storage.local_dir}."
                )
                if self._last_error is None:
                    self._last_error = "No suitable images in the selected sources"
                return None
            except Exception as error:
                self.report_error(error)
                return None
            finally:
                self.storage.trim_cache()

    def check_once(self, stop_event=None): # проверяет необходимость смены фона
        """Один шаг автоматики; полезен для будущего connector и проверок."""
        with self._operation_lock:
            context = self.get_context()
            signature = self.selection_signature(context)
            current = self.storage.data.get("current")
            if current and current["signature"] == signature and self.current_is_valid():
                return False
            if self._seen_signature != signature:
                self.log_activity(f"Context changed: {context.season} / {context.time_of_day} / {context.style}")
                self._seen_signature = signature
            if signature == self._retry_signature and T.monotonic() < self._next_retry:
                return False
            changed = self.change_background(context, stop_event=stop_event)
            if not changed:
                self._retry_signature = signature
                self._next_retry = T.monotonic() + self.settings["retry_interval"]
            return bool(changed)

    def selection_signature(self, context): # создаёт ключ контекста и источника фона
        return context.signature() + "|provider=" + self.settings["provider"]

    def _run(self): # проверяет фон до остановки движка
        while not self._stop_event.is_set():
            try:
                self.check_once(self._stop_event)
            except Exception as error:
                self.report_error(error)
            self._stop_event.wait(self.settings["check_interval"])
        self.log_activity("Background engine stopped")

    def start(self): # запускает автоматическую смену фона
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return not self._stop_event.is_set()
            self._stop_event.clear()
            self.storage.settings["auto_mode"] = True
            self.storage.save_settings()
            self._thread = threading.Thread(target=self._run, name="DynamicBackgroundEngine", daemon=True)
            self._thread.start()
            self.log_activity("Background engine started")
            return True

    def stop(self, timeout=2.0, save_preference=True): # останавливает автоматическую смену фона
        with self._thread_lock:
            thread = self._thread
            self._stop_event.set()
            if save_preference:
                self.storage.settings["auto_mode"] = False
                self.storage.save_settings()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        stopped = thread is None or not thread.is_alive()
        if not stopped:
            self.log_activity("Stopping: waiting for the current bounded request to finish")
        return stopped

    def get_status(self): # собирает текущее состояние движка
        context = self.get_context()
        running = self._thread is not None and self._thread.is_alive()
        state = "STOPPING" if running and self._stop_event.is_set() else ("RUNNING" if running else "READY")
        pexels = self.providers.get("pexels")
        try:
            cache_count = len(self.storage.cache_files())
        except (OSError, BackgroundError):
            cache_count = 0
        current = copy.deepcopy(self.storage.data.get("current"))
        return {
            "version": ENGINE_VERSION,
            "engine": state, "auto_mode": running and not self._stop_event.is_set(),
            "auto_mode_saved": self.settings["auto_mode"], "context": context.to_dict(), # type: ignore
            "query": build_background_query(context), "provider": self.settings["provider"],
            "internet": getattr(pexels, "internet", "Unknown"),
            "internet_last_check": getattr(pexels, "last_check", None),
            "pexels_api": "configured" if os.environ.get("PEXELS_API_KEY", "").strip() else "not configured",
            "pexels_manual_selection": "available" if os.environ.get("PEXELS_API_KEY", "").strip() else "API key required",
            "pexels_automatic": (
                "available with persistent attribution"
                if self.pexels_persistent_attribution_available()
                else "manual selection only; persistent attribution display not connected"
            ),
            "screen_source": "Settings" if self.settings["screen_width"] else self._screen[2], # type: ignore
            "pillow": "available" if Image is not None else "missing",
            "current": current, "current_file_exists": self.get_path() is not None,
            "cache_count": cache_count, "cache_limit": self.settings["cache_limit"],
            "history_count": len(self.storage.data["history"]),
            "last_error": self._last_error, "directory": str(self.storage.directory),
            "attribution": current.get("attribution") if isinstance(current, dict) else None,
            "pexels_policy": PEXELS_WALLPAPER_HELP,
        }


# Public API — обёртки сохраняют прежние импорты; связывание находится в connector.py.
def configure_background_engine(
    directory=DEFAULT_DIRECTORY, context_provider=None, wallpaper_setter=None,
    attribution_display=None, providers=None,
): # подключает движок к динамическому интерфейсу
    from main.connector import configure_background_engine as configure
    return configure(
        directory=directory, context_provider=context_provider,
        wallpaper_setter=wallpaper_setter, attribution_display=attribution_display,
        providers=providers,
    )


def get_engine(): # получает общий экземпляр движка
    from main.connector import get_engine as get_configured_engine
    return get_configured_engine()


def get_background_context(when: DT.datetime | None = None) -> dict: # получает контекст общего движка
    from main.connector import get_background_context as get_context
    return get_context(when)


def get_background_path() -> str | None: # получает путь к текущему фону
    from main.connector import get_background_path as get_path
    return get_path()


def get_background_attribution() -> dict | None: # получает сведения об авторе текущего фона
    from main.connector import get_background_attribution as get_attribution
    return get_attribution()


def change_background(context: BackgroundContext | dict | None = None) -> str | None: # меняет фон через общий движок
    from main.connector import change_background as change
    return change(context)


def start_background_engine() -> bool: # запускает общий движок
    from main.connector import start_background_engine as start
    return start()


def stop_background_engine(timeout: float = 2.0) -> bool: # останавливает общий движок
    from main.connector import stop_background_engine as stop
    return stop(timeout)


def get_background_status() -> dict: # получает состояние общего движка
    from main.connector import get_background_status as get_status
    return get_status()


def terminal_menu(engine=None): # открывает меню движка из settings.py
    from main.settings import terminal_menu as show_menu
    return show_menu(engine)


def main(argv=None): # запускает терминальный интерфейс движка
    from main.settings import background_main
    return background_main(argv)


if __name__ == "__main__":
    sys.exit(main())
