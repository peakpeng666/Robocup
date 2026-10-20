"""Keep pip Isaac Sim's shortcut generator from replacing the managed launcher."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import sysconfig
import tempfile

target = Path(sysconfig.get_paths()['purelib']) / 'isaacsim/exts/isaacsim.app.setup/isaacsim/app/setup/extension.py'
original = target.read_text()
marker = '/exts/isaacsim.app.setup/createDesktopIcon'
if marker in original:
    sys.exit(0)
anchor = '        app_utils.create_desktop_icon(self._app, self._ext_manager, ext_id)'
if original.count(anchor) != 1 or 'self._settings: ISettings = carb.settings.get_settings()' not in original:
    raise RuntimeError(f'Unrecognized desktop generator in {target}; review required')
replacement = ('        # Local: the workstation maintains its own desktop launcher.\n'
               '        if self._settings.get("/exts/isaacsim.app.setup/createDesktopIcon") is not False:\n'
               '    ' + anchor)
patched = original.replace(anchor, replacement)
backup = Path(__file__).parent / 'gui-app-setup.original.py'
if not backup.exists():
    backup.write_text(original)
# Atomic replacement detaches the venv file from uv's shared hardlink cache.
fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.desktop-guard-')
try:
    with os.fdopen(fd, 'w') as output:
        output.write(patched)
    os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
    os.replace(temporary, target)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print(json.dumps({'patched': str(target),
                  'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
                  'patched_sha256': hashlib.sha256(patched.encode()).hexdigest()}))
