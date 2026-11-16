"""A fresh installation never reads or writes author-specific source data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class UserPathsTests(unittest.TestCase):
    def test_runtime_paths_use_one_external_root_without_import_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'new user data'
            code = """
import json
from main.paths import DATA_DIR, BACKGROUND_DIR, CONFIG_DIR
from main.background_engine import DEFAULT_DIRECTORY
from main.settings import CONFIG_FILE
from main.rules import RULES_FILE
print(json.dumps([str(DATA_DIR),str(BACKGROUND_DIR),str(CONFIG_DIR),str(DEFAULT_DIRECTORY),str(CONFIG_FILE),str(RULES_FILE)]))
"""
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                env={**os.environ, 'DYNAMIC_BACKGROUND_DATA_DIR': str(data)},
                check=True, capture_output=True, text=True)
            paths = json.loads(result.stdout)
            self.assertEqual(paths[0], str(data))
            self.assertEqual(paths[1], paths[3])
            self.assertEqual(paths[4], paths[5])
            self.assertTrue(all(Path(p).is_relative_to(data) for p in paths))
            self.assertFalse(data.exists())

if __name__ == '__main__':
    unittest.main()
