"""Highest-priority forbidden-claim pack (no Gym).

Each case MUST raise. If a refuse is silent, the gate goes red.
Cases: T1 as walk, standup→kick, SimRobot as fast standup, latent into 344,
draft overwrite live, unified PD as closed gap, sibling merge into 344,
T1 ONNX as K1 walk, BehaviorControl replacing walk, TeamComm into 344,
mix 128/512, fallen as SkillRequest Type, GetUp incomplete kick,
stay on standup after getup, kick replacing walk, cfg dim rewrite,
kickModel pointing at T1, kick ONNX occupying the walk slot,
getUp overwriting walk, T1 getUp as K1, fast standup as Isaac,
Simulated speed as closed PD, fabricated Competition getUp,
standAnkleStiffness as closed PD, Competition diffs changing net slot,
policySwitch as net swap, shiftBall as dim change,
kickPolicy as default walk, maxAcc as net swap,
getNextTargetRequest as hot-swap train graph, speed gear as net swap,
ball-net off as dim change, intercept as kick default,
avoidance as hot-swap train, shouldStop as kick default,
stand as dim change, ball unseen as hot-swap train,
empty SkillRequest as kick.

Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
ESTIMATORS = ROOT.parent / "k1-estimators"
DRAFT = ROOT.parent / "configs" / "draft-only"
SCRIPTS = ROOT.parent / "scripts"
for extra in (ROOT, REACTIVE, ESTIMATORS, DRAFT, SCRIPTS):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from behavior_control_handoff import refuse_behavior_replaces_walk  # noqa: E402
from checkpoint_layout import refuse_foreign_on_walk_path  # noqa: E402
from compressed_teamcomm_shape import refuse_teamcomm_into_344  # noqa: E402
from draft_validator import refuse_overwrite_live_rewards  # noqa: E402
from falldown_motion_chain import (  # noqa: E402
    refuse_fallen_as_skill_request,
    refuse_kick_before_getup_done,
)
from force_walk_afterwards import (  # noqa: E402
    refuse_getup_done_direct_kick,
    refuse_stay_on_standup_after_getup,
)
from kick_engine_boundary import refuse_kick_replaces_walk  # noqa: E402
from kick_onnx_naming import refuse_kick_onnx_on_walk_slot  # noqa: E402
from cfg_copy_crosscheck import refuse_fabricate_competition_getup  # noqa: E402
from getup_engine_cfg_audit import (  # noqa: E402
    refuse_fast_standup_as_isaac,
    refuse_getup_overwrites_walk,
    refuse_t1_getup_as_k1,
)
from competition_walk_diff import refuse_competition_diff_net_slot  # noqa: E402
from motor_parameters_audit import refuse_simulated_speed_as_pd_closed  # noqa: E402
from ball_network_active import refuse_ball_net_off_as_dim_change  # noqa: E402
from get_next_target_request import refuse_getnext_as_hot_swap_train  # noqa: E402
from intercept_avoid_bypass import (  # noqa: E402
    refuse_avoid_as_hot_swap_train,
    refuse_intercept_as_kick_default,
)
from walk_stay_remaining import (  # noqa: E402
    refuse_ball_unseen_as_hot_swap_train,
    refuse_empty_skill_as_kick,
    refuse_should_stop_as_kick_default,
    refuse_stand_as_dim_change,
)
from max_acceleration_diff import refuse_max_acc_as_net_swap  # noqa: E402
from policy_switch_threshold import refuse_policy_switch_as_net_swap  # noqa: E402
from speed_gear_diff import refuse_speed_gear_as_net_swap  # noqa: E402
from shift_ball_position import refuse_shift_ball_as_dim_change  # noqa: E402
from stand_ankle_stiffness import refuse_stand_ankle_as_pd_closed  # noqa: E402
from walk_kick_policy_switch import refuse_kick_policy_as_default_walk  # noqa: E402
from walking_engine_cfg_audit import (  # noqa: E402
    refuse_cfg_dim_rewrite,
    refuse_kickmodel_points_t1,
)
from hifar_boundary import refuse_huoshen_obs_as_walk, refuse_t1_weight_on_k1_actor  # noqa: E402
from hooks import refuse_concat_latent_onto_walk  # noqa: E402
from official_sibling_tasks_audit import refuse_merge_sibling_into_344  # noqa: E402
from onnx_deploy_path_crosscheck import refuse_t1_onnx_as_k1_walk  # noqa: E402
from pd_domain_gap_contract import refuse_unified_pd_as_closed_gap  # noqa: E402
from sm import LEGAL_EDGES, SwitcherSM  # noqa: E402
from standup_kick_contract import refuse_simrobot_as_fast_standup  # noqa: E402
from teamcomm_128_vs_512 import refuse_mix_128_512  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13

CaseFn = Callable[[], None]


def _case_t1_as_walk() -> None:
    refuse_t1_weight_on_k1_actor("model.pth")


def _case_huoshen_obs_as_walk() -> None:
    refuse_huoshen_obs_as_walk(58, 15)


def _case_t1_on_walk_slot() -> None:
    refuse_foreign_on_walk_path(
        {
            "dest": "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth",
            "name": "model.pth",
            "family": "T1",
        }
    )


def _case_standup_to_kick() -> None:
    if ("standup", "kick") in LEGAL_EDGES or ("fast_standup", "kick") in LEGAL_EDGES:
        return
    sm = SwitcherSM()
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted:
        raise ValueError("fixture: fallen must enter standup before kick refuse")
    kicked = sm.request("kick")
    if kicked.accepted:
        return
    raise ValueError("standup→kick refused")


def _case_simrobot_as_fast() -> None:
    refuse_simrobot_as_fast_standup(
        {"simrobot_pass": True, "impersonates": "fast_standup"}
    )


def _case_latent_into_344() -> None:
    refuse_concat_latent_onto_walk([0.0] * WALK_OBS, [0.0] * 8)


def _case_draft_write_live() -> None:
    refuse_overwrite_live_rewards(
        {"target": "k1.yaml", "key": "reference_mean_penalty"}
    )


def _case_unified_pd_closed() -> None:
    refuse_unified_pd_as_closed_gap({"unified": True, "gap_closed": True})


def _case_sibling_merge_into_344() -> None:
    refuse_merge_sibling_into_344({"task": "K1_Ball", "concat_into": WALK_OBS})


def _case_t1_onnx_as_k1_walk() -> None:
    refuse_t1_onnx_as_k1_walk("T1_walk.onnx")


def _case_behavior_replaces_walk() -> None:
    refuse_behavior_replaces_walk({"replaces_walk": True, "default_skill": "kick"})


def _case_teamcomm_into_344() -> None:
    refuse_teamcomm_into_344({"compressed_into_344": True, "obs": WALK_OBS})


def _case_mix_128_512() -> None:
    refuse_mix_128_512({"overwrite_128_with_512": True, "mix": True})


def _case_fallen_as_skill_request() -> None:
    refuse_fallen_as_skill_request({"fallen_is_skill_request_type": True})


def _case_getup_incomplete_kick() -> None:
    refuse_kick_before_getup_done()


def _case_stay_on_standup_after_getup() -> None:
    refuse_stay_on_standup_after_getup({"stay_on_standup_after_getup": True})


def _case_getup_done_direct_kick() -> None:
    refuse_getup_done_direct_kick()


def _case_kick_replaces_walk() -> None:
    refuse_kick_replaces_walk({"replaces_walk": True, "kick_as_walk_baseline": True})


def _case_cfg_dim_rewrite() -> None:
    refuse_cfg_dim_rewrite({"cfg_dim_changed": True, "numInput": 365, "slot": "walk"})


def _case_kickmodel_t1() -> None:
    refuse_kickmodel_points_t1({"kickModel": "T1_kick_inner.onnx"})


def _case_kick_onnx_on_walk_slot() -> None:
    refuse_kick_onnx_on_walk_slot(
        {
            "dest": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx",
            "name": "K1_kick_inner.onnx",
            "family": "kick",
        }
    )


def _case_getup_overwrites_walk() -> None:
    refuse_getup_overwrites_walk(
        {"getup_overwrites_walk": True, "policyName": "K1_walk.onnx"}
    )


def _case_t1_getup_as_k1() -> None:
    refuse_t1_getup_as_k1({"policyName": "T1.onnx", "slot": "k1_getup"})


def _case_fast_standup_as_isaac() -> None:
    refuse_fast_standup_as_isaac({"task": "K1_fast_standup", "registered": True})


def _case_simulated_speed_as_pd_closed() -> None:
    refuse_simulated_speed_as_pd_closed(
        {"simulated_speed_closes_pd": True, "source": "simulated_speed"}
    )


def _case_fabricate_competition_getup() -> None:
    refuse_fabricate_competition_getup(
        {"fabricate_competition_getup": True, "role": "CompetitionWalk/K1"}
    )


def _case_stand_ankle_as_pd_closed() -> None:
    refuse_stand_ankle_as_pd_closed(
        {"stand_ankle_closes_pd": True, "source": "standAnkleStiffness"}
    )


def _case_competition_diff_net_slot() -> None:
    refuse_competition_diff_net_slot(
        {"competition_changes_net_slot": True, "numInput": 365, "modelName": "T1_walk.onnx"}
    )


def _case_policy_switch_as_net_swap() -> None:
    refuse_policy_switch_as_net_swap(
        {
            "policy_switch_as_net_swap": True,
            "source": "ballDistancePolicySwitch",
            "walk_obs": 365,
        }
    )


def _case_shift_ball_as_dim_change() -> None:
    refuse_shift_ball_as_dim_change(
        {
            "shift_ball_as_dim_change": True,
            "source": "shiftBallPosition",
            "walk_obs": 59,
        }
    )


def _case_kick_policy_as_default_walk() -> None:
    refuse_kick_policy_as_default_walk(
        {
            "kick_policy_as_default_walk": True,
            "empty_context": True,
            "skill": "kick",
        }
    )


def _case_max_acc_as_net_swap() -> None:
    refuse_max_acc_as_net_swap(
        {
            "max_acc_as_net_swap": True,
            "source": "maxAcceleration",
            "walk_obs": 365,
        }
    )


def _case_getnext_as_hot_swap_train() -> None:
    refuse_getnext_as_hot_swap_train(
        {
            "getnext_as_hot_swap_train": True,
            "source": "getNextTargetRequest",
            "train_graph": True,
        }
    )


def _case_speed_gear_as_net_swap() -> None:
    refuse_speed_gear_as_net_swap(
        {
            "speed_gear_as_net_swap": True,
            "source": "fastWalkSpeed",
            "walk_obs": 365,
        }
    )


def _case_ball_net_off_as_dim_change() -> None:
    refuse_ball_net_off_as_dim_change(
        {
            "ball_net_off_as_dim_change": True,
            "source": "ballNetworkParameters.active",
            "walk_obs": 59,
        }
    )


def _case_intercept_as_kick_default() -> None:
    refuse_intercept_as_kick_default(
        {
            "intercept_as_kick_default": True,
            "source": "shouldInterceptBall",
        }
    )


def _case_avoid_as_hot_swap_train() -> None:
    refuse_avoid_as_hot_swap_train(
        {
            "avoid_as_hot_swap_train": True,
            "source": "obstacleAvoidance",
            "train_graph": True,
        }
    )


def _case_should_stop_as_kick_default() -> None:
    refuse_should_stop_as_kick_default(
        {
            "should_stop_as_kick_default": True,
            "source": "shouldStop",
        }
    )


def _case_stand_as_dim_change() -> None:
    refuse_stand_as_dim_change(
        {
            "stand_as_dim_change": True,
            "source": "MotionPhase::stand",
            "walk_obs": 59,
        }
    )


def _case_ball_unseen_as_hot_swap_train() -> None:
    refuse_ball_unseen_as_hot_swap_train(
        {
            "ball_unseen_as_hot_swap_train": True,
            "source": "ballTimeWhenLastSeen",
            "train_graph": True,
        }
    )


def _case_empty_skill_as_kick() -> None:
    refuse_empty_skill_as_kick(
        {
            "empty_skill_as_kick": True,
            "empty_context": True,
            "skill": "kick",
        }
    )


CASES: tuple[tuple[str, CaseFn], ...] = (
    ("t1_as_walk", _case_t1_as_walk),
    ("huoshen_obs_as_walk", _case_huoshen_obs_as_walk),
    ("t1_on_walk_slot", _case_t1_on_walk_slot),
    ("standup_to_kick", _case_standup_to_kick),
    ("simrobot_as_fast_standup", _case_simrobot_as_fast),
    ("latent_into_344", _case_latent_into_344),
    ("draft_write_live", _case_draft_write_live),
    ("unified_pd_closed_fake_green", _case_unified_pd_closed),
    ("sibling_merge_into_344", _case_sibling_merge_into_344),
    ("t1_onnx_as_k1_walk", _case_t1_onnx_as_k1_walk),
    ("behavior_replaces_walk", _case_behavior_replaces_walk),
    ("teamcomm_into_344", _case_teamcomm_into_344),
    ("mix_128_512", _case_mix_128_512),
    ("fallen_as_skill_request", _case_fallen_as_skill_request),
    ("getup_incomplete_kick", _case_getup_incomplete_kick),
    ("stay_on_standup_after_getup", _case_stay_on_standup_after_getup),
    ("getup_done_direct_kick", _case_getup_done_direct_kick),
    ("kick_replaces_walk", _case_kick_replaces_walk),
    ("cfg_dim_rewrite", _case_cfg_dim_rewrite),
    ("kickmodel_t1", _case_kickmodel_t1),
    ("kick_onnx_on_walk_slot", _case_kick_onnx_on_walk_slot),
    ("getup_overwrites_walk", _case_getup_overwrites_walk),
    ("t1_getup_as_k1", _case_t1_getup_as_k1),
    ("fast_standup_as_isaac", _case_fast_standup_as_isaac),
    ("simulated_speed_as_pd_closed", _case_simulated_speed_as_pd_closed),
    ("fabricate_competition_getup", _case_fabricate_competition_getup),
    ("stand_ankle_as_pd_closed", _case_stand_ankle_as_pd_closed),
    ("competition_diff_net_slot", _case_competition_diff_net_slot),
    ("policy_switch_as_net_swap", _case_policy_switch_as_net_swap),
    ("shift_ball_as_dim_change", _case_shift_ball_as_dim_change),
    ("kick_policy_as_default_walk", _case_kick_policy_as_default_walk),
    ("max_acc_as_net_swap", _case_max_acc_as_net_swap),
    ("getnext_as_hot_swap_train", _case_getnext_as_hot_swap_train),
    ("speed_gear_as_net_swap", _case_speed_gear_as_net_swap),
    ("ball_net_off_as_dim_change", _case_ball_net_off_as_dim_change),
    ("intercept_as_kick_default", _case_intercept_as_kick_default),
    ("avoid_as_hot_swap_train", _case_avoid_as_hot_swap_train),
    ("should_stop_as_kick_default", _case_should_stop_as_kick_default),
    ("stand_as_dim_change", _case_stand_as_dim_change),
    ("ball_unseen_as_hot_swap_train", _case_ball_unseen_as_hot_swap_train),
    ("empty_skill_as_kick", _case_empty_skill_as_kick),
)


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"forbidden-regressions pack is read-only; must not write {path or 'K1.yaml'}"
    )


def run_case(name: str, fn: CaseFn) -> dict[str, Any]:
    try:
        fn()
    except (ValueError, RuntimeError, AssertionError):
        return {"id": name, "refused": True, "status": "PASS"}
    return {
        "id": name,
        "refused": False,
        "status": "FAIL",
        "error": f"{name} did not raise (gate must go red)",
    }


def run_pack() -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("forbidden-regressions leaked TRAINABLE/WRITE_YAML")
    results = [run_case(name, fn) for name, fn in CASES]
    failed = [row["id"] for row in results if not row.get("refused")]
    return {
        "ok": not failed,
        "failed": failed,
        "results": results,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "note": "any silent refuse is a gate-red failure",
    }


def assert_pack_frozen() -> dict[str, Any]:
    report = run_pack()
    if not report["ok"]:
        raise AssertionError(
            "forbidden regressions leaked: " + ", ".join(report["failed"])
        )
    return report
