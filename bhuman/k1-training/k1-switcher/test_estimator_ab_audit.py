#!/usr/bin/env python3
"""Estimator A/B draft: bypass only; no 344 write; not registered in train.py."""
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
    rel = "bhuman/k1-training/scripts/estimator_ab_audit.py"
    spec = importlib.util.spec_from_file_location("estimator_ab_audit_test", repo / rel)
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
        errors.append("estimator A/B audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.EST_TRAINABLE:
        errors.append("estimator A/B flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_estimator_ab_frozen(repo)
        notes.append("assert_estimator_ab_frozen: bypass only; TRAINABLE=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    draft = data.get("draft") or {}
    proposed = draft.get("proposed_only") or {}
    if proposed.get("actor_obs") != 344:
        errors.append("estimator draft actor_obs drifted off 344")
    else:
        notes.append("draft actor_obs=344 bypass")
    if proposed.get("estimator") != "passthrough":
        errors.append("default estimator A/B family drifted")
    if draft.get("write_344") or draft.get("register_train_py") or draft.get("applied"):
        errors.append("estimator draft marked write_344 / train.py / applied")
    else:
        notes.append("D_estimator_ab not written into 344; not registered in train.py")
    if data.get("estimators_trainable") is not False:
        errors.append("k1-estimators TRAINABLE leaked")
    else:
        notes.append("k1-estimators TRAINABLE=false cross-checked")

    registry = data.get("registry") or {}
    if registry.get("bypass_registered"):
        errors.append(f"bypass leaked into registry {registry['bypass_registered']}")
    else:
        notes.append("env registry: k1-estimators still a bypass")

    try:
        mod.refuse_write_344({"write_344": True, "actor_obs": 352})
        errors.append("write_344 must raise")
    except ValueError:
        notes.append("negative: write into 344 refused")

    try:
        mod.refuse_register_train_py(
            {"register_train_py": True, "task": "passthrough"}
        )
        errors.append("register_train_py must raise")
    except ValueError:
        notes.append("negative: train.py registration refused")

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
        errors.append("K1.yaml changed during estimator A/B audit")
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
        f"[estimator-ab] {'PASS' if report['ok'] else 'FAIL'} "
        "bypass only; no 344 write; train.py unregistered"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
