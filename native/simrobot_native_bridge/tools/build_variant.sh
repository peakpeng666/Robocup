#!/usr/bin/env bash
# Build a native-bridge variant's SimRobot targets (Ninja/Release, clang via B-Human defaults).
#
# Usage: build_variant.sh <variant-name> [jobs]
#
# Refuses to build if the variant's source fingerprint no longer matches
# variant.json (accidental edits invalidate receipts). Products land inside the
# variant under Build/Linux/SimRobot/Release — never in bhuman-local.
set -euo pipefail

BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_ROOT="$BRIDGE_ROOT/work"

name="${1:?usage: build_variant.sh <variant-name> [jobs]}"
jobs="${2:-12}"
root="$WORK_ROOT/$name"
[ -f "$root/variant.json" ] || { echo "ERROR: no variant.json under $root (create it with tools/make_variant.py)" >&2; exit 2; }

echo "== fingerprint check =="
python3 - "$root" "$BRIDGE_ROOT/tools" <<'PYEOF'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from make_variant import tree_manifest, manifest_digest  # noqa: E402
root = Path(sys.argv[1])
data = json.loads((root / "variant.json").read_text())
current = manifest_digest(tree_manifest(root))
if current != data["source_sha256"]:
    print(f"ERROR: variant source fingerprint changed: expected {data['source_sha256']}, got {current}", file=sys.stderr)
    sys.exit(3)
print(f"fingerprint OK ({current[:16]}…)")
PYEOF

build_dir="$root/_builds/simrobot-Release"
mkdir -p "$build_dir"
stamp="$(date +%Y%m%d_%H%M%S)"
log="$build_dir/console-$stamp.log"
receipt="$build_dir/build.json"

echo "== configure =="
echo "+ cmake -S Make/CMake -B _builds/simrobot-Release -G Ninja -DCMAKE_BUILD_TYPE=Release"
CCACHE_DISABLE=1 cmake -S "$root/Make/CMake" -B "$build_dir" -G Ninja -DCMAKE_BUILD_TYPE=Release \
  2>&1 | tee "$log"

echo "== build (jobs=$jobs) =="
CCACHE_DISABLE=1 cmake --build "$build_dir" --parallel "$jobs" \
  --target SimRobot SimulatedRobot SimRobotCore3 2>&1 | tee -a "$log"

echo "== products =="
prod_dir="$root/Build/Linux/SimRobot/Release"
status=PASS
for f in SimRobot libSimulatedRobot.so libSimRobotCore3.so; do
  if [ -f "$prod_dir/$f" ]; then
    sha=$(sha256sum "$prod_dir/$f" | cut -d' ' -f1)
    size=$(stat -c%s "$prod_dir/$f")
    echo "OK  $f  $size  $sha"
  else
    echo "MISSING  $f"
    status=FAIL
  fi
done

python3 - "$root" "$stamp" "$status" "$jobs" "$prod_dir" <<'PYEOF' >> "$receipt.tmp"
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
root, stamp, status, jobs, prod_dir = sys.argv[1:6]
tools = [t.split()[0:2] + [subprocess.run([t.split()[0], "--version"], capture_output=True, text=True).stdout.splitlines()[0]] for t in ("cmake x", "ninja x", "clang++ x")]
receipt = {
    "schema": "bridge.build/1", "variant": root.split("/")[-1], "stamp": stamp,
    "status": status, "jobs": int(jobs), "built_at": datetime.now(timezone.utc).isoformat(),
    "products": {},
    "log": f"_builds/simrobot-Release/console-{stamp}.log",
}
for f in ("SimRobot", "libSimulatedRobot.so", "libSimRobotCore3.so"):
    p = Path(prod_dir) / f
    receipt["products"][f] = ({"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "size": p.stat().st_size}
                              if p.is_file() else {"missing": True})
print(json.dumps(receipt, indent=2))
PYEOF
mv "$receipt.tmp" "$receipt"

# Small tracked summary in evidence/ (heavy console log stays in the variant).
evdir="$BRIDGE_ROOT/evidence/${stamp}-build-${name}"
mkdir -p "$evdir"
cp "$receipt" "$evdir/build.json"
tail -40 "$log" > "$evdir/console-tail.log"
echo "receipt: $receipt"
echo "evidence: $evdir"
[ "$status" = PASS ]
