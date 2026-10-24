#!/usr/bin/env python3
"""Read-only K1 reward audit: live baseline PASS, tampered snapshot FAIL."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DRAFT_ONLY_REL = "bhuman/k1-training/configs/draft-only"


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load_audit(repo: Path):
    rel = "bhuman/k1-training/scripts/k1_reward_audit.py"
    spec = importlib.util.spec_from_file_location("k1_reward_audit_test", repo / rel)
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
        errors.append("reward audit test imported Gym")

    audit = _load_audit(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        live = audit.audit(repo)
        audit.assert_snapshot_matches_baseline(live)
        notes.append("live snapshot matches still_proportion 0.1 / tracking_* / action_rate -1. / ref 1.0")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    if live:
        sources = live.get("sources") or {}
        official = " ".join(
            str(item)
            for key in ("k1_yaml", "stability")
            for item in (sources.get(key) or [])
        )
        if "draft-only" in official:
            errors.append("audit sources must exclude draft-only")
        elif DRAFT_ONLY_REL not in (sources.get("excluded") or []):
            errors.append("audit must list draft-only under excluded")
        else:
            notes.append("draft-only not used as an official source")
        if not live.get("reward_scales"):
            errors.append("audit must list reward scale items")
        else:
            notes.append(f"reward item list: {len(live['reward_scales'])} scales")

    for key, bad in (
        ("still_proportion", 0.25),
        ("tracking_lin_vel_x", 1.0),
        ("action_rate", 0.0),
        ("reference_mean_penalty", 0.25),
    ):
        tampered = copy.deepcopy(live) if live else {"baseline_values": {}, "walk": "344→13"}
        tampered.setdefault("baseline_values", {})[key] = bad
        tampered["write_yaml"] = False
        tampered["trainable"] = False
        tampered["walk"] = "344→13"
        try:
            audit.assert_snapshot_matches_baseline(tampered)
            errors.append(f"tampered {key}={bad} must fail")
        except AssertionError:
            notes.append(f"tampered snapshot {key}={bad} refused")

    try:
        audit.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back API refused")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during reward-audit test")
    else:
        notes.append("official K1.yaml untouched")

    report = audit.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[k1-reward-audit] {'PASS' if report['ok'] else 'FAIL'} "
        "read-only; tampered snapshot fails"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
