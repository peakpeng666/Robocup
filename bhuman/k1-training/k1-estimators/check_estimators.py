#!/usr/bin/env python3
"""Static checks for the P1 estimator bypass stubs (no GPU / Isaac Gym)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dreamwaq_stub import DreamWaQEstimator  # noqa: E402,F401
from interface import (  # noqa: E402
    ESTIMATOR_LATENT,
    REGISTRY_NAMES,
    TRAINABLE,
    WALK_ACT,
    WALK_OBS,
    official_walk_yaml_untouched,
    select_estimator,
    split_walk_obs,
)
from passthrough import PassthroughEstimator  # noqa: E402,F401
from rma_stub import RMAEstimator  # noqa: E402,F401


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _sample_walk_obs() -> list[float]:
    return [float(i % 17) * 0.01 for i in range(WALK_OBS)]


def check(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    errors: list[str] = []
    notes: list[str] = []
    sample = _sample_walk_obs()

    if TRAINABLE:
        errors.append("k1-estimators must stay TRAINABLE=false")
    if WALK_OBS != 344 or WALK_ACT != 13:
        errors.append("estimator module drifted off walk 344->13")

    if not official_walk_yaml_untouched(repo):
        errors.append("official K1.yaml is no longer 344/13 (estimators must not edit it)")
    else:
        notes.append("official K1.yaml still 344->13 (read-only check)")

    for name in REGISTRY_NAMES:
        try:
            est = select_estimator(name)
        except Exception as exc:
            errors.append(f"select_estimator({name!r}): {exc}")
            continue
        if est.family != name:
            errors.append(f"{name} family {est.family!r} mismatch")
        if est.trainable or est.actor_obs_dim != WALK_OBS:
            errors.append(f"{name} broke TRAINABLE=false / actor 344")
        try:
            actor = est.actor_observation(sample)
        except Exception as exc:
            errors.append(f"{name}.actor_observation: {exc}")
            continue
        if actor != sample:
            errors.append(f"{name} mutated or reordered the 344 actor vector")
        else:
            notes.append(f"{name}: actor observation is a 344-D copy")
        latent = est.encode_latent(sample)
        expect_latent = 0 if name == "passthrough" else ESTIMATOR_LATENT
        if len(latent) != expect_latent:
            errors.append(f"{name} latent dim {len(latent)} != {expect_latent}")
        if any(abs(x) > 0.0 for x in latent):
            errors.append(f"{name} stub must return zeros (no fake encoder)")
        try:
            est.rewrite_walk_obs(sample)
            errors.append(f"{name}.rewrite_walk_obs must raise")
        except RuntimeError:
            notes.append(f"{name}: rewrite_walk_obs refused")
        try:
            est.attach_to_k1_yaml()
            errors.append(f"{name}.attach_to_k1_yaml must raise")
        except RuntimeError:
            notes.append(f"{name}: attach_to_k1_yaml refused")
        try:
            est.create_training_env()
            errors.append(f"{name}.create_training_env must raise")
        except RuntimeError:
            notes.append(f"{name}: create_training_env refused")

    try:
        split_walk_obs([0.0] * 59)
        errors.append("59-D kick vector must not be accepted as walk history")
    except ValueError:
        notes.append("kick 59 rejected as walk estimator input")
    try:
        split_walk_obs([0.0] * 64)
        errors.append("reactive 64 must not be accepted as walk 344")
    except ValueError:
        notes.append("reactive 64 rejected as walk estimator input")
    try:
        split_walk_obs([0.0] * 79)
        errors.append("NUSim 79 must not be accepted")
    except ValueError:
        notes.append("NUSim 79 rejected")

    try:
        select_estimator("huoshen_t1")
        errors.append("huoshen_t1 must not be an estimator family")
    except KeyError:
        notes.append("no huoshen_t1 estimator family")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "families": list(REGISTRY_NAMES),
        "actor_obs": WALK_OBS,
        "actor_act": WALK_ACT,
        "trainable": TRAINABLE,
    }


def main() -> int:
    report = check()
    print(
        f"[k1-estimators] {'PASS' if report['ok'] else 'FAIL'} "
        f"families={report['families']} actor={report['actor_obs']}->{report['actor_act']} "
        f"TRAINABLE={report['trainable']}"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
