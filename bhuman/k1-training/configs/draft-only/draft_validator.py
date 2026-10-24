"""Validate P1 draft-only files (no Gym, no train.py patch).

A legal draft must set draft_only: true and must not be read by
run_walk_stability.sh or official --config_patch. Official live rewards
(still_proportion / tracking_* / action_rate / reference_mean_penalty)
must stay on K1.yaml / stability-v1; drafts may only propose.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

LIVE_REWARD_KEYS = (
    "still_proportion",
    "tracking_lin_vel_x",
    "tracking_lin_vel_y",
    "tracking_ang_vel",
    "action_rate",
    "reference_mean_penalty",
)
LIVE_REWARD_VALUES = {
    "still_proportion": 0.1,
    "tracking_lin_vel_x": 0.75,
    "tracking_lin_vel_y": 0.75,
    "tracking_ang_vel": 0.375,
    "action_rate": -1.0,
    "reference_mean_penalty": 1.0,
}
LIVE_TARGETS = {"live", "k1.yaml", "config_patch", "run_walk_stability", "official"}


def require_draft_only_flag(data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or data.get("draft_only") is not True:
        raise ValueError("draft file must set draft_only: true")
    if data.get("do_not_pass_to_train_py") is not True:
        raise ValueError("draft file must set do_not_pass_to_train_py: true")
    if data.get("trainable") is not False:
        raise ValueError("draft file must stay trainable=false")


def refuse_as_official_config_patch(data: dict[str, Any]) -> None:
    """A draft is not a legal --config_patch / live overlay."""
    if data.get("draft_only") is not True:
        raise ValueError("file without draft_only:true is not a legal draft")
    if data.get("apply_to_live") is True or data.get("config_patch") is True:
        raise ValueError("draft-only must not be applied as a live config_patch")
    if data.get("do_not_pass_to_train_py") is not True:
        raise ValueError("draft-only must refuse train.py --config_patch")


def refuse_overwrite_live_rewards(claim: dict[str, Any]) -> None:
    """Refuse writing draft proposed values onto live official keys."""
    if not isinstance(claim, dict):
        raise ValueError("live-overwrite claim must be a mapping")
    target = str(claim.get("target") or "")
    key = str(claim.get("key") or "")
    hits = [name for name in LIVE_REWARD_KEYS if name in key]
    if target in LIVE_TARGETS and hits:
        raise ValueError(
            f"draft must not overwrite live {hits[0]} "
            f"(official {LIVE_REWARD_VALUES.get(hits[0])})"
        )


def refuse_stability_script_reads_draft(script_text: str) -> None:
    if "draft-only" in script_text or "walk-p1-factors" in script_text:
        raise ValueError("run_walk_stability.sh must not load draft-only files")


def refuse_dim_rewrite(data: dict[str, Any]) -> None:
    baseline = data.get("baseline") or {}
    if baseline.get("num_observations") not in (None, 344):
        raise ValueError("draft baseline must stay 344")
    if baseline.get("num_actions") not in (None, 13):
        raise ValueError("draft baseline must stay 13")
    for name, factor in (data.get("factors") or {}).items():
        proposed = factor.get("proposed_only") or {}
        if proposed.get("num_observations") not in (None, 344):
            raise ValueError(f"{name} must not rewrite num_observations")
        if proposed.get("actor_obs") not in (None, 344):
            raise ValueError(f"{name} actor_obs must stay 344")


def official_live_rewards_untouched(repo: Path) -> None:
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    if "still_proportion: 0.1" not in text or "action_rate: -1." not in text:
        raise AssertionError("official K1.yaml live rewards drifted")
    if "tracking_lin_vel_x: 0.75" not in text:
        raise AssertionError("official tracking_lin_vel_x drifted")
    ref = repo / "bhuman/k1-training/configs/walk-reference-stability-v1.json"
    import json

    algo = (json.loads(ref.read_text(encoding="utf-8")).get("algorithm") or {})
    if algo.get("reference_mean_penalty") != 1.0:
        raise AssertionError("official reference_mean_penalty drifted")


def assert_current_draft(repo: Path, data: dict[str, Any], script_text: str) -> None:
    require_draft_only_flag(data)
    refuse_as_official_config_patch(data)
    refuse_dim_rewrite(data)
    refuse_stability_script_reads_draft(script_text)
    official_live_rewards_untouched(repo)
