"""Offline regression checks; all files stay in temporary directories.

Run from the project folder: python3 -B tests/test_refactor.py
Optional: DYNAMIC_INTERFACE_PROJECT=/path/to/project python3 test_refactor.py
"""

import datetime as DT
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from PIL import Image


PROJECT = Path(os.environ.get(
    "DYNAMIC_INTERFACE_PROJECT",
    str(Path(__file__).resolve().parents[1]),
)).resolve()
sys.path.insert(0, str(PROJECT))
core = importlib.import_module("main.background_engine")
sensors = importlib.import_module("main.sensors")
logs = importlib.import_module("main.activity_logs")
connector = importlib.import_module("main.connector")
settings = importlib.import_module("main.settings")
actions = importlib.import_module("main.actions")


class FakeResponse(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}


class RefactorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dynamic-interface-check-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        # Fail closed: a missed mock must never contact a service or the desktop.
        for target in ("socket.socket.connect", "subprocess.run", "subprocess.check_output"):
            guard = patch(target, side_effect=AssertionError("Unexpected external operation"))
            guard.start()
            self.addCleanup(guard.stop)
        env = patch.dict(os.environ, {"PEXELS_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.setter = Mock(return_value=True)
        self.engine = core.BackgroundEngine(self.directory, wallpaper_setter=self.setter)
        self.addCleanup(self.engine.stop)
        self.assertTrue(self.engine.update_settings(
            provider="local", screen_width=320, screen_height=180,
        ))
        self.context = core.BackgroundContext("winter", "night", width=320, height=180)

    def image(self, name, size=(640, 360), color=(20, 80, 140)):
        path = self.engine.storage.local_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.new("RGB", size, color) as source:
            source.save(path)
        return path

    def test_context_validation_and_stable_signature(self):
        values = self.context.to_dict()
        restored = core.BackgroundContext(**values)
        self.assertEqual(self.context.signature(), restored.signature())
        for changes in ({"season": "bad"}, {"time_of_day": "noon"},
                        {"style": "bad"}, {"orientation": "portrait"},
                        {"width": 0}, {"height": 16385}):
            with self.subTest(changes=changes), self.assertRaises(core.BackgroundError):
                core.BackgroundContext(**{**values, **changes})
        query = core.build_background_query(self.context)
        self.assertIn("winter", query)
        self.assertIn("night", query)

    def test_sensors_accept_explicit_date_and_time_boundaries(self):
        for hour, expected in ((0, "night"), (5, "night"), (6, "morning"),
                               (11, "morning"), (12, "day"), (17, "day"),
                               (18, "evening"), (21, "evening"), (22, "night")):
            self.assertEqual(sensors.get_time_of_day(DT.datetime(2026, 6, 1, hour)), expected)
        for month, expected in ((1, "winter"), (3, "spring"), (6, "summer"),
                                (9, "fall"), (12, "winter")):
            self.assertEqual(sensors.get_current_season(DT.datetime(2026, month, 1)), expected)
        self.assertIsNotNone(DT.datetime.fromisoformat(sensors.now_text()).tzinfo)

    def test_explicit_context_datetime_bypasses_host_provider(self):
        host = Mock(return_value={"season": "summer", "time_of_day": "day"})
        self.engine.context_provider = host
        context = self.engine.get_context(DT.datetime(2026, 12, 15, 23))
        self.assertEqual((context.season, context.time_of_day), ("winter", "night"))
        host.assert_not_called()
        self.assertEqual(self.engine.get_context().season, "summer")
        host.assert_called_once_with()

    def test_activity_is_bounded_isolated_and_redacts_secret(self):
        first, second = logs.ActivityLog(), logs.ActivityLog()
        with patch.dict(os.environ, {"PEXELS_API_KEY": "local-test-secret"}):
            first.log_activity("hello\nlocal-test-secret\x00")
            self.assertEqual(first.get_activity()[0]["message"], "hello[REDACTED]")
            self.assertEqual(logs.clean_text("ab\ncd", 3), "abc")
        self.assertEqual(second.get_activity(), [])
        for number in range(70):
            self.engine.log_activity(str(number))
        events = self.engine.get_activity()
        self.assertEqual(len(events), 50)
        self.assertEqual(events[-1]["message"], "69")
        events.clear()
        self.assertEqual(len(self.engine.get_activity()), 50)

    def test_local_selection_resize_metadata_and_restart(self):
        original = self.image("winter/night_landscape.png", (800, 400))
        self.image("too_small.png", (100, 80))
        (self.engine.storage.local_dir / "broken.jpg").write_bytes(b"broken image")
        candidates = self.engine.get_candidates(self.context)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].context["season"], "winter")
        self.assertEqual(candidates[0].context["time_of_day"], "night")
        prepared = self.engine.change_background(self.context, candidates[0])
        self.assertIsNotNone(prepared, self.engine.get_activity())
        self.setter.assert_called_once_with(prepared)
        with Image.open(prepared) as image:
            self.assertEqual(image.size, (320, 180))
            self.assertEqual(image.format, "JPEG")
        with Image.open(original) as image:
            self.assertEqual(image.size, (800, 400))
        data = json.loads((self.directory / "metadata.json").read_text())
        self.assertEqual(data["current"]["path"], prepared)
        self.assertEqual(data["history"][0]["id"], candidates[0].id)
        restored = core.BackgroundEngine(self.directory, wallpaper_setter=self.setter)
        self.addCleanup(restored.stop)
        self.assertEqual(restored.get_path(), prepared)
        self.assertTrue(restored.current_is_valid())

    def test_full_inspection_preserves_exif_dimensions_for_jpeg_and_png(self):
        for suffix, image_format in (("jpg", "JPEG"), ("png", "PNG")):
            with self.subTest(format=image_format):
                path = self.directory / ("rotated." + suffix)
                with Image.new("RGB", (360, 640), (20, 80, 140)) as image:
                    exif = image.getexif()
                    exif[274] = 6
                    image.save(path, image_format, exif=exif)
                self.assertEqual(core.inspect_image(path, full=True), (640, 360, image_format))
                prepared = self.engine.storage.prepare_wallpaper(path, self.context)
                with Image.open(prepared) as image:
                    self.assertEqual(image.size, (320, 180))

    def test_full_inspection_rejects_png_with_damaged_chunk(self):
        path = self.image("damaged.png")
        data = bytearray(path.read_bytes())
        # Keep the PNG image readable, but invalidate IDAT's CRC for verify().
        chunk = data.index(b"IDAT")
        length = int.from_bytes(data[chunk - 4:chunk], "big")
        data[chunk + 4 + length] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(core.BackgroundError, "damaged image"):
            core.inspect_image(path, full=True)

    def test_replacement_cleans_previous_prepared_file_and_bounds_history(self):
        self.image("winter_night.png")
        self.assertTrue(self.engine.update_settings(history_limit=1))
        candidate = self.engine.get_candidates(self.context)[0]
        first = self.engine.change_background(self.context, candidate)
        self.assertIsNotNone(first, self.engine.get_activity())
        second = self.engine.change_background(self.context, candidate)
        self.assertNotEqual(first, second)
        self.assertFalse(Path(first).exists())
        self.assertTrue(Path(second).exists())
        self.assertEqual(len(self.engine.storage.data["history"]), 1)

    def test_failed_setter_keeps_previous_background_and_removes_new_file(self):
        self.image("winter_night.png")
        candidate = self.engine.get_candidates(self.context)[0]
        first = self.engine.change_background(self.context, candidate)
        self.assertIsNotNone(first, self.engine.get_activity())
        self.setter.return_value = False
        self.assertIsNone(self.engine.change_background(self.context, candidate))
        self.assertEqual(self.engine.get_path(), first)
        self.assertEqual(list(self.engine.storage.current_dir.iterdir()), [Path(first)])
        self.assertEqual(len(self.engine.storage.data["history"]), 1)

    def test_cancelled_change_does_not_call_wallpaper_setter(self):
        cancelled = threading.Event()
        cancelled.set()
        self.assertIsNone(self.engine.change_background(self.context, stop_event=cancelled))
        self.setter.assert_not_called()

    def test_invalid_json_backed_up_and_invalid_settings_restored(self):
        directory = self.directory / "invalid"
        directory.mkdir()
        (directory / "metadata.json").write_text("{incomplete", encoding="utf-8")
        (directory / "settings.json").write_text(json.dumps({
            "cache_limit": -10, "screen_width": 1920, "screen_height": 0,
            "provider": "missing", "api_key": "must-not-persist",
        }), encoding="utf-8")
        engine = core.BackgroundEngine(directory, wallpaper_setter=self.setter)
        self.addCleanup(engine.stop)
        self.assertEqual(engine.settings["cache_limit"], core.DEFAULT_SETTINGS["cache_limit"])
        self.assertEqual(engine.settings["screen_width"], 0)
        self.assertEqual(engine.storage.data["history"], [])
        self.assertEqual(len(list(directory.glob("metadata.broken-*.json"))), 1)
        self.assertNotIn("api_key", json.loads((directory / "settings.json").read_text()))

    def test_managed_paths_reject_arbitrary_files(self):
        for name in ("../other.jpg", "photo.jpg", "wallpaper_" + "a" * 32 + ".jpg"):
            with self.subTest(name=name), self.assertRaises(core.BackgroundError):
                self.engine.storage.managed_path(name)

    def test_start_stop_and_repeat_start_use_one_worker(self):
        entered = threading.Event()
        with patch.object(self.engine, "check_once", side_effect=lambda _: entered.set()):
            self.assertTrue(self.engine.start())
            self.assertTrue(entered.wait(2))
            worker = self.engine._thread
            self.assertTrue(self.engine.start())
            self.assertIs(self.engine._thread, worker)
            self.assertTrue(self.engine.stop(timeout=2))
            self.assertFalse(worker.is_alive())
            self.assertFalse(self.engine.settings["auto_mode"])
            self.assertEqual(self.engine.get_status()["engine"], "READY")
        self.setter.assert_not_called()

    def test_pexels_without_key_never_opens_connection(self):
        provider = self.engine.providers["pexels"]
        with patch.object(provider.opener, "open") as opened:
            with self.assertRaisesRegex(core.BackgroundError, "not configured"):
                provider.search(self.context, "winter night")
            opened.assert_not_called()

    def test_pexels_search_cache_and_network_timestamp_with_mock_http(self):
        provider = self.engine.providers["pexels"]
        payload = {"photos": [{
            "id": 123, "width": 640, "height": 360, "alt": "Winter landscape",
            "url": "https://www.pexels.com/photo/winter-123/",
            "photographer": "Sample", "photographer_url": "https://www.pexels.com/@sample/",
            "src": {"original": "https://images.pexels.com/photos/123/photo.jpeg"},
        }]}
        response = FakeResponse(json.dumps(payload).encode())
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-key"}), \
             patch.object(provider.opener, "open", return_value=response) as opened:
            first = provider.search(self.context, "winter night")
            second = provider.search(self.context, "winter night")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].id, second[0].id)
        opened.assert_called_once()
        self.assertEqual(provider.internet, "Online to Pexels")
        self.assertIsNotNone(DT.datetime.fromisoformat(provider.last_check).tzinfo)
        self.assertEqual(opened.call_args.args[0].get_header("Authorization"), "test-key")

    def test_pexels_http_errors_and_retry_cooldown(self):
        provider = self.engine.providers["pexels"]
        rate_limit = HTTPError("https://api.pexels.com/", 429, "limit", {"Retry-After": "120"}, None)
        with patch.object(provider.opener, "open", side_effect=rate_limit):
            with self.assertRaisesRegex(core.BackgroundError, "rate limit"):
                provider.request("https://api.pexels.com/", {})
        self.assertGreater(provider.retry_at(), core.T.time())
        with patch.object(provider.opener, "open", side_effect=URLError("offline")):
            with self.assertRaisesRegex(core.BackgroundError, "Cannot reach"):
                provider.request("https://api.pexels.com/", {})
        self.assertIn("unreachable", provider.internet)

    def test_mocked_remote_image_download_populates_valid_cache(self):
        provider = self.engine.providers["pexels"]
        body = io.BytesIO()
        with Image.new("RGB", (640, 360), (20, 80, 140)) as image:
            image.save(body, "JPEG")
        candidate = core.BackgroundCandidate(
            "pexels:123", "pexels", "Sample landscape", 640, 360,
            download_url="https://images.pexels.com/photos/123/photo.jpeg",
        )
        response = FakeResponse(body.getvalue(), {"Content-Type": "image/jpeg"})
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-key"}), \
             patch.object(provider.opener, "open", return_value=response):
            cached = provider.get_image(candidate, self.context)
        self.assertTrue(cached.is_file())
        self.assertEqual(cached.parent, self.engine.storage.cache_dir)
        self.assertEqual(self.engine.storage.data["images"][cached.name]["id"], "pexels:123")
        self.assertEqual(self.engine.storage.cached_candidates(self.context)[0].path, str(cached))
        self.assertEqual(list(self.engine.storage.cache_dir.glob(".download-*")), [])
        self.setter.assert_not_called()

    def test_background_menu_and_legacy_menu_exit(self):
        out = io.StringIO()
        with patch("builtins.input", side_effect=["6", "12", "13"]), redirect_stdout(out):
            settings.terminal_menu(self.engine)
        self.assertIn("BACKGROUND CONTEXT", out.getvalue())
        self.assertIn("RECENT ACTIVITY", out.getvalue())
        with patch("builtins.input", return_value="7"), redirect_stdout(out):
            settings.main()
        self.assertIn("DYNAMIC INTERFACE SETTINGS", out.getvalue())
        self.setter.assert_not_called()

    def test_background_cli_context_honors_at(self):
        out = io.StringIO()
        with redirect_stdout(out):
            result = settings.background_main([
                "--context", "--at", "2026-12-15T23:00:00", "--screen", "320x180",
                "--data-dir", str(self.directory / "cli"), "--provider", "local",
            ])
        self.assertEqual(result, 0)
        self.assertIn('"season": "winter"', out.getvalue())
        self.assertIn('"time_of_day": "night"', out.getvalue())

    def test_background_cli_rejects_invalid_at_mode(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_error:
            settings.background_main(["--status", "--at", "2026-12-15T23:00:00"])
        self.assertEqual(exit_error.exception.code, 2)

    def test_old_entrypoint_wrappers_delegate(self):
        with patch.object(settings, "background_main", return_value=9) as main:
            self.assertEqual(core.main(["--status"]), 9)
            main.assert_called_once_with(["--status"])
        with patch.object(connector, "get_engine", return_value=self.engine):
            self.assertIs(core.get_engine(), self.engine)
            self.assertEqual(core.get_background_path(), connector.get_background_path())

    def test_connector_owns_shared_singleton(self):
        with patch.object(connector, "_default_engine", None):
            engine = connector.configure_background_engine(
                directory=self.directory / "singleton", wallpaper_setter=self.setter,
            )
            self.addCleanup(engine.stop)
            self.assertIs(connector.get_engine(), engine)
            self.assertIs(core.get_engine(), engine)

    def test_action_calls_mocked_osascript_with_prepared_path(self):
        path = self.image("action.png")
        with patch.object(actions.subprocess, "run") as run:
            self.assertTrue(actions.set_wallpaper(path))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertEqual(command[-1], str(path.resolve()))
        self.assertEqual(run.call_args.kwargs["timeout"], 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
