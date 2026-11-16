#!/bin/bash
set -euo pipefail
PACKAGE_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Dynamic Background requires macOS."
  exit 1
fi
PYTHON_BIN="${DYNAMIC_BACKGROUND_PYTHON:-python3}"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  echo "Install Python 3.10 or later from python.org, then open START.command again."
  exit 1
fi
if [[ ! -x "$PACKAGE_DIR/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$PACKAGE_DIR/.venv"
fi
if ! "$PACKAGE_DIR/.venv/bin/python" -c 'from PIL import Image, ImageOps' >/dev/null 2>&1; then
  "$PACKAGE_DIR/.venv/bin/python" -m pip install -r "$PACKAGE_DIR/requirements.txt"
fi
cd "$PACKAGE_DIR"
exec "$PACKAGE_DIR/.venv/bin/python" -m main.background_engine "$@"
