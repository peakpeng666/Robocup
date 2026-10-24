#!/usr/bin/env python3
"""Negative fixture: skeleton YAML exists, but train.py must not see it.

Gate rule
---------
IsaacGymRL Runner (utils/runner.py) does:

    from envs import *                          # names from envs/__init__.py
    cfg_file = os.path.join("envs", "{task}.yaml")
    task_class = eval(self.cfg["basic"]["task"])

So a YAML that only lives in k1-reactive/ is invisible. The required gate
result is therefore:

    skeleton YAML present  AND  unregistered_in_train_py = PASS

Negative cases (must FAIL the gate if they ever happen)
-------------------------------------------------------
1. Official envs/__init__.py gains `from envs.k1_reactive import K1_Reactive`
   (or any other mention of the task name). Then eval("K1_Reactive") works.
2. Someone copies K1_Reactive.yaml or k1_reactive.py into IsaacGymRL/envs/.
   Then `python train.py --task=K1_Reactive` can open the YAML.

This file never writes into the official trees. It only scores in-memory
fixtures plus the current checkout. See check_skeleton.registration_is_leak.

Run:
  python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_skeleton import (  # noqa: E402
    ISAAC_ENV_TREES,
    inspect_official_registry,
    registration_is_leak,
)
from contract import TASK_NAME  # noqa: E402

# Minimal stand-in for the official envs/__init__.py (walk/kick/standup only).
OFFICIAL_INIT_OK = (
    "from envs.t1 import T1\n"
    "from envs.t1_ball import T1_Ball\n"
    "from envs.t1_stand_up import T1_Stand_Up\n"
    "from envs.k1 import K1\n"
    "from envs.k1_ball import K1_Ball\n"
    "from envs.k1_stand_up import K1_Stand_Up\n"
)

# Negative fixture: leaked import. This is what must never land in git.
LEAKED_INIT = OFFICIAL_INIT_OK + f"from envs.k1_reactive import {TASK_NAME}\n"


def run_negative_fixtures() -> dict[str, Any]:
    errors: list[str] = []
    notes: list[str] = []

    if registration_is_leak(OFFICIAL_INIT_OK, leaked_yaml=False, leaked_py=False):
        errors.append("positive fixture (official init, no leak) was scored as a leak")
    else:
        notes.append("positive fixture: official init without K1_Reactive → not a leak")

    if not registration_is_leak(LEAKED_INIT, leaked_yaml=False, leaked_py=False):
        errors.append(
            "NEGATIVE TEST FAILED: leaked `from envs.k1_reactive import "
            f"{TASK_NAME}` must be scored as a leak (would register into train.py)"
        )
    else:
        notes.append(
            "negative fixture: leaked import in envs/__init__.py → FAIL (as required)"
        )

    if not registration_is_leak(OFFICIAL_INIT_OK, leaked_yaml=True, leaked_py=False):
        errors.append("NEGATIVE TEST FAILED: leaked envs/K1_Reactive.yaml must FAIL")
    else:
        notes.append("negative fixture: leaked envs/K1_Reactive.yaml → FAIL (as required)")

    if not registration_is_leak(OFFICIAL_INIT_OK, leaked_yaml=False, leaked_py=True):
        errors.append("NEGATIVE TEST FAILED: leaked envs/k1_reactive.py must FAIL")
    else:
        notes.append("negative fixture: leaked envs/k1_reactive.py → FAIL (as required)")

    return {"ok": not errors, "errors": errors, "notes": notes}


def run(repo: Path | None = None) -> dict[str, Any]:
    fixtures = run_negative_fixtures()
    registry = inspect_official_registry(repo)
    errors = list(fixtures["errors"])
    notes = list(fixtures["notes"])

    if not registry.get("skeleton_yaml_exists"):
        errors.append("skeleton YAML missing; gate rule assumes it already exists")
    if registry.get("unregistered_in_train_py") != "PASS":
        errors.append(
            "current tree must be unregistered_in_train_py=PASS "
            f"(got {registry.get('unregistered_in_train_py')!r})"
        )
    else:
        notes.append(
            "current tree: skeleton YAML exists beside IsaacGymRL; "
            "unregistered in train.py = PASS"
        )
    for rel in ISAAC_ENV_TREES:
        notes.append(f"checked official tree {rel}")

    return {
        "ok": not errors,
        "unregistered_in_train_py": registry.get("unregistered_in_train_py"),
        "skeleton_yaml_exists": registry.get("skeleton_yaml_exists"),
        "registry": registry,
        "errors": errors,
        "notes": notes,
    }


def main() -> int:
    report = run()
    print(
        f"[unregistered] {'PASS' if report['ok'] else 'FAIL'} "
        f"yaml_exists={report['skeleton_yaml_exists']} "
        f"unregistered_in_train_py={report['unregistered_in_train_py']}"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
