#!/usr/bin/env python3
"""Reference-penalty anneal draft: live 1.0 untouched; snapshot diff only."""
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
    rel = "bhuman/k1-training/scripts/reference_penalty_anneal_audit.py"
    spec = importlib.util.spec_from_file_location(
        "reference_penalty_anneal_audit_test", repo / rel
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
        errors.append("anneal audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("anneal audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ref_path = repo / "bhuman/k1-training/configs/walk-reference-stability-v1.json"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ref = hashlib.sha256(ref_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_anneal_frozen(repo)
        notes.append("assert_anneal_frozen: live reference_mean_penalty=1.0")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    if data.get("live_reference_mean_penalty") != 1.0:
        errors.append("live reference_mean_penalty drifted")
    else:
        notes.append("live reference_mean_penalty=1.0")
    diff = data.get("diff") or {}
    if diff.get("official") != 1.0 or diff.get("live_updated"):
        errors.append("anneal snapshot must keep official 1.0 / live_updated=false")
    else:
        notes.append(
            "snapshot diff: official 1.0 vs proposed start/end; not applied"
        )
    proposed = (diff.get("proposed_only") or (data.get("draft") or {}).get("proposed_only") or {})
    if proposed.get("reference_mean_penalty_end") != 0.3:
        errors.append("draft anneal end drifted")
    if "reference_mean_penalty" in proposed:
        errors.append("draft must not propose the live reference_mean_penalty key")

    try:
        mod.refuse_overwrite_live_penalty(
            {
                "target": "official",
                "key": "algorithm.reference_mean_penalty",
                "proposed_only": {"reference_mean_penalty": 0.3},
            }
        )
        errors.append("overwrite live reference_mean_penalty must raise")
    except ValueError:
        notes.append("negative: live reference_mean_penalty overwrite refused")

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
    after_ref = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during anneal audit")
    elif before_ref != after_ref:
        errors.append("walk-reference-stability-v1.json changed during anneal audit")
    else:
        notes.append("official K1.yaml + reference stability untouched")

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
        f"[anneal-draft] {'PASS' if report['ok'] else 'FAIL'} "
        "live 1.0 intact; anneal proposed_only"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
