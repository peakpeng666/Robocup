#!/usr/bin/env python3
"""Negative fixtures for P1 draft-only isolation (no Gym, no train).

Legal draft: draft_only=true, not read by run_walk_stability.sh / official
config_patch. Draft proposed values must not overwrite live
still_proportion / tracking_* / action_rate / reference_mean_penalty.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from draft_validator import (  # noqa: E402
    LIVE_REWARD_KEYS,
    STABILITY_OFFICIAL_PRESET,
    assert_current_draft,
    official_patches_isolated,
    refuse_as_official_config_patch,
    refuse_official_patch_imports_draft,
    refuse_overwrite_live_rewards,
    refuse_stability_script_reads_draft,
    require_draft_only_flag,
    require_every_draft_file,
    require_stability_script_official_preset,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[3], ROOT.parents[4], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []

    current = json.loads((ROOT / "walk-p1-factors-v0.json").read_text(encoding="utf-8"))
    script = (repo / "bhuman/k1-training/scripts/run_walk_stability.sh").read_text(
        encoding="utf-8"
    )
    try:
        assert_current_draft(repo, current, script)
        notes.append("current draft: draft_only=true; stability script does not read it")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        checked = require_every_draft_file(ROOT)
        notes.append(f"draft-only dir scan: {checked}")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        official_patches_isolated(repo)
        notes.append("official walk-*-stability-v1.json do not import draft-only")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        require_draft_only_flag({"trainable": False, "do_not_pass_to_train_py": True})
        errors.append("missing draft_only:true must raise")
    except ValueError:
        notes.append("negative: draft without draft_only:true refused")

    try:
        refuse_as_official_config_patch(
            {
                "draft_only": True,
                "do_not_pass_to_train_py": True,
                "trainable": False,
                "apply_to_live": True,
            }
        )
        errors.append("apply_to_live draft must raise")
    except ValueError:
        notes.append("negative: draft apply_to_live / live config_patch refused")

    try:
        refuse_as_official_config_patch(
            {
                "draft_only": True,
                "do_not_pass_to_train_py": True,
                "trainable": False,
                "config_patch": True,
            }
        )
        errors.append("draft config_patch:true must raise")
    except ValueError:
        notes.append("negative: draft marked config_patch=true refused")

    try:
        refuse_as_official_config_patch({"draft_only": False, "do_not_pass_to_train_py": True})
        errors.append("draft_only=false must raise")
    except ValueError:
        notes.append("negative: draft_only=false refused as official patch")

    for key in LIVE_REWARD_KEYS:
        try:
            refuse_overwrite_live_rewards(
                {"target": "k1.yaml", "key": key, "draft_value": 0.0}
            )
            errors.append(f"overwrite live {key} must raise")
        except ValueError:
            notes.append(f"negative: draft must not overwrite live {key}")

    try:
        refuse_overwrite_live_rewards({"target": "config_patch", "key": "still_proportion"})
        errors.append("config_patch overwrite of still_proportion must raise")
    except ValueError:
        notes.append("negative: official config_patch cannot eat draft still_proportion")

    try:
        refuse_overwrite_live_rewards(
            {"target": "run_walk_stability", "key": "rewards.scales.action_rate"}
        )
        errors.append("stability overwrite of action_rate must raise")
    except ValueError:
        notes.append("negative: run_walk_stability cannot eat draft action_rate")

    try:
        refuse_overwrite_live_rewards(
            {"target": "official", "key": "algorithm.reference_mean_penalty"}
        )
        errors.append("official overwrite of reference_mean_penalty must raise")
    except ValueError:
        notes.append("negative: official reference_mean_penalty cannot eat draft anneal")

    try:
        refuse_stability_script_reads_draft(
            'patch_json=.../configs/draft-only/walk-p1-factors-v0.json\n--config_patch "$patch_json"'
        )
        errors.append("stability script reading draft-only must raise")
    except ValueError:
        notes.append("negative: run_walk_stability.sh loading draft-only refused")

    try:
        require_stability_script_official_preset(script)
        if STABILITY_OFFICIAL_PRESET not in script:
            errors.append("current stability script lost official preset path")
        else:
            notes.append("current run_walk_stability.sh stays on official v1 presets")
    except ValueError:
        errors.append("current stability script must not mention draft-only")

    try:
        require_stability_script_official_preset(
            'exec train.py --task K1 --config_patch "$inline"'
        )
        errors.append("stability script without official v1 preset must raise")
    except ValueError:
        notes.append("negative: stability script missing official v1 preset refused")

    try:
        refuse_official_patch_imports_draft(
            '{"note":"load configs/draft-only/walk-p1-factors-v0.json"}'
        )
        errors.append("official patch importing draft-only must raise")
    except ValueError:
        notes.append("negative: official config_patch importing draft-only refused")

    try:
        refuse_overwrite_live_rewards({"target": "notebook", "key": "still_proportion"})
        notes.append("non-live target may discuss proposed still_proportion")
    except ValueError:
        errors.append("proposed-only discussion must not raise")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[draft-validator] {'PASS' if report['ok'] else 'FAIL'} "
        "draft_only; live rewards not overwritten"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
