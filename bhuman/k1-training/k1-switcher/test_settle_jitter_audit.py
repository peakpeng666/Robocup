#!/usr/bin/env python3
"""Settle/jitter draft: new keys only; live action_rate / YAML not overwritten."""
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
    rel = "bhuman/k1-training/scripts/settle_jitter_audit.py"
    spec = importlib.util.spec_from_file_location("settle_jitter_audit_test", repo / rel)
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
        errors.append("settle-jitter audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("settle-jitter flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_settle_frozen(repo)
        notes.append("assert_settle_frozen: live has no draft settle keys")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    if data.get("live_action_rate") != -1.0:
        errors.append("live action_rate drifted")
    else:
        notes.append("live action_rate=-1. intact")
    absent = set(data.get("live_absent_keys") or [])
    if "draft_settle_jitter_scale" not in absent or "draft_zero_cmd_root_acc_scale" not in absent:
        errors.append("official must honestly record missing settle/jitter keys")
    else:
        notes.append(f"official absent settle keys: {sorted(absent)}")

    draft = data.get("draft") or {}
    if draft.get("applied") or data.get("live_overwritten"):
        errors.append("settle draft marked applied / live overwritten")
    else:
        notes.append("B_settle_jitter proposed_only; not applied")

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
        mod.refuse_overwrite_live_settle(
            {"target": "k1.yaml", "proposed_only": {"action_rate": -0.1}}
        )
        errors.append("overwrite live action_rate must raise")
    except ValueError:
        notes.append("negative: draft overwrite live action_rate refused")

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
        errors.append("K1.yaml changed during settle-jitter audit")
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
        f"[settle-jitter] {'PASS' if report['ok'] else 'FAIL'} "
        "new keys only; live action_rate intact"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
