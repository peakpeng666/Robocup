#!/usr/bin/env bash
# Restore the recorded project environment; never upgrades system packages.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$HOME/.venvs/bh-gym}"
case "$TARGET" in
 /*/bh-gym|/*/bh-gym-*) ;;
 *) echo "Choose a dedicated bh-gym or bh-gym-* environment path" >&2; exit 2 ;;
esac
UV="${UV_BIN:-$HOME/.local/bin/uv}"
export UV_CACHE_DIR="$ROOT/cache/uv"
WHEEL="$ROOT/downloads/torch-2.3.0a0+git63d5e92-cp38-cp38-linux_x86_64.whl"
ARCHIVE="$ROOT/downloads/IsaacGym_Preview_4_Package.tar.gz"
"$UV" --version
python3 -B - "$WHEEL" "$ARCHIVE" <<'PY'
import hashlib, pathlib, sys
expected = ['6a9707962e83ededded35df45df0149951b8276df37035761ba61173428c1512',
            'c51d77ac1144b91b356f439c7313d8d59468147e37187ebffe7cdbc3154fdb8f']
for filename, wanted in zip(sys.argv[1:], expected):
    digest = hashlib.sha256()
    with open(filename, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != wanted:
        raise SystemExit('Archive mismatch: ' + filename)
print('Downloaded artifact identity checks passed (self-recorded hashes).')
PY
if [[ ! -f "$ROOT/third_party/isaacgym/python/setup.py" ]]; then
 if [[ -e "$ROOT/third_party/isaacgym" ]]; then
  echo "Incomplete existing Isaac Gym directory; inspect it before restoring" >&2
  exit 2
 fi
 python3 -B - "$ARCHIVE" <<'PY'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or path.parts[0] != 'isaacgym':
            raise SystemExit('Unexpected member in the pinned official archive')
PY
 mkdir -p "$ROOT/third_party"
 tar -xzf "$ARCHIVE" -C "$ROOT/third_party"
 patch --batch --forward -p1 -d "$ROOT/third_party/isaacgym" -i "$ROOT/patches/isaacgym-optional-vision.patch"
fi
if [[ ! -e "$TARGET" ]]; then
 "$UV" venv --python 3.8.20 "$TARGET"
fi
"$TARGET/bin/python" -B -c 'import sys; assert sys.version_info[:3] == (3,8,20), sys.version'
# The lock lists the full installed closure. Avoid resolving torchvision into
# an incompatible torch replacement; dependency health is checked afterwards.
"$UV" pip install --python "$TARGET/bin/python" --no-deps "$WHEEL" -r "$ROOT/manifests/requirements.lock"
"$UV" pip install --python "$TARGET/bin/python" --no-deps --no-build-isolation -e "$ROOT/third_party/isaacgym/python"
"$UV" pip check --python "$TARGET/bin/python"
echo "Installed recorded candidate. Run run_env_check.sh with BH_PY=$TARGET/bin/python."
