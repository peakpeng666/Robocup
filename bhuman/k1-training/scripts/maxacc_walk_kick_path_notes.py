"""Pin maxAcceleration notes on walk vs kick paths; forbid silent live copy.

Deepens max_acceleration_diff without replacing it:

  * Walk path: getTranslationPolygon uses commonSpeedParameters.maxAcceleration
  * Kick path: kickPolicy.apply does not read maxAcceleration
  * Default 20/20 · Simulated 60/20 · Competition 200/20; y stays 20
  * Silent copy of Sim/Comp maxAcc into Default live cfg FAIL

Does not import policy_switch_hysteresis_enter_exit.
Does not write K1.yaml / walkingEngine.cfg.

Runnable: python3 bhuman/k1-training/scripts/maxacc_walk_kick_path_notes.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from max_acceleration_diff import (  # noqa: E402
    ALLOWED_COMP_MAX_ACC_DIFFS,
    ALLOWED_SIM_MAX_ACC_DIFFS,
    COMP_MAX_ACC,
    DEFAULT_MAX_ACC,
    SIM_MAX_ACC,
    assert_max_acc_frozen,
    refuse_max_acc_allowlist_drift,
    refuse_max_acc_as_net_swap,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
)
SIM_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
WALK_CPP_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)
SNAPSHOT_REL = "bhuman/k1-training/manifests/maxacc-walk-kick-path-notes-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
DEFAULT_WALK_SHA256 = "c6fc603b80ee4347a17739ff592d1d9825b04da3987214b309450b9f1feb4611"
COMPETITION_WALK_SHA256 = "a0a8af819ada04442de3dfb73dba5895bdd7c7ff577a13624f55ccddbf19f10e"
WALK_PATH_NEEDLE = "const Vector2f maxStepSizeChange = commonSpeedParameters.maxAcceleration"
KICK_APPLY_NEEDLE = "engine.walkPolicy.apply()"
KICK_POLICY_NEEDLE = "CompiledNN& policy = !isOldKick ? engine.kickPolicy"

CHECKLIST = (
    "walk_path_uses_maxacc",
    "kick_path_does_not_read_maxacc",
    "plant_values_frozen",
    "hashes_frozen",
    "silent_copy_refused",
)
DOC_NEEDLES = (
    "maxacc_walk_kick_path_notes",
    "walk vs kick",
    "TRAINABLE=false",
    "gap_closed=false",
    "silent maxAcc",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "field_ready=true",
    "competition_ready=true",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"maxAcc walk/kick path notes are read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"maxAcc walk/kick path notes are read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_silent_maxacc_copy_into_live_cfg(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-maxacc-copy-into-live-cfg claim must be a mapping")
    if (
        claim.get("silent_maxacc_copy_into_live_cfg")
        or claim.get("copy_maxacc_to_default")
        or claim.get("write_cfg") is True
        or claim.get("apply_to_live") is True
        or claim.get("hash_drift_ok")
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("copied") or claim.get("silent_copy") or claim.get("edited"))
        )
    ):
        raise ValueError(
            "Default walkingEngine.cfg maxAcceleration is hash-pinned; "
            "silent copy of Simulated 60 or Competition 200 into live cfg is forbidden"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("maxAcc walk/kick path notes leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    frozen = assert_max_acc_frozen(repo)
    if frozen.get("status") == "SKIP":
        raise AssertionError("maxAcc path notes must not SKIP when cfgs exist")
    plant = frozen.get("max_acceleration") or {}
    if (
        (plant.get("default") or {}) != DEFAULT_MAX_ACC
        or (plant.get("simulated") or {}) != SIM_MAX_ACC
        or (plant.get("competition") or {}) != COMP_MAX_ACC
    ):
        raise AssertionError(f"maxAcceleration plant drifted: {plant}")
    if frozen.get("allowed_sim_count") != len(ALLOWED_SIM_MAX_ACC_DIFFS):
        raise AssertionError("Simulated maxAcc allowlist count drifted off sibling pin")
    if frozen.get("allowed_comp_count") != len(ALLOWED_COMP_MAX_ACC_DIFFS):
        raise AssertionError("Competition maxAcc allowlist count drifted off sibling pin")

    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    default_sha = hashlib.sha256(default_path.read_bytes()).hexdigest()
    comp_sha = hashlib.sha256(comp_path.read_bytes()).hexdigest()
    if default_sha != DEFAULT_WALK_SHA256:
        raise AssertionError("Default walkingEngine.cfg hash drifted (silent maxAcc copy?)")
    if comp_sha != COMPETITION_WALK_SHA256:
        raise AssertionError("Competition walkingEngine.cfg hash drifted")

    cpp_path = repo / WALK_CPP_REL
    if not cpp_path.is_file():
        raise AssertionError("WalkingEngine.cpp missing")
    cpp_text = cpp_path.read_text(encoding="utf-8", errors="replace")
    if WALK_PATH_NEEDLE not in cpp_text:
        raise AssertionError("walk path missing maxStepSizeChange = maxAcceleration")
    if KICK_APPLY_NEEDLE not in cpp_text or KICK_POLICY_NEEDLE not in cpp_text:
        raise AssertionError("kick path apply site missing")
    kick_idx = cpp_text.find(KICK_POLICY_NEEDLE)
    if kick_idx < 0:
        raise AssertionError("kickPolicy apply site missing")
    kick_window = cpp_text[kick_idx : kick_idx + 1800]
    if "maxAcceleration" in kick_window or "maxStepSizeChange" in kick_window:
        raise AssertionError("kickPolicy path must not read maxAcceleration")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/maxacc_walk_kick_path_notes.py",
        "checklist": list(CHECKLIST),
        "walk_path": {
            "uses_maxacc": True,
            "site": "WalkPhase getTranslationPolygon maxStepSizeChange",
            "default": dict(DEFAULT_MAX_ACC),
            "simulated": dict(SIM_MAX_ACC),
            "competition": dict(COMP_MAX_ACC),
        },
        "kick_path": {
            "uses_maxacc": False,
            "site": "kickPolicy.apply compiled bypass",
        },
        "silent_maxacc_copy_into_live_cfg": False,
        "walk": "344→13",
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "field_ready": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "maxAcceleration ratchets walk step size only; "
            "kickPolicy does not read it; "
            "silent copy of Sim/Comp values into Default live cfg forbidden"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "default_sha256": default_sha,
        "competition_sha256": comp_sha,
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_maxacc_walk_kick_path_notes_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("maxAcc walk/kick path notes leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"maxAcc path-notes checklist drifted: {snap.get('checklist')}")
    walk = snap.get("walk_path") or {}
    kick = snap.get("kick_path") or {}
    if not walk.get("uses_maxacc") or kick.get("uses_maxacc"):
        raise AssertionError("walk/kick maxAcc path notes drifted")
    if snap.get("silent_maxacc_copy_into_live_cfg") or snap.get("apply_to_live"):
        raise AssertionError("silent maxAcc copy / apply_to_live leaked")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("maxAcc path notes leaked ready_gpu / would_train / GAP-closed")
    if snap.get("default_sha256") != DEFAULT_WALK_SHA256:
        raise AssertionError("Default hash pin drifted")
    try:
        refuse_silent_maxacc_copy_into_live_cfg(
            {
                "silent_maxacc_copy_into_live_cfg": True,
                "copy_maxacc_to_default": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_silent_maxacc_copy_into_live_cfg must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("maxAcc walk/kick path notes imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    comp_path = repo / COMP_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    try:
        snap = assert_maxacc_walk_kick_path_notes_frozen(repo)
        notes.append("assert_maxacc_walk_kick_path_notes_frozen: walk uses / kick does not")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("walk path ratchets maxAcc; kickPolicy.apply does not read it")
        notes.append("Default 20/20 vs Simulated 60/20 vs Competition 200/20; y stays 20")
        notes.append("silent maxAcc copy into live cfg forbidden")

    try:
        refuse_silent_maxacc_copy_into_live_cfg(
            {"status": "PASS", "copied": True, "this_pin": True}
        )
        errors.append("silent_maxacc_copy_into_live_cfg must raise")
    except ValueError:
        notes.append("negative: silent maxAcc copy into live cfg refused")
    try:
        refuse_max_acc_as_net_swap(
            {"max_acc_as_net_swap": True, "source": "maxAcceleration", "walk_obs": 365}
        )
        errors.append("refuse_max_acc_as_net_swap must raise")
    except ValueError:
        notes.append("negative: maxAcc as net swap refused")
    try:
        refuse_max_acc_allowlist_drift(
            {
                "max_acc_allowlist_drift": True,
                "source": "SimulatedK1",
                "pair": COMP_MAX_ACC,
            }
        )
        errors.append("refuse_max_acc_allowlist_drift must raise")
    except ValueError:
        notes.append("negative: maxAcc allowlist drift refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of Default walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (default_path, before_default, "Default walkingEngine.cfg"),
        (sim_path, before_sim, "SimulatedK1 walkingEngine.cfg"),
        (comp_path, before_comp, "CompetitionWalk walkingEngine.cfg"),
    ):
        if path.is_file() and before:
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during maxAcc path notes")
            else:
                notes.append(f"official {label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "silent_maxacc_copy_into_live_cfg": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[maxacc-path-notes] FAIL {exc}")
        return 1
    print(
        f"[maxacc-path-notes] {snap.get('status')} "
        f"walk uses maxAcc; kick does not; silent copy forbidden; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
