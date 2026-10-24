"""Documented attach points for P1 estimators (not wired).

Estimator output is a side-channel (critic / logs later). It must not
enter official walk 344, SwitcherSM, DeployCall, or K1.yaml.

See README.md and bhuman/docs/MIGRATE-TO-K1.md.
"""
from __future__ import annotations

from interface import TRAINABLE, WALK_OBS

HOOKS = {
    "actor": "actor_observation copies official walk 344; never rewrite",
    "latent": "encode_latent is zeros; critic/logs only; never concat onto 344",
    "switcher": "not wired: SwitcherSM.request does not call encode_latent",
    "deploy_call": "not wired: DeployCall.tick does not select an estimator",
    "k1_yaml": "attach_to_k1_yaml raises; official rewards/dims stay",
    "teammate_state": "forbidden: TeamComm must not be written into 344",
}


def documented_hooks() -> dict[str, str]:
    if TRAINABLE:
        raise RuntimeError("estimator hooks leaked TRAINABLE=true")
    return dict(HOOKS)


def refuse_concat_latent_onto_walk(flat_344, latent) -> None:
    values = list(flat_344)
    extra = list(latent)
    if len(values) != WALK_OBS:
        raise ValueError(f"walk obs dim {len(values)} != {WALK_OBS}")
    raise RuntimeError(
        f"refuse concat {len(values)}+{len(extra)}: latent must not enter official 344"
    )


def refuse_inject_teammate_state(*_args, **_kwargs) -> None:
    raise RuntimeError("teammate / CTDE state must not be written into walk 344")


def refuse_wire_into_switcher(*_args, **_kwargs) -> None:
    raise RuntimeError(
        "estimators are not on SwitcherSM; official actor stays 344→13"
    )


def refuse_wire_into_deploy_call(*_args, **_kwargs) -> None:
    raise RuntimeError(
        "estimators are not on DeployCall.tick; default skill stays official walk"
    )


def assert_hooks_unwired() -> None:
    hooks = documented_hooks()
    for key in ("switcher", "deploy_call"):
        if "not wired" not in hooks[key]:
            raise AssertionError(f"{key} hook must stay unwired")
    try:
        refuse_concat_latent_onto_walk([0.0] * WALK_OBS, [0.0] * 8)
    except RuntimeError:
        return
    raise AssertionError("concat latent onto 344 must raise")
