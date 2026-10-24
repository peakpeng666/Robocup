#!/usr/bin/env python3
"""Unit tests: estimator extras stay off official walk 344 (no Gym)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SWITCHER = ROOT.parent / "k1-switcher"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SWITCHER) not in sys.path:
    sys.path.insert(0, str(SWITCHER))

from hooks import (  # noqa: E402
    assert_hooks_unwired,
    documented_hooks,
    refuse_concat_latent_onto_walk,
    refuse_inject_teammate_state,
    refuse_wire_into_deploy_call,
    refuse_wire_into_switcher,
)
from interface import (  # noqa: E402
    TRAINABLE,
    WALK_OBS,
    official_walk_yaml_untouched,
    select_estimator,
)
from passthrough import PassthroughEstimator  # noqa: E402,F401
from rma_stub import RMAEstimator  # noqa: E402,F401
from dreamwaq_stub import DreamWaQEstimator  # noqa: E402,F401


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    errors: list[str] = []
    notes: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("estimator bypass test imported Gym")

    if TRAINABLE:
        errors.append("k1-estimators TRAINABLE must stay false")

    try:
        assert_hooks_unwired()
        notes.append("hooks unwired: switcher / deploy_call do not eat latent")
    except AssertionError as exc:
        errors.append(str(exc))

    hooks = documented_hooks()
    if "344" not in hooks["actor"] or "never concat" not in hooks["latent"]:
        errors.append("hook comments lost the 344 / no-concat rule")
    else:
        notes.append("interface comment: latent is side-channel, not official 344")

    sample = [float(i) * 0.01 for i in range(WALK_OBS)]
    rma = select_estimator("rma")
    actor = rma.actor_observation(sample)
    latent = rma.encode_latent(sample)
    if len(actor) != WALK_OBS:
        errors.append("RMA actor left official 344")
    if len(actor) + len(latent) == WALK_OBS:
        errors.append("latent was folded into the actor vector")
    if actor != sample:
        errors.append("RMA mutated the official walk observation")
    if any(abs(x) > 0.0 for x in latent):
        errors.append("RMA stub must not invent a nonzero encoder (fake-green)")
    else:
        notes.append("RMA: actor 344 copy; latent zeros stay off the vector")

    try:
        refuse_concat_latent_onto_walk(actor, latent)
        errors.append("concat latent onto 344 must raise")
    except RuntimeError:
        notes.append("concat 344+latent refused")

    try:
        refuse_inject_teammate_state({"mate_x": 1.0})
        errors.append("teammate inject must raise")
    except RuntimeError:
        notes.append("teammate/CTDE state refused from 344")

    try:
        refuse_wire_into_switcher()
        errors.append("switcher wire must raise")
    except RuntimeError:
        notes.append("switcher attach point documented, not wired")

    try:
        refuse_wire_into_deploy_call()
        errors.append("deploy_call wire must raise")
    except RuntimeError:
        notes.append("deploy_call attach point documented, not wired")

    if not official_walk_yaml_untouched(repo):
        errors.append("official K1.yaml drifted off 344/13")
    else:
        notes.append("official K1.yaml still 344→13 (estimators did not edit it)")

    # DeployCall must still default to official walk without selecting an estimator.
    from deploy_call import DeployCall, TRAINABLE as DEPLOY_TRAINABLE  # noqa: E402

    if DEPLOY_TRAINABLE:
        errors.append("DeployCall TRAINABLE leaked")
    call = DeployCall()
    tick = call.tick()
    if not tick.is_official_walk():
        errors.append("DeployCall default left official walk after estimator import")
    else:
        notes.append("DeployCall still defaults to official walk 344→13")

    readme = ROOT / "README.md"
    if not readme.is_file() or "不进" not in readme.read_text(encoding="utf-8"):
        # Allow either the Chinese 不进 or the English "must not enter".
        text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
        if "不得改" not in text and "must not" not in text and "不进" not in text:
            errors.append("estimator README must say extras stay off official 344")
        else:
            notes.append("estimator README keep-off-344 wording present")
    else:
        notes.append("estimator README: extras 不进 official 344")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[estimator-bypass] {'PASS' if report['ok'] else 'FAIL'} "
        "latent off 344; hooks unwired"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
