"""Highest-priority forbidden-claim pack (no Gym).

Each case MUST raise. If a refuse is silent, the gate goes red.
Cases: T1 as walk, standup→kick, SimRobot as fast standup, latent into 344,
draft overwrite live, unified PD as closed gap, sibling merge into 344,
T1 ONNX as K1 walk, BehaviorControl replacing walk, TeamComm into 344,
mix 128/512, fallen as SkillRequest Type, GetUp incomplete kick,
stay on standup after getup, kick replacing walk, cfg dim rewrite,
kickModel pointing at T1, kick ONNX occupying the walk slot.

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
