#!/usr/bin/env python3
"""Missing-weight SKIP honesty: 7-path inventory PASS ≠ fabricated / fail-closed."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
    rel = "bhuman/k1-training/scripts/missing_weight_skip_honesty.py"
    spec = importlib.util.spec_from_file_location(
        "missing_weight_skip_honesty_test", repo / rel
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
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("missing-weight SKIP honesty test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.WRITE_WEIGHTS:
        errors.append("missing-weight SKIP honesty flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_missing_weight_skip_honesty_frozen(repo)
        notes.append("assert_missing_weight_skip_honesty_frozen: 7-path SKIP honesty")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    ids = [row.get("id") for row in (snap.get("paths") or [])]
    expected = [path_id for path_id, _w, _fn in mod.PATH_SPECS]
    if ids != expected:
        errors.append(f"honesty path table drifted: {ids}")
    else:
        notes.append("paths frozen: walk/kick/standup/fast replay+eval")
    if snap.get("will_exec_replay_here") or snap.get("will_run_train_py"):
        errors.append("missing-weight honesty must not exec replay / train")
    else:
        notes.append("inventory only; no replay / no train")
    if (
        snap.get("missing_weight_as_fabricated_pass")
        or snap.get("missing_weight_fails_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("missing-weight honesty must stay SKIP / not fail-closed / GAP open")
    else:
        notes.append("inventory PASS without weights OK; not fabricated; GAP open")
    if snap.get("missing_weight_skip"):
        if snap.get("missing_weight_honesty") != "SKIP":
            errors.append("missing weights must record honest SKIP")
        else:
            notes.append("missing-weight SKIP honesty: not fabricated PASS")
            warnings.append("weight files absent; honest SKIP recorded")

    try:
        mod.refuse_missing_weight_as_fabricated_pass(
            {
                "missing_weight": True,
                "as_have_weights": True,
                "status": "PASS",
                "比赛合格": True,
            }
        )
        errors.append("missing_weight_as_fabricated_pass must raise")
    except ValueError:
        notes.append("negative: missing-weight as fabricated PASS refused")
    try:
        mod.refuse_missing_weight_fails_closed(
            {
                "missing_weight_fails_closed": True,
                "fail_closed": True,
                "because_missing": True,
                "status": "FAIL",
            }
        )
        errors.append("missing_weight_fails_closed must raise")
    except ValueError:
        notes.append("negative: missing-weight fail-closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/missing-weight-skip-honesty-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("missing_weight_as_fabricated_pass")
            or blob.get("missing_weight_fails_closed")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep walk 344 / GAP open / honest SKIP")
        else:
            notes.append("wrote manifests/missing-weight-skip-honesty-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during missing-weight SKIP honesty test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during missing-weight SKIP honesty test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[missing-weight] {'PASS' if report['ok'] else 'FAIL'} "
        "7-path SKIP honesty; not fabricated PASS; not fail-closed"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
