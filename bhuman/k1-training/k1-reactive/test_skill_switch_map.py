#!/usr/bin/env python3
"""Live static tests for skill_switch_map.py (no Gym).

Covers checklist T1/T2/T3/T5 and P2 phase wrap. History memcpy (H1–H6)
stays in the empty-shell file.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import HUOSHEN_T1_ACT, NUM_ACTIONS, WALK_ACT  # noqa: E402
from skill_switch_map import (  # noqa: E402
    HOT_SWAP_FORBIDDEN,
    advance_gait,
    first_step_last_action,
    history_policy,
    kick_action_to_reactive,
    refuse_hot_swap,
    reactive_action_to_walk,
    walk_action_to_reactive,
    walk_frequency_hz,
)


def run() -> dict[str, Any]:
    errors: list[str] = []
    notes: list[str] = []

    walk = [0.01 * i for i in range(WALK_ACT)]
    walk[12] = 0.25
    mapped = walk_action_to_reactive(walk, head_yaw=0.3, head_pitch=-0.1)
    if len(mapped) != NUM_ACTIONS:
        errors.append(f"reactive map dim {len(mapped)}")
    if mapped[2:14] != walk[:12]:
        errors.append("T1: walk legs did not land in reactive[2:14]")
    else:
        notes.append("T1 PASS: walk action[:12] == reactive[2:14]")
    if mapped[14] != walk[12] or mapped[0] != 0.3 or mapped[1] != -0.1:
        errors.append("T2/P4: freq or head slots wrong")
    else:
        notes.append("T2 PASS: walk action[12] == reactive[14]; head from caller")
    back = reactive_action_to_walk(mapped)
    if back != walk:
        errors.append("reactive -> walk is not an inverse on legs+freq")
    else:
        notes.append("T1 inverse PASS: reactive -> walk drops head")

    kick = list(walk)
    if kick_action_to_reactive(kick)[2:14] != kick[:12]:
        errors.append("kick family did not reuse the walk slot map")
    else:
        notes.append("kick shares the 13-D family map")

    first = first_step_last_action("walk", walk, "reactive")
    if first[2:14] != walk[:12]:
        errors.append("T3: first reactive last_action did not keep walk legs")
    else:
        notes.append("T3 PASS: first-step last_action keeps previous legs")

    if abs(walk_frequency_hz([0] * 12 + [0.0]) - 1.5) > 1e-9:
        errors.append("base frequency is not 1.5 Hz")
    if abs(walk_frequency_hz([0] * 12 + [0.9]) - 2.0) > 1e-9:
        errors.append("frequency clip +0.5 failed")
    g0 = 0.9
    g1 = advance_gait(g0, 1.5, 0.020)
    expected = (0.9 + 0.020 * 1.5) % 1.0
    if abs(g1 - expected) > 1e-12:
        errors.append(f"P2 gait wrap {g1} != {expected}")
    else:
        notes.append("P2 PASS: gait += dt*freq (mod 1)")

    try:
        refuse_hot_swap("walk", "kick")
        errors.append("T5: walk/kick hot-swap must raise")
    except ValueError:
        notes.append("T5 PASS: walk/kick 13==13 is not a swap permit")
    try:
        refuse_hot_swap("reactive", "huoshen_t1")
        errors.append("T5: reactive/T1 hot-swap must raise")
    except ValueError:
        notes.append("T5 PASS: reactive/T1 15==15 is not a load permit")
    if NUM_ACTIONS != HUOSHEN_T1_ACT:
        errors.append("catalog assumes 15==15 coincidence; contract drifted")
    if ("walk", "kick") not in HOT_SWAP_FORBIDDEN:
        errors.append("HOT_SWAP_FORBIDDEN missing walk/kick")

    hist = history_policy("walk")
    if hist["flat"] != 344 or hist["frames"] * hist["frame_dim"] + hist["tail_dim"] != 344:
        errors.append("walk history policy drifted from 10×32+24=344")
    else:
        notes.append("H-doc PASS: walk history 10×32+24 documented, not memcpy'd")
    react = history_policy("reactive")
    if react["flat_forbidden"] == 344:
        errors.append("reactive flatten collided with walk 344")
    if history_policy("kick")["frames"] != 0:
        errors.append("kick history must stay 0")

    try:
        walk_action_to_reactive([0.0] * 12)
        errors.append("short walk action must raise")
    except ValueError:
        notes.append("dim guard: short walk action rejected")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[skill-switch-map] {'PASS' if report['ok'] else 'FAIL'} static T1/T2/T3/T5/P2")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
