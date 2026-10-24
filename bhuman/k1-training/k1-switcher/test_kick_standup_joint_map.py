#!/usr/bin/env python3
"""Kick/standup joint map: extract or SKIP; standup[12] motor ≠ walk freq."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joint_map_contract import STANDUP_ACTION_MAP, WALK_ACTION_MAP  # noqa: E402
from kick_standup_joint_map import (  # noqa: E402
    STANDUP_SLOT12_NAME,
    TRAINABLE,
    WRITE_YAML,
    assert_maps_frozen,
    extract_maps,
    kick_shared_exit_semantics,
    refuse_fast_standup_as_walk,
    refuse_kick_as_new_walk_baseline,
    refuse_kick_name_remap,
    refuse_standup_prefix_as_walk,
    refuse_standup_slot12_as_gait_frequency,
    refuse_standup_yaml_gait_frequency_as_action12,
    refuse_walk_freq_as_standup_motor,
    refuse_write_yaml,
    standup_slot12_semantics,
    write_snapshot,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    skipped = False

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick/standup joint map imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("kick/standup joint map flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = assert_maps_frozen(repo)
        notes.append("assert_maps_frozen: kick shares walk 13-exit; standup 22 extracted")
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        errors.append(str(exc))
        snap = {}

    try:
        extracted = extract_maps(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        extracted = snap

    if extracted.get("skipped"):
        skipped = True
        warnings.append(extracted.get("kick", {}).get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated kick/standup names")
        if extracted.get("kick", {}).get("names") or extracted.get("standup", {}).get("names"):
            errors.append("SKIP snapshot must not invent names")
    elif extracted:
        kick = extracted.get("kick") or {}
        standup = extracted.get("standup") or {}
        if kick.get("status") == "PASS":
            notes.append("kick 59→13 shares walk 12-legs+gait_frequency")
        if standup.get("status") == "PASS":
            notes.append(
                f"standup 73→22 / fast 72→22; [12]={standup.get('slot12')} is_motor=true"
            )
        if extracted.get("cross", {}).get("confused"):
            errors.append("walk[12] vs standup[12] marked confused")

    sem = standup_slot12_semantics()
    if sem["name"] != STANDUP_SLOT12_NAME or not sem["is_motor"] or sem["index"] != 12:
        errors.append("standup_slot12_semantics drifted")
    else:
        notes.append("standup[12]=lHipYaw is_motor=true (not gait_frequency)")

    kick_sem = kick_shared_exit_semantics()
    if not kick_sem.get("shares_walk_exit") or kick_sem.get("act") != 13:
        errors.append("kick shared-exit semantics drifted")
    else:
        notes.append("kick shared-exit semantics: act=13, names=walk map")

    try:
        refuse_standup_slot12_as_gait_frequency(
            {"index": 12, "is_motor": False, "name": "gait_frequency"}
        )
        errors.append("standup[12] as gait_frequency must raise")
    except ValueError:
        notes.append("negative: standup[12] as gait_frequency refused")

    try:
        refuse_standup_slot12_as_gait_frequency(
            {"interpret_as": "gait_frequency", "is_motor": True}
        )
        errors.append("standup[12] interpret_as gait_frequency must raise")
    except ValueError:
        notes.append("negative: standup[12] interpret_as frequency refused")

    try:
        refuse_walk_freq_as_standup_motor(
            {"skill": "walk", "is_motor": True, "name": STANDUP_SLOT12_NAME}
        )
        errors.append("walk freq as standup motor must raise")
    except ValueError:
        notes.append("negative: walk action[12] as lHipYaw refused")

    try:
        refuse_standup_prefix_as_walk(STANDUP_ACTION_MAP[:13])
        errors.append("standup[:13] as walk map must raise")
    except ValueError:
        notes.append("negative: standup[:13] refused as walk 13-D map")

    try:
        refuse_kick_name_remap(["lHipPitch"] * 12 + ["gait_frequency"])
        errors.append("remapped kick names must raise")
    except ValueError:
        notes.append("negative: kick joint remap refused")

    try:
        refuse_kick_as_new_walk_baseline({"obs": 59, "act": 13, "new_baseline": True})
        errors.append("kick as new walk baseline must raise")
    except ValueError:
        notes.append("negative: kick as new walk baseline refused")

    try:
        refuse_standup_yaml_gait_frequency_as_action12(
            {
                "field": "commands.gait_frequency",
                "interpret_as": "action[12]",
                "source": "K1_Stand_Up.yaml",
            }
        )
        errors.append("standup YAML gait_frequency as action[12] must raise")
    except ValueError:
        notes.append("negative: standup YAML gait_frequency ≠ action[12]")

    try:
        refuse_fast_standup_as_walk()
        errors.append("fast standup as walk must raise")
    except ValueError:
        notes.append("negative: fast standup 72→22 refused as walk")

    try:
        refuse_kick_name_remap(WALK_ACTION_MAP)
        notes.append("kick shared walk names accepted")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = write_snapshot(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during kick/standup joint-map test")
    else:
        notes.append("official K1.yaml untouched (read-only extract)")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": skipped,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "kick": "59→13",
        "standup": "73→22",
    }


def main() -> int:
    report = run()
    print(
        f"[kick-standup-map] {'PASS' if report['ok'] else 'FAIL'} "
        "kick 59→13 shares walk exit; standup[12]=lHipYaw motor"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
