#!/usr/bin/env python3
"""FallDown / MotionEngine chain: fallen → 73→22 → getup_done → walk."""
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
    rel = "bhuman/k1-training/scripts/falldown_motion_chain.py"
    spec = importlib.util.spec_from_file_location("falldown_motion_chain_test", repo / rel)
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
        errors.append("FallDown chain test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("FallDown chain flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_chain_frozen(repo)
        notes.append("assert_chain_frozen: fallen→73→22→walk; not SkillRequest")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        if snap.get("falldown_states") or snap.get("chain"):
            errors.append("SKIP must not fabricate states/chain")
        else:
            notes.append("honest SKIP: empty states/chain, not fabricated")
        warnings.append(str(snap.get("reason") or "source missing"))
    elif snap:
        if snap.get("fallen_is_skill_request_type"):
            errors.append("fallen must stay outside SkillRequest")
        else:
            notes.append("fallen is not a SkillRequest Type")
        if snap.get("default_after_getup") != "walk" or snap.get("default_contract") != "344→13":
            errors.append("getup_done must return official walk 344→13")
        else:
            notes.append("getup_done returns official walk 344→13")
        if snap.get("standup_contract") != "73→22":
            errors.append("fallen must enter official standup 73→22")
        states = snap.get("falldown_states") or []
        if "fallen" not in states:
            errors.append("FallDownState snapshot missing fallen")
        else:
            notes.append(f"FallDownState::State {states}")
        chain_steps = [row.get("step") for row in (snap.get("chain") or [])]
        expected = ["fallen", "route_getup", "getup_73_22", "getup_done", "return_walk"]
        if chain_steps != expected:
            errors.append(f"chain steps drifted: {chain_steps}")
        else:
            notes.append("chain: fallen → GetUpEngine 73→22 → getup_done → walk")
        cross = snap.get("cross") or {}
        if not cross.get("agrees"):
            errors.append("switcher / handoff_getup cross-check missing")
        elif cross.get("bt_fallen") != "handoff_getup" or cross.get("sm_getup_done") != "walk":
            errors.append("cross-check drifted off handoff_getup / walk")
        else:
            notes.append("cross: bt_skill_select / skill_request_map / SwitcherSM agree")
        completion = snap.get("getup_completion") or {}
        if completion.get("status") == "SKIP":
            notes.append("GetUpEngine completion SKIP (source missing)")
        elif not completion.get("completes_then_walk"):
            errors.append("GetUpEngine must force walk after State::done")
        else:
            notes.append("GetUpEngine isDone → Force walk afterwards")

    skip_blank = mod._skip_snapshot("unit-test missing source")
    if skip_blank.get("falldown_states") or skip_blank.get("chain"):
        errors.append("SKIP helper must not invent states/chain")
    else:
        notes.append("SKIP helper leaves states/chain empty")

    for claim, label in (
        ({"fallen_is_skill_request_type": True}, "fallen as SkillRequest Type"),
        ({"handoff_getup_is_skill_request_type": True}, "handoff_getup as Type"),
        ({"skill_request_type": "fallen"}, "skill_request_type=fallen"),
        ({"official": "standup"}, "official=standup"),
    ):
        try:
            mod.refuse_fallen_as_skill_request(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        mod.refuse_kick_before_getup_done({"kick_before_getup_done": True})
        errors.append("kick_before_getup_done claim must raise")
    except ValueError:
        notes.append("negative: GetUp incomplete kick claim refused")

    try:
        mod.refuse_kick_before_getup_done()
        errors.append("SM GetUp incomplete kick must raise")
    except ValueError:
        notes.append("negative: SM kick before getup_done refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/falldown-motion-chain-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("skipped") and (blob.get("falldown_states") or blob.get("chain")):
            errors.append("written SKIP snapshot fabricated chain")
        elif blob.get("status") == "PASS" and blob.get("fallen_is_skill_request_type"):
            errors.append("written PASS snapshot must keep fallen outside SkillRequest")
        else:
            notes.append("wrote manifests/falldown-motion-chain-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during FallDown chain test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
        "walk": "344→13",
        "standup": "73→22",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[fall-chain] {'PASS' if report['ok'] else 'FAIL'} "
        f"status={'SKIP' if report.get('skipped') else 'extract'}; "
        "fallen→73→22→walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
