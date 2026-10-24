#!/usr/bin/env python3
"""Read-only PD domain-gap: train p60 vs robot p25; no K1.yaml write-back."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pd_domain_gap_contract import (  # noqa: E402
    ROBOT_ANKLE_ROLL_P,
    TRAIN_ANKLE_ROLL_P,
    TRAINABLE,
    WRITE_YAML,
    assert_pd_gap_frozen,
    recorded_gap,
    refuse_train_pd_writeback,
    refuse_unified_pd_as_closed_gap,
    refuse_write_yaml,
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

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("pd domain-gap imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("PD gap flags leaked")

    try:
        assert_pd_gap_frozen(repo)
        notes.append("assert_pd_gap_frozen: intentional p60 vs p25; read-only")
    except (AssertionError, ValueError, RuntimeError) as exc:
        errors.append(str(exc))

    try:
        gap = recorded_gap(repo)
        if (
            gap["train_ankle_roll_p"] != TRAIN_ANKLE_ROLL_P
            or gap["robot_ankle_roll_p"] != ROBOT_ANKLE_ROLL_P
            or not gap["intentional"]
            or gap["closed"]
        ):
            errors.append("recorded gap drifted")
        else:
            notes.append("recorded intentional open gap: train p60 vs robot p25")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        refuse_train_pd_writeback({"Ankle_Roll": ROBOT_ANKLE_ROLL_P})
        errors.append("p25 write-back onto K1.yaml must raise")
    except ValueError:
        notes.append("negative: train PD write-back p25 refused")

    try:
        refuse_write_yaml("bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml")
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        refuse_unified_pd_as_closed_gap({"unified": True, "gap_closed": True})
        errors.append("unified PD as closed gap must raise")
    except ValueError:
        notes.append("negative: unified PD ≠ closed domain gap")

    try:
        refuse_unified_pd_as_closed_gap(
            {"source": "train_yaml", "Ankle_Roll": ROBOT_ANKLE_ROLL_P}
        )
        errors.append("train YAML claiming p25 must raise")
    except ValueError:
        notes.append("negative: train Ankle_Roll p25 refused")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if '"Ankle_Roll": 60.' not in walk:
        errors.append("live K1.yaml Ankle_Roll is no longer p60")
    elif "num_observations: 344" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official K1.yaml untouched: 344→13 + Ankle_Roll p60")

    return {"ok": not errors, "errors": errors, "notes": notes, "walk": "344→13"}


def main() -> int:
    report = run()
    print(
        f"[pd-gap] {'PASS' if report['ok'] else 'FAIL'} "
        "train p60 vs robot p25; no write-back"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
