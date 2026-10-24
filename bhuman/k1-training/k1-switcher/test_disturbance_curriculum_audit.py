#!/usr/bin/env python3
"""Disturbance draft: legal proposed_only; live push_* not overwritten."""
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
    rel = "bhuman/k1-training/scripts/disturbance_curriculum_audit.py"
    spec = importlib.util.spec_from_file_location(
        "disturbance_curriculum_audit_test", repo / rel
    )
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
        errors.append("disturbance audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("disturbance audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_disturbance_frozen(repo)
        notes.append("assert_disturbance_frozen: live push_* intact; draft not applied")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    live = data.get("live_push") or {}
    if live.get("push_interval_s") != 5.0 or live.get("push_duration_s") != 2.0:
        errors.append("live push interval/duration drifted")
    else:
        notes.append("live push_interval_s=5 / push_duration_s=2")
    if live.get("push_force.range") != [0.0, 10.0]:
        errors.append("live push_force.range drifted")
    else:
        notes.append("live push_force [0,10] / push_torque [0,2]")

    draft = data.get("draft") or {}
    if draft.get("applied") or data.get("live_overwritten"):
        errors.append("disturbance draft marked applied / live overwritten")
    else:
        notes.append("C_disturbance_curriculum proposed_only; not applied")

    try:
        mod.refuse_missing_draft_only(
            {"trainable": False, "do_not_pass_to_train_py": True}
        )
        errors.append("missing draft_only must raise")
    except ValueError:
        notes.append("negative: missing draft_only refused")

    try:
        mod.refuse_apply_to_live(
            {
                "draft_only": True,
                "do_not_pass_to_train_py": True,
                "trainable": False,
                "apply_to_live": True,
            }
        )
        errors.append("apply_to_live must raise")
    except ValueError:
        notes.append("negative: apply_to_live refused")

    try:
        mod.refuse_overwrite_live_push(
            {"target": "k1.yaml", "proposed_only": {"push_interval_s": 1.0}}
        )
        errors.append("overwrite live push_interval_s must raise")
    except ValueError:
        notes.append("negative: draft overwrite live push_* refused")

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
        errors.append("K1.yaml changed during disturbance audit")
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
        f"[disturb-draft] {'PASS' if report['ok'] else 'FAIL'} "
        "live push intact; draft_only / apply_to_live refused"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
