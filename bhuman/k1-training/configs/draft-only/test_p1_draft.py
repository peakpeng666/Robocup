#!/usr/bin/env python3
"""Assert P1 draft-only files do not rewrite official walk rewards or 344."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DRAFT = ROOT / "walk-p1-factors-v0.json"

OFFICIAL_REWARD_NEEDLES = (
    ("tracking_lin_vel_x:", "0.75"),
    ("tracking_lin_vel_y:", "0.75"),
    ("tracking_ang_vel:", "0.375"),
    ("action_rate:", "-1."),
    ("still_proportion:", "0.1"),
    ("num_observations:", "344"),
    ("num_actions:", "13"),
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[3], ROOT.parents[4], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _has_key_value(text: str, key: str, value: str) -> bool:
    pattern = rf"{re.escape(key)}\s*{re.escape(value)}"
    return re.search(pattern, text) is not None


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []

    if not DRAFT.is_file():
        return {"ok": False, "errors": ["missing walk-p1-factors-v0.json"], "notes": []}
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    if data.get("draft_only") is not True or data.get("do_not_pass_to_train_py") is not True:
        errors.append("draft file must set draft_only and do_not_pass_to_train_py")
    if data.get("trainable") is not False:
        errors.append("draft file must stay trainable=false")
    baseline = data.get("baseline") or {}
    if baseline.get("num_observations") != 344 or baseline.get("num_actions") != 13:
        errors.append("draft baseline drifted off 344→13")
    else:
        notes.append("draft baseline stays 344→13")

    snap = data.get("official_snapshot") or {}
    if snap.get("num_observations") != 344 or snap.get("rewards.scales.tracking_lin_vel_x") != 0.75:
        errors.append("official_snapshot lost the frozen reward / dim numbers")

    for factor_name, factor in (data.get("factors") or {}).items():
        if factor.get("rewrites_344") is not False:
            errors.append(f"{factor_name} must keep rewrites_344=false")
        if factor.get("status") != "draft":
            errors.append(f"{factor_name} must stay status=draft")
        proposed = factor.get("proposed_only") or {}
        if "num_observations" in proposed and proposed["num_observations"] != 344:
            errors.append(f"{factor_name} proposed a dim rewrite")
        if proposed.get("actor_obs") not in (None, 344):
            errors.append(f"{factor_name} actor_obs is not 344")
    notes.append("five P1 factors are draft-only and do not rewrite 344")

    for rel in data.get("do_not_edit") or []:
        path = repo / rel
        if not path.is_file():
            errors.append(f"missing official file {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".yaml":
            for key, value in OFFICIAL_REWARD_NEEDLES:
                if not _has_key_value(text, key, value):
                    errors.append(f"{rel} no longer has official {key} {value}")
        elif path.name == "walk-reference-stability-v1.json":
            ref = json.loads(text)
            algo = ref.get("algorithm") or {}
            if algo.get("reference_mean_penalty") != 1.0:
                errors.append("walk-reference-stability-v1.json reference_mean_penalty was rewritten")
            if algo.get("critic_warmup_iterations") != 20:
                errors.append("walk-reference-stability-v1.json critic warmup was rewritten")
        elif path.name == "walk-critic-stability-v1.json":
            ref = json.loads(text)
            if (ref.get("algorithm") or {}).get("critic_warmup_iterations") != 20:
                errors.append("walk-critic-stability-v1.json critic warmup was rewritten")
    if not errors:
        notes.append("official K1.yaml rewards and stability v1 jsons unchanged")

    script = repo / "bhuman/k1-training/scripts/run_walk_stability.sh"
    if script.is_file():
        sh = script.read_text(encoding="utf-8")
        if "draft-only" in sh or "walk-p1-factors" in sh:
            errors.append("run_walk_stability.sh must not load draft-only files")
        if "stability-v1.json" not in sh:
            errors.append("run_walk_stability.sh lost the official v1 preset path")
        else:
            notes.append("run_walk_stability.sh still uses official v1 presets only")
    else:
        errors.append("missing run_walk_stability.sh")

    doc = repo / "bhuman/docs/P1-CONFIG-DIFF-DRAFT.md"
    if not doc.is_file():
        errors.append("missing P1-CONFIG-DIFF-DRAFT.md")
    else:
        text = doc.read_text(encoding="utf-8")
        missing = [n for n in ("draft-only", "344→13", "0.75", "不改默认") if n not in text]
        if missing:
            errors.append(f"P1-CONFIG-DIFF-DRAFT.md missing {missing}")
        else:
            notes.append("P1 config draft doc present")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[p1-draft] {'PASS' if report['ok'] else 'FAIL'} official rewards untouched")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
