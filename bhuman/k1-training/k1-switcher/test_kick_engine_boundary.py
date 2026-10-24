#!/usr/bin/env python3
"""KickEngine boundary: kick 59→13 bypass ≠ walk 344→13 baseline."""
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
    rel = "bhuman/k1-training/scripts/kick_engine_boundary.py"
    spec = importlib.util.spec_from_file_location("kick_engine_boundary_test", repo / rel)
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
        errors.append("KickEngine boundary test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("KickEngine boundary flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_boundary_frozen(repo)
        notes.append("assert_boundary_frozen: kick 59→13 bypass; walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    standalone = snap.get("standalone_kick_engine") or {}
    if snap.get("status") == "SKIP" and not snap.get("chain"):
        if snap.get("fabricated") or snap.get("chain"):
            errors.append("SKIP must not fabricate a kick chain")
        else:
            notes.append("honest SKIP: live kick chain missing, not fabricated")
        warnings.append(str(snap.get("reason") or "source missing"))
    elif snap:
        if snap.get("replaces_walk"):
            errors.append("kick must not replace walk")
        if snap.get("default_contract") != "344→13":
            errors.append("default must stay official walk 344→13")
        else:
            notes.append("default still official walk 344→13")
        if snap.get("kick_contract") != "59→13":
            errors.append("kick bypass must stay 59→13")
        else:
            notes.append("kick is skill bypass 59→13")
        if standalone.get("status") == "SKIP":
            warnings.append(str(standalone.get("reason") or "KickEngine.cpp missing"))
            notes.append("honest SKIP: standalone KickEngine not fabricated")
        chain_steps = [row.get("step") for row in (snap.get("chain") or [])]
        expected = ["playball", "walk_to_ball_and_kick_skill", "walk_kick_engine", "kick_policy"]
        if chain_steps != expected:
            errors.append(f"kick chain drifted: {chain_steps}")
        else:
            notes.append("chain: PlayBall → WalkToBallAndKick → WalkToBallAndKickEngine → kickPolicy")
        cross = snap.get("cross") or {}
        if (
            not cross.get("agrees")
            or cross.get("bt_want_kick") != "kick"
            or cross.get("sm_back") != "walk"
        ):
            errors.append("want_kick / PlayBall / switcher cross-check missing")
        else:
            notes.append("cross: want_kick / PlayBall / SwitcherSM agree")

    for claim, label in (
        ({"replaces_walk": True}, "replaces_walk"),
        ({"kick_as_walk_baseline": True}, "kick as walk baseline"),
        ({"default_skill": "kick"}, "default_skill kick"),
        ({"obs": 344, "skill": "kick"}, "kick occupying 344"),
    ):
        try:
            mod.refuse_kick_replaces_walk(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/kick-engine-boundary-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("replaces_walk") or blob.get("default_contract") not in (None, "344→13"):
            errors.append("written snapshot must keep walk 344→13")
        else:
            notes.append("wrote manifests/kick-engine-boundary-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during KickEngine boundary test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(
            snap.get("status") == "SKIP"
            or standalone.get("status") == "SKIP"
        ),
        "walk": "344→13",
        "kick": "59→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-boundary] {'PASS' if report['ok'] else 'FAIL'} "
        "kick 59→13 bypass ≠ walk 344→13; KickEngine standalone SKIP ok"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
