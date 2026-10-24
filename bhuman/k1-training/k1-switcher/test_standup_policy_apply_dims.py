#!/usr/bin/env python3
"""standup apply-site 73→22 / K1.onnx; ≠ walk 344 / kick 59 / fast 72."""
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
    rel = "bhuman/k1-training/scripts/standup_policy_apply_dims.py"
    spec = importlib.util.spec_from_file_location("standup_policy_apply_dims_test", repo / rel)
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
        errors.append("standup apply-dims test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("standup apply-dims flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_standup_apply_dims_frozen(repo)
        notes.append("assert_standup_apply_dims_frozen: regular apply 73→22")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "GetUpEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate standup apply dims")
        else:
            notes.append("honest SKIP: standup apply dims not fabricated")
    elif snap:
        regular = (snap.get("apply_sites") or {}).get("regular") or {}
        if regular.get("contract") != "73→22" or tuple(regular.get("onnx_allow") or ()) != ("K1.onnx",):
            errors.append("regular apply must be 73→22 / K1.onnx")
        else:
            notes.append("regular apply 73→22 / K1.onnx")
        if not regular.get("not_walk") or not regular.get("not_kick"):
            errors.append("regular apply must refuse walk 344 / kick 59")
        else:
            notes.append("≠ walk 344 / kick 59 / fast as regular")
        if snap.get("standup_as_walk_344") or snap.get("getup_as_hot_swap_train"):
            errors.append("standup apply must not be marked walk / train hot-swap")
        else:
            notes.append("standup ≠ walk 344; GetUp ≠ hot-swap train.py")
        if not (snap.get("handoff_13_zero") or {}).get("closed_elsewhere"):
            errors.append("must reference existing 13-zero handoff")
        else:
            notes.append("standup→walk 13-zero referenced, not re-closed")
        if snap.get("walk_kick_gap_closed"):
            errors.append("must not mark walk↔kick GAP closed")
        else:
            notes.append("walk↔kick resetHistoryData GAP stays open")

    try:
        mod.refuse_standup_as_walk_344(
            {"standup_as_walk_344": True, "source": "policy", "numInput": 344}
        )
        errors.append("standup as walk 344 must raise")
    except ValueError:
        notes.append("negative: standup as walk 344 refused")
    try:
        mod.refuse_getup_as_hot_swap_train(
            {"getup_as_hot_swap_train": True, "source": "GetUpEngine", "train_graph": True}
        )
        errors.append("GetUp as hot-swap train must raise")
    except ValueError:
        notes.append("negative: GetUp as hot-swap train refused")
    try:
        mod.refuse_standup_onnx_as_kick_slot(
            {"standup_onnx_as_kick_slot": True, "source": "K1.onnx", "kick_slot": True}
        )
        errors.append("standup ONNX as kick slot must raise")
    except ValueError:
        notes.append("negative: standup ONNX as kick slot refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: getUpEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/standup-policy-apply-dims-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("standup_as_walk_344") or blob.get("getup_as_hot_swap_train"):
            errors.append("written snapshot must keep standup 73→22 / not train")
        else:
            notes.append("wrote manifests/standup-policy-apply-dims-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during standup apply-dims test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during standup apply-dims test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "standup": "73→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[standup-apply] {'PASS' if report['ok'] else 'FAIL'} "
        "regular apply 73→22 / K1.onnx; ≠ walk 344"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
