#!/usr/bin/env python3
"""Command schedule: official commands extracted; draft not applied."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/command_schedule_audit.py"
    spec = importlib.util.spec_from_file_location("command_schedule_audit_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("command-schedule audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("command-schedule flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_schedule_frozen(repo)
        notes.append("assert_schedule_frozen: official commands; draft not applied")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    official = (data.get("official") or [{}])[0].get("commands") or {}
    if official.get("still_proportion") != 0.1:
        errors.append("official still_proportion drifted off 0.1")
    else:
        notes.append("official still_proportion=0.1")
    if official.get("lin_vel_x") != [-1.0, 2.0] or official.get("lin_vel_y") != [-1.0, 1.0]:
        errors.append("official lin_vel ranges drifted")
    else:
        notes.append("official lin_vel_x/y + ang_vel_yaw present")

    missing = data.get("missing_on_official") or []
    if "schedule" not in missing or "curriculum" not in missing:
        errors.append("official must honestly record missing schedule/curriculum")
    else:
        notes.append(f"honest missing on official: {missing}")

    draft = data.get("draft") or {}
    if draft.get("applied") or data.get("draft_applied"):
        errors.append("draft command schedule marked applied")
    else:
        notes.append("draft A_command_schedule proposed_only; not applied")

    try:
        mod.refuse_draft_as_applied(
            {"applied": True, "source": "official", "still_proportion": 0.25}
        )
        errors.append("draft-as-applied must raise")
    except ValueError:
        notes.append("negative: draft treated as applied refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = mod.write_audit(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during command-schedule audit")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[command-sched] {'PASS' if report['ok'] else 'FAIL'} "
        "official commands; draft schedule not applied"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
