#!/usr/bin/env python3
"""Single launch entry for the K1 SimRobot bridge. Backend is explicit:

  --backend bhuman   official local entry: bhuman/start-bhuman.sh (gait|match ...)
  --backend arm16    forge ARM/QEMU 1.6 route, invoked as-is (forge/bin/forge ...)
  --backend native17 the native 1.7 core bridge (variant SimRobot; not integrated yet)

Arguments after `--` are passed through unchanged to the selected backend.

Examples:
  run_native_bridge.py --backend bhuman -- gait --seconds 30 --record
  run_native_bridge.py --backend arm16 -- match --variant booster-native-fw16-20261023-f
  run_native_bridge.py --backend native17 --scene K1/BHumanLocalMatch --seconds 60
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BRIDGE_ROOT.parent.parent          # robocup-1
PARENT_ROOT = REPO_ROOT.parent                  # .../Desktop/Robocup (read-only for us)

BHUMAN_ENTRY = PARENT_ROOT / "bhuman" / "start-bhuman.sh"
FORGE_CLI = PARENT_ROOT / "forge" / "bin" / "forge"
WORK_ROOT = BRIDGE_ROOT / "work"


def fail(msg: str) -> "None":
    print(f"run_native_bridge: {msg}", file=sys.stderr)
    sys.exit(2)


def latest_variant(pattern: str) -> Path | None:
    candidates = sorted(WORK_ROOT.glob(pattern))
    return candidates[-1] if candidates else None


def check_native17() -> list[str]:
    """Prerequisites for the native17 backend; empty list means ready."""
    missing = []
    unpacked = WORK_ROOT / "package" / "unpacked"
    if not unpacked.is_dir():
        missing.append(
            "evidence package not unpacked yet: run tools/verify_package.py with the split "
            "volumes once their location is known (see README)")
    else:
        passes = sorted(BRIDGE_ROOT.glob("evidence/*-package-verification/package-verification.json"))
        ok = False
        for p in reversed(passes):
            try:
                if json.loads(p.read_text()).get("result") == "PASS":
                    ok = True
                    break
            except json.JSONDecodeError:
                continue
        if not ok:
            missing.append("no PASS package-verification evidence; verify the package first")
    variants = [d for d in sorted(WORK_ROOT.glob("variant-*"))
                if (d / "Build" / "Linux" / "SimRobot" / "Release" / "SimRobot").is_file()]
    if not any("native17" in d.name for d in variants):
        missing.append(
            "no built native17 variant: after vendoring the core from the verified package, "
            "create one with tools/make_variant.py --patch <bhuman-side patches> and build it")
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", required=True, choices=("native17", "arm16", "bhuman"))
    ap.add_argument("--scene", default=None, help="native17 only: scene under variant Config/Scenes")
    ap.add_argument("--seconds", type=float, default=None, help="native17 only: simulated duration")
    ap.add_argument("--variant", default=None, help="native17 only: variant name under work/")
    args, passthrough = ap.parse_known_args()
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    if args.backend == "bhuman":
        if not BHUMAN_ENTRY.is_file():
            fail(f"official entry not found: {BHUMAN_ENTRY}")
        if not passthrough or passthrough[0] not in ("gait", "match"):
            fail("bhuman backend needs a mode: -- gait|match [run-bhuman-k1.py options]")
        os.execv("/bin/bash", ["bash", str(BHUMAN_ENTRY), *passthrough])

    if args.backend == "arm16":
        if not FORGE_CLI.is_file():
            fail(f"forge CLI not found: {FORGE_CLI}")
        os.execv(str(FORGE_CLI), [str(FORGE_CLI), *passthrough])

    # native17
    missing = check_native17()
    if missing:
        print("run_native_bridge: native17 backend is not ready:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 2
    variant = (WORK_ROOT / args.variant) if args.variant else latest_variant("variant-*native17*")
    if variant is None or not variant.is_dir():
        fail(f"variant not found under {WORK_ROOT}")
    simrobot = variant / "Build" / "Linux" / "SimRobot" / "Release" / "SimRobot"
    if not simrobot.is_file():
        fail(f"SimRobot binary missing in variant: {simrobot}")
    scene = args.scene or "K1/BHumanLocalMatch"
    scene_arg = scene if scene.endswith((".ros3", ".con")) else f"{scene}.ros3"
    cmd = [str(simrobot), scene_arg, *passthrough]
    env = dict(os.environ)
    if args.seconds is not None:
        env.setdefault("BH_NATIVE17_SECONDS", str(args.seconds))
    print(f"[native17] {variant.name} scene={scene_arg}", file=sys.stderr)
    return subprocess.run(cmd, env=env, cwd=str(variant)).returncode


if __name__ == "__main__":
    sys.exit(main())
