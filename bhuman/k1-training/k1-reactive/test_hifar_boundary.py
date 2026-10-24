#!/usr/bin/env python3
"""Executable HiFAR / Huoshen T1 boundary (no weights, no Gym).

Confirms this checkout cannot load T1 weights onto a K1 actor and cannot
treat Huoshen 58-D obs as official walk 344. Doc pointers: GLOBAL §6.1/§6.2
and research-inputs (huoshen_findings.md / RESEARCH-BRANCH.md).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import HUOSHEN_T1_ACT, HUOSHEN_T1_OBS, WALK_ACT, WALK_OBS  # noqa: E402
from hifar_boundary import (  # noqa: E402
    HIFAR_ARXIV,
    HUOSHEN_ARXIV,
    RESEARCH_INPUTS,
    assert_hifar_boundary,
    refuse_huoshen_obs_as_walk,
    refuse_t1_weight_on_k1_actor,
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
        errors.append("HiFAR boundary imported Gym")

    try:
        assert_hifar_boundary(repo)
        notes.append("assert_hifar_boundary: no T1 weights, no 58-as-344, docs present")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    for path in ("model.pth", "K1_walk.pth"):
        try:
            refuse_t1_weight_on_k1_actor(path)
            errors.append(f"{path} must not load onto a K1 / HiFAR actor")
        except ValueError:
            notes.append(f"refused {path} as a K1 actor weight")

    try:
        refuse_huoshen_obs_as_walk(HUOSHEN_T1_OBS, HUOSHEN_T1_ACT)
        errors.append("Huoshen 58→15 must raise when claimed as walk")
    except ValueError:
        notes.append("Huoshen T1 58→15 refused as official walk 344→13")
    try:
        refuse_huoshen_obs_as_walk(WALK_OBS, HUOSHEN_T1_ACT)
        errors.append("344+15 must not be a walk actor pair")
    except ValueError:
        notes.append("walk 344 + Huoshen 15-D action refused")

    if WALK_OBS == 344 and WALK_ACT == 13 and HUOSHEN_T1_OBS != WALK_OBS:
        notes.append("official walk stays 344→13; Huoshen 58 is a different family")
    else:
        errors.append("walk / Huoshen dim constants collided")

    for rel in RESEARCH_INPUTS:
        text = (repo / rel).read_text(encoding="utf-8")
        notes.append(f"research-input present: {rel}")
        if rel.endswith("HIFAR-VS-STANDUP.md") and HIFAR_ARXIV in text:
            notes.append(f"HIFAR pointer {HIFAR_ARXIV} ≠ standup 73→22 / 72→22")
        if rel.endswith("GLOBAL-HUMANOID-SURVEY-20261024.md") and HUOSHEN_ARXIV in text:
            notes.append(f"GLOBAL cites 火神 {HUOSHEN_ARXIV} and HiFAR separately")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[hifar-boundary] {'PASS' if report['ok'] else 'FAIL'} "
        "HiFAR ≠ standup; Huoshen 58 ≠ walk 344"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
