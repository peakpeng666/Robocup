#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
"$BH_PY" -B - <<'CHECK'
import ctypes, importlib.metadata as m, json, site, sys, sysconfig
ctypes.CDLL('libpython3.8.so.1.0')
assert sys.version_info[:3] == (3, 8, 20)
assert site.ENABLE_USER_SITE is False
report = {'python': sys.executable, 'version': sys.version,
          'libdir': sysconfig.get_config_var('LIBDIR'),
          'packages': {p: m.version(p) for p in ['torch','isaacgym','numpy','onnx','onnxruntime']}}
print(json.dumps(report, indent=2))
CHECK
"${UV_BIN:-$HOME/.local/bin/uv}" pip check --python "$BH_PY"
echo "Interpreter/dependency checks passed. GPU probe is a separate explicit command."
