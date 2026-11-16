"""User-owned state; importing this module has no filesystem side effects."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DYNAMIC_BACKGROUND_DATA_DIR") or
                Path.home() / "Library/Application Support/DynamicBackground").expanduser()
BACKGROUND_DIR = DATA_DIR / "backgrounds"
CONFIG_DIR = DATA_DIR / "config"
