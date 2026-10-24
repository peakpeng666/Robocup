#!/usr/bin/env python3
"""One-shot switcher integration suite (no Gym).

Composes switcher SM + deploy_call + standup/kick + BT cross-check.
Default assertion: empty context → official walk 344→13.
"""
from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from bt_skill_select import select_skill  # noqa: E402
from deploy_call import TRAINABLE as DEPLOY_TRAINABLE, DeployCall  # noqa: E402
from sm import CONTRACTS, DEFAULT_SKILL, TRAINABLE as SM_TRAINABLE, SwitcherSM  # noqa: E402
from standup_kick_contract import WALK  # noqa: E402

SUITE = (
    ("test_switcher_sm.py", "k1_suite_switcher_sm"),
    ("test_deploy_call.py", "k1_suite_deploy_call"),
    ("test_standup_kick_hardening.py", "k1_suite_standup_kick"),
    ("test_bt_deploy_crosscheck.py", "k1_suite_bt_deploy"),
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(name: str, path: Path) -> Any:
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    parts: dict[str, Any] = {}

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("integration suite imported Gym / Isaac Gym")

    if SM_TRAINABLE or DEPLOY_TRAINABLE:
        errors.append("switcher/deploy TRAINABLE must stay false")
    if CONTRACTS["walk"] != WALK or WALK != (344, 13):
        errors.append("suite walk contract drifted off 344→13")
    if DEFAULT_SKILL != "walk":
        errors.append("suite default skill must stay walk")

    idle_bt = select_skill()
    idle_tick = DeployCall().tick()
    idle_sm = SwitcherSM()
    if (
        not idle_bt.is_official_walk()
        or not idle_tick.is_official_walk()
        or idle_tick.contract != "344→13"
        or idle_sm.state.skill != "walk"
    ):
        errors.append("empty context must stay official walk 344→13")
    else:
        notes.append("suite default: empty context → walk 344→13")

    for filename, mod_name in SUITE:
        path = ROOT / filename
        if not path.is_file():
            errors.append(f"missing suite member {filename}")
            continue
        report = _load(mod_name, path).run(repo)
        parts[filename] = {"ok": bool(report.get("ok")), "errors": report.get("errors") or []}
        if report.get("ok"):
            notes.append(f"suite member PASS: {filename}")
        else:
            errors.extend(f"{filename}: {item}" for item in (report.get("errors") or ["FAIL"]))

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "parts": parts,
        "default": "walk 344→13",
        "trainable": False,
    }


def main() -> int:
    report = run()
    print(
        f"[switcher-suite] {'PASS' if report['ok'] else 'FAIL'} "
        "empty→walk 344→13; SM+deploy+standup/kick+BT"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
