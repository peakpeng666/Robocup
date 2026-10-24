#!/usr/bin/env python3
"""Walk action[12] = gait_frequency; refuse motor / standup 22 / reactive 15."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gait_frequency_contract import (  # noqa: E402
    REACTIVE_FREQ_INDEX,
    SLOT_NAME,
    WALK_FREQ_INDEX,
    assert_gait_frequency_frozen,
    cross_assert_joint_map,
    decode_walk_frequency_hz,
    refuse_foreign_as_walk_gait_frequency,
    refuse_slot12_as_motor,
    walk_slot12_semantics,
)
from joint_map_contract import STANDUP_ACTION_MAP, WALK_ACTION_MAP  # noqa: E402


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
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("gait_frequency test imported Gym")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        frozen = assert_gait_frequency_frozen(repo)
        notes.extend(frozen.get("notes") or [])
        notes.append(f"decode sample 1.5+0.25 → {frozen.get('hz_sample')}")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))

    sem = walk_slot12_semantics()
    if sem["index"] != 12 or sem["name"] != SLOT_NAME or sem["is_motor"]:
        errors.append("walk_slot12_semantics drifted")
    else:
        notes.append("walk action[12] semantics = gait_frequency, is_motor=false")

    try:
        refuse_slot12_as_motor({"index": 12, "is_motor": True, "name": "lSomething"})
        errors.append("is_motor=true must fail")
    except ValueError:
        notes.append("negative: slot 12 as motor refused")

    try:
        refuse_slot12_as_motor({"index": 12, "interpret_as": "13th_motor"})
        errors.append("13th_motor interpret must fail")
    except ValueError:
        notes.append("negative: 13th motor interpretation refused")

    try:
        refuse_slot12_as_motor({"name": "rAnkleRoll", "is_motor": False})
        errors.append("naming slot 12 as a leg joint must fail")
    except ValueError:
        notes.append("negative: slot 12 named as a leg motor refused")

    try:
        refuse_foreign_as_walk_gait_frequency("standup", 22, index=12)
        errors.append("standup 22 action[12] must not be walk gait_frequency")
    except ValueError:
        notes.append(
            f"negative: standup[12]={STANDUP_ACTION_MAP[12]} is a motor, not gait_frequency"
        )

    try:
        refuse_foreign_as_walk_gait_frequency("reactive", 15, index=WALK_FREQ_INDEX)
        errors.append("reactive action[12] must not be walk gait_frequency")
    except ValueError:
        notes.append("negative: reactive action[12] is a leg, not walk freq")

    try:
        refuse_foreign_as_walk_gait_frequency("reactive", 15, index=REACTIVE_FREQ_INDEX)
        errors.append("reactive action[14] must not impersonate walk action[12]")
    except ValueError:
        notes.append("negative: reactive freq[14] ≠ walk action[12]")

    try:
        hz = decode_walk_frequency_hz([0.0] * 12 + [2.0])
        if abs(hz - 2.0) > 1e-12:
            errors.append(f"clip ±0.5 failed: {hz}")
        else:
            notes.append("clip(+2.0) → 1.5+0.5=2.0")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        decode_walk_frequency_hz([0.0] * 22)
        errors.append("22-D decode must fail")
    except ValueError:
        notes.append("negative: standup 22-D refused as walk frequency decode")

    try:
        decode_walk_frequency_hz([0.0] * 15)
        errors.append("15-D decode must fail")
    except ValueError:
        notes.append("negative: reactive 15-D refused as walk frequency decode")

    try:
        cross = cross_assert_joint_map()
        if WALK_ACTION_MAP[12] != SLOT_NAME or not cross.get("ok"):
            errors.append("joint_map cross-assert failed")
        else:
            notes.append("cross-assert: joint_map[12] == gait_frequency")
    except AssertionError as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during gait_frequency test")
    else:
        notes.append("official K1.yaml untouched")

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
        f"[gait-frequency] {'PASS' if report['ok'] else 'FAIL'} "
        "action[12]=gait_frequency; not a motor"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
