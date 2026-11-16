import ast
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
ENV.pop('PEXELS_API_KEY', None)
checks = []


def run(name, args, text='', expected=0, contains=None):
    result = subprocess.run([sys.executable, '-B', *args], cwd=PROJECT,
                            env=ENV, input=text, text=True, capture_output=True, timeout=15)
    assert result.returncode == expected, (name, result.returncode, result.stdout, result.stderr)
    assert 'Traceback' not in result.stderr, (name, result.stderr)
    if contains:
        for part in contains:
            assert part in result.stdout, (name, part, result.stdout)
    checks.append(name)
    print('PASS:', name)


for path in [*sorted((PROJECT / 'main').glob('*.py')), PROJECT / 'main_start.py']:
    source = path.read_text()
    ast.parse(source, filename=str(path), feature_version=(3, 10))
    compile(source, str(path), 'exec')
checks.append('Syntax: 9 files; Python 3.10 grammar')

modules = ['sensors', 'activity_logs', 'rules', 'actions', 'background_engine', 'connector', 'settings']
for first in modules:
    order = [first, *[m for m in modules if m != first]]
    run('Cold import, first ' + first, ['-c', f'''
import importlib, pathlib, sys, threading
sys.modules['AppKit'] = None
before = set(pathlib.Path('.').rglob('*'))
threads = threading.active_count()
for name in {order!r}:
    importlib.import_module('main.' + name)
import main.connector as connector
import main.background_engine as engine
assert connector._default_engine is None
assert engine.stop_background_engine()
assert connector._default_engine is None
assert threading.active_count() == threads
assert set(pathlib.Path('.').rglob('*')) == before
'''])

with tempfile.TemporaryDirectory(prefix='dynamic-startup-') as directory:
    data = str(Path(directory) / 'backgrounds')
    for mode, command in [('package', ['-m', 'main.background_engine']),
                          ('script', ['main/background_engine.py'])]:
        run(mode + ' help', [*command, '--help'], contains=['--context', '--data-dir'])
        run(mode + ' status', [*command, '--status', '--data-dir', data, '--screen', '640x360'],
            contains=['BACKGROUND ENGINE STATUS', 'READY', '640x360'])
        run(mode + ' explicit context', [*command, '--context', '--at', '2026-12-15T22:00:00',
            '--data-dir', data], contains=['"season": "winter"', '"time_of_day": "night"'])
        run(mode + ' local candidates', [*command, '--candidates', '--provider', 'local',
            '--data-dir', data], contains=['BACKGROUND CANDIDATES', 'No suitable candidates'])
        run(mode + ' menu back', [*command, '--data-dir', data], text='13\n',
            contains=['DYNAMIC BACKGROUND ENGINE'])
    run('settings package menu', ['-m', 'main.settings'], text='1\n4\n7\n',
        contains=['WALLPAPER RULES', 'RECENT ACTIONS', 'Exit'])
    run('settings direct menu', ['main/settings.py'], text='7\n',
        contains=['DYNAMIC INTERFACE SETTINGS', 'Exit'])
    run('settings nested background menu', ['-c', f'''
from main.connector import configure_background_engine
from main.settings import main
engine = configure_background_engine(directory={data!r})
try:
    main()
finally:
    engine.stop()
'''], text='5\n1\n6\n12\n13\n7\n',
        contains=['BACKGROUND ENGINE STATUS', 'BACKGROUND CONTEXT', 'RECENT ACTIVITY', 'Exit'])
    run('engine status without Pillow or AppKit', ['-c', f'''
import sys
sys.modules['PIL'] = None
sys.modules['AppKit'] = None
from main.background_engine import main
raise SystemExit(main(['--status', '--data-dir', {str(Path(directory) / 'no-pillow')!r}, '--screen', '640x360']))
'''], contains=['Pillow: missing', 'BACKGROUND ENGINE STATUS'])

run('actions module import entry', ['-m', 'main.actions'])
run('connector module import entry', ['-m', 'main.connector'])
run('connector direct entry', ['main/connector.py'])
run('main_start connects sensor/rules/actions (controlled)', ['-c', '''
import runpy
from unittest.mock import patch
import main.connector as connector
calls = []
with patch.object(connector, 'start_system_information', side_effect=lambda: calls.append('sensors')), \\
     patch.object(connector, 'start_rules_informaton', side_effect=lambda: calls.append('rules')), \\
     patch.object(connector, 'start_actions', side_effect=lambda: calls.append('actions')):
    runpy.run_path('main_start.py', run_name='__main__')
assert calls == ['sensors', 'rules', 'actions'], calls
'''])
run('sensor and rule entry points schedule workers (controlled)', ['-c', '''
import runpy
from unittest.mock import patch
with patch('threading.Thread') as thread:
    runpy.run_module('main.sensors', run_name='__main__')
    assert thread.call_count == 5, thread.call_count
    assert thread.return_value.start.call_count == 5
with patch('threading.Thread') as thread:
    runpy.run_module('main.rules', run_name='__main__')
    assert thread.call_count == 3, thread.call_count
    assert thread.return_value.start.call_count == 3
'''])
print(json.dumps({'checks': len(checks), 'python': sys.version.split()[0], 'result': 'PASS'}, indent=2))
