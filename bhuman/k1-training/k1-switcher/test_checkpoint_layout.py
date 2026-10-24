#!/usr/bin/env python3
"""Walk checkpoint layout: official slots only; missing → SKIP; T1/reactive refused."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from checkpoint_layout import (  # noqa: E402
    TRAINABLE,
    WALK_SLOTS,
    WRITE_WEIGHTS,
    assert_layout_frozen,
    probe_layout,
    recorded_layout,
    refuse_foreign_on_walk_path,
    refuse_write_weights,
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
    skipped = False

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("checkpoint layout imported Gym")
    if TRAINABLE or WRITE_WEIGHTS:
        errors.append("checkpoint layout flags leaked")

    try:
        assert_layout_frozen(repo)
        notes.append("assert_layout_frozen: K1_walk.* slots; no write")
    except (AssertionError, ValueError, RuntimeError) as exc:
        errors.append(str(exc))

    try:
        layout = recorded_layout(repo)
        if not layout["foreign_forbidden_on_walk"]:
            errors.append("foreign-on-walk rule missing")
        else:
            notes.append("CHECKPOINT-LAYOUT.md names K1_walk.pth / onnx")
    except AssertionError as exc:
        errors.append(str(exc))

    probe = probe_layout(repo)
    if probe["missing"]:
        if probe["status"] != "SKIP":
            errors.append("missing weights must be honest SKIP")
        else:
            skipped = True
            notes.append(f"weights SKIP: missing {len(probe['missing'])} official slots")
    elif probe["status"] != "PASS":
        errors.append("present official slots must PASS layout presence")
    else:
        notes.append("official walk slots present on disk")

    dest = WALK_SLOTS[0]["rel"]
    for placement, label in (
        ({"dest": dest, "name": "model.pth", "family": "huoshen_t1"}, "T1 model.pth"),
        ({"dest": dest, "name": "T1_walk.pth", "family": "T1"}, "T1_walk.pth"),
        ({"dest": dest, "name": "K1_Reactive.pth", "family": "reactive"}, "reactive"),
        (
            {"dest": dest, "name": "K1_walk.pth", "family": "nusim", "obs": 79},
            "NUSim as K1_walk.pth",
        ),
    ):
        try:
            refuse_foreign_on_walk_path(placement)
            errors.append(f"{label} on walk path must raise")
        except ValueError:
            notes.append(f"negative: {label} refused on walk default path")

    try:
        refuse_write_weights(dest)
        errors.append("write weights must raise")
    except RuntimeError:
        notes.append("negative: write K1_walk.pth refused")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official K1.yaml untouched 344→13")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "skipped": skipped,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[ckpt-layout] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_walk slots; missing SKIP; foreign refused"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
