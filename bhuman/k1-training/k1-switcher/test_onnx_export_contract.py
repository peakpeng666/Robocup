#!/usr/bin/env python3
"""Negatives for the official walk ONNX export contract (no real export).

Default exportable path is walk 344→13. Kick / standup / reactive / Huoshen
dims cannot impersonate it. Hot-swap into the official actor is refused.
Missing checkpoint is an honest SKIP, not a fake export.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from onnx_export_contract import (  # noqa: E402
    DEFAULT_EXPORT,
    IMPLEMENTED,
    NOT_DEFAULT_EXPORT,
    TRAINABLE,
    WALK_ONNX_REL,
    WALK_PTH_REL,
    WRITE_WEIGHTS,
    assert_onnx_export_frozen,
    export_readiness,
    refuse_foreign_as_default_export,
    refuse_hot_swap_into_official_actor,
    refuse_write_official_onnx,
    require_default_export_claim,
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
        errors.append("onnx export contract imported Gym / Isaac Gym")
    if TRAINABLE or IMPLEMENTED or WRITE_WEIGHTS:
        errors.append("onnx export TRAINABLE/IMPLEMENTED/WRITE_WEIGHTS must stay false")

    try:
        assert_onnx_export_frozen()
        notes.append("export frozen: TRAINABLE=false; default walk 344→13; no write")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        require_default_export_claim(DEFAULT_EXPORT)
        notes.append("default exportable path is official walk 344→13")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        require_default_export_claim({"skill": "walk", "obs": 59, "act": 13})
        errors.append("kick dims as default export must raise")
    except ValueError:
        notes.append("negative: default export missing 344→13 declaration refused")

    for skill, (obs, act) in NOT_DEFAULT_EXPORT.items():
        try:
            refuse_foreign_as_default_export(skill, obs, act)
            errors.append(f"{skill} {obs}→{act} as default export must raise")
        except ValueError:
            notes.append(f"negative: {skill} {obs}→{act} refused as default walk export")

    try:
        refuse_hot_swap_into_official_actor({"hot_swap_into_official_actor": True})
        errors.append("hot-swap into official actor must raise")
    except ValueError:
        notes.append("negative: hot-swap ONNX into official actor refused")

    try:
        refuse_hot_swap_into_official_actor({"replace_official_onnx": True})
        errors.append("replace_official_onnx must raise")
    except ValueError:
        notes.append("negative: replace official ONNX refused")

    try:
        refuse_hot_swap_into_official_actor({"swap_walk_with": "kick"})
        errors.append("swap walk ONNX with kick must raise")
    except ValueError:
        notes.append("negative: walk/kick ONNX swap refused")

    try:
        refuse_write_official_onnx(WALK_ONNX_REL)
        errors.append("writing official ONNX must raise")
    except RuntimeError:
        notes.append("official K1_walk.onnx write refused")

    ready = export_readiness(repo, user_approved=False)
    if ready.get("would_export"):
        errors.append("export_readiness must never set would_export=true")
    if ready.get("status") != "SKIP" or not ready.get("skipped"):
        errors.append("export_readiness must stay honest SKIP")
    else:
        notes.append(ready.get("reason") or "export SKIP")

    approved = export_readiness(repo, user_approved=True)
    if approved.get("would_export") or not approved.get("skipped"):
        errors.append("even with user approval the stub must not export")
    else:
        notes.append("user approval still does not export (IMPLEMENTED=false)")

    if (repo / WALK_PTH_REL).is_file():
        notes.append("checkpoint present on disk; stub still did not export")
    else:
        notes.append("skipped (missing optional runtime): no K1_walk.pth")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official K1.yaml drifted off walk 344→13")
    else:
        notes.append("official K1.yaml still 344→13 (export stub did not edit it)")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "skipped": bool(ready.get("skipped")),
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[onnx-export] {'PASS' if report['ok'] else 'FAIL'} "
        "default walk 344→13; no real export"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
