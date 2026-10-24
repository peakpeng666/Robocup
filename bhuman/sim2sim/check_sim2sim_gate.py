#!/usr/bin/env python3
"""GPU-free sim2sim gate skeleton.

Checks that the MuJoCo walk overpass still targets official 344->13.
Does not source env.sh (that file requires the operator bh-gym interpreter).
Does not start Isaac Sim, does not connect a robot, does not train.

Missing mujoco / weights / isaacsim-gui python => SKIP + warn, exit 0.
Set SIM2SIM_GATE_RUN=1 only on an operator machine that already has the
stack; this skeleton still will not auto-invoke run-mujoco.sh.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
RECORDED_RUN = "runs/20261020_220814_312153_mujoco_walk"
# Official Isaac / MuJoCo train PD (K1.yaml live block). Robot ankle-roll p25
# is a documented domain gap — must not overwrite this declaration.
TRAIN_ANKLE_PITCH_P = 50.0
TRAIN_ANKLE_ROLL_P = 60.0
ROBOT_ANKLE_ROLL_P = 25.0
FOREIGN_OVERPASS = (
    (59, 13, "kick 59→13"),
    (64, 15, "reactive 64→15"),
    (58, 15, "Huoshen T1 58→15"),
    (73, 22, "standup 73→22"),
    (72, 22, "fast standup 72→22"),
    (79, 22, "NUSim 79→22"),
    (365, 14, "B-Human T1 walk 365→14"),
    (344, 15, "walk obs + reactive act"),
    (344, 22, "walk obs + standup act"),
    (64, 13, "reactive obs + walk act"),
)
REQUIRED_RESULT_KEYS = (
    "status",
    "observations_shape",
    "policy_identity",
    "robot_connected",
    "physics_steps",
    "policy_calls",
)
REQUIRED_CHECKS = (
    "no_fall",
    "all_states_and_actions_finite",
    "source_model_and_config_unchanged",
    "final_stop_bounded",
)


def _repo_from(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parent.parent, ROOT.parents[1], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_foreign_policy(obs_dim: int, act_dim: int | None = None) -> None:
    """Walk overpass only. Wrong dims / foreign families are not walk."""
    if obs_dim == WALK_OBS and (act_dim in (None, WALK_ACT)):
        return
    labels = {
        (59, 13): "kick 59->13 checkpoint is not a walk sim2sim policy",
        (64, 15): "reactive 64 is a parallel stub; not the walk overpass",
        (64, 13): "reactive 64 + walk 13 is not a legal overpass pair",
        (58, 15): "Huoshen T1 58->15 is not K1 walk",
        (73, 22): "standup 73->22 is GetUpEngine, not the walk overpass",
        (72, 22): "fast standup 72->22 is deploy-only; SimRobot/MuJoCo must not impersonate it",
        (79, 22): "NUSim 79 is forbidden in sim2sim",
        (365, 14): "B-Human T1 walk 365->14 is not K1",
        (344, 15): "walk 344 obs cannot pair with a 15-D reactive action",
        (344, 22): "walk 344 obs cannot pair with a 22-D standup action",
    }
    raise ValueError(
        labels.get((obs_dim, act_dim), f"sim2sim walk gate expects 344->13, got {obs_dim}->{act_dim}")
    )


def refuse_pd_claim(claim: dict) -> None:
    """Refuse unified / robot-p25-as-train / foreign-family PD declarations."""
    if not isinstance(claim, dict):
        raise ValueError("PD claim must be a mapping")
    if claim.get("unified") is True:
        raise ValueError("must not unify Isaac / MuJoCo / SimRobot / robot PD groups")
    source = str(claim.get("source") or "")
    family = str(claim.get("family") or "")
    ankle_roll = claim.get("Ankle_Roll")
    if family in {"huoshen_t1", "nusim", "t1_reactive", "K1_Reactive"}:
        raise ValueError(f"foreign PD family {family} is forbidden on the walk overpass")
    if source in {"train_yaml", "isaac", "k1.yaml", "official_walk"} and ankle_roll is not None:
        value = float(ankle_roll)
        if value == ROBOT_ANKLE_ROLL_P:
            raise ValueError("must not rewrite official train Ankle_Roll p60 to robot p25")
        if value != TRAIN_ANKLE_ROLL_P:
            raise ValueError(f"official train Ankle_Roll must stay p{TRAIN_ANKLE_ROLL_P:g}, got {ankle_roll}")


def official_train_pd_untouched(repo: Path) -> None:
    """Read-only: live K1.yaml PD stays ankle-roll p60, not robot p25."""
    for rel in (
        "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
        "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
    ):
        text = (repo / rel).read_text(encoding="utf-8")
        if '"Ankle_Roll": 60.' not in text:
            raise AssertionError(f"{rel} live Ankle_Roll is no longer official train p60")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError(f"{rel} is no longer official walk 344→13")


def probe_stack() -> dict[str, Any]:
    modules = {}
    for name in ("mujoco", "torch", "onnxruntime"):
        try:
            __import__(name)
            modules[name] = True
        except Exception:
            modules[name] = False
    isaacsim_py = Path.home() / ".venvs/isaacsim-gui/bin/python"
    walk_pth = ROOT.parent / "k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"
    walk_onnx = ROOT.parent / "BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx"
    ready = bool(
        modules.get("mujoco")
        and isaacsim_py.exists()
        and (walk_pth.is_file() or walk_onnx.is_file())
    )
    skip_reasons = []
    if not modules.get("mujoco"):
        skip_reasons.append("python module mujoco missing")
    if not isaacsim_py.exists():
        skip_reasons.append("isaacsim-gui python missing")
    if not walk_pth.is_file() and not walk_onnx.is_file():
        skip_reasons.append("official K1_walk.pth / K1_walk.onnx absent (gitignored)")
    return {
        "modules": modules,
        "isaacsim_gui_python_exists": isaacsim_py.exists(),
        "walk_pth_exists": walk_pth.is_file(),
        "walk_onnx_exists": walk_onnx.is_file(),
        "ready": ready,
        "skip_reasons": skip_reasons,
        "auto_run_requested": os.environ.get("SIM2SIM_GATE_RUN") == "1",
    }


def check_recorded_result(path: Path) -> dict[str, Any]:
    """Validate recorded PASS evidence, not just the presence of its fields.

    Live-stack SKIP handling belongs to run(). A recorded SKIP/FAIL is never
    successful acceptance evidence, and its original status is preserved.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"path": str(path), "ok": False, "errors": [f"{path.name} unreadable result: {exc}"], "status": None}
    if not isinstance(data, dict):
        return {"path": str(path), "ok": False, "errors": [f"{path.name} result must be an object"], "status": None}
    errors: list[str] = []
    for key in REQUIRED_RESULT_KEYS:
        if key not in data:
            errors.append(f"{path.name} missing {key}")
    if data.get("status") != "PASS":
        errors.append(f"{path.name} status must be PASS, got {data.get('status')!r}")
    shape = data.get("observations_shape") or []
    shape_ok = (
        isinstance(shape, list)
        and len(shape) == 2
        and type(shape[0]) is int
        and shape[0] > 0
        and type(shape[1]) is int
        and shape[1] == WALK_OBS
    )
    if not shape_ok:
        errors.append(f"{path.name} observations_shape {shape} is not (positive count, 344)")
    else:
        refuse_foreign_policy(int(shape[1]), WALK_ACT)
    identity = data.get("policy_identity")
    if not isinstance(identity, dict) or identity.get("critic_loaded") is not False:
        errors.append("recorded run must explicitly declare critic_loaded=false; walk overpass is actor-only")
    if data.get("robot_connected") is not False:
        errors.append("recorded sim2sim run must keep robot_connected=false")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        errors.append(f"{path.name} checks must be an object")
        checks = {}
    for name in REQUIRED_CHECKS:
        if checks.get(name) is not True:
            errors.append(f"{path.name} checks.{name} must be true")
    policy_calls = data.get("policy_calls")
    physics_steps = data.get("physics_steps")
    # JSON booleans, floats (including NaN/Infinity), and strings are not counts.
    counts_ok = True
    for name, value in (("policy_calls", policy_calls), ("physics_steps", physics_steps)):
        if type(value) is not int or value <= 0:
            errors.append(f"{path.name} {name} must be a positive integer")
            counts_ok = False
    if counts_ok and physics_steps != policy_calls * 10:
        errors.append("physics_steps != policy_calls * 10 (dt 0.002, decimation 10)")
    if counts_ok and shape_ok and shape[0] != policy_calls:
        errors.append("observations_shape[0] != policy_calls")
    launch = path.with_name("launch.json")
    if launch.is_file():
        errors.extend(_check_recorded_pd(launch))
    return {"path": str(path), "ok": not errors, "errors": errors, "status": data.get("status")}


def _check_recorded_pd(launch: Path) -> list[str]:
    data = json.loads(launch.read_text(encoding="utf-8"))
    stiffness = data.get("pd_stiffness") or []
    errors: list[str] = []
    # mujoco_walk.py: first 10 DoF are upper body (Default 10), then 12 legs.
    # Leg order: HipPitch, HipRoll, HipYaw, Knee, AnklePitch, AnkleRoll ×2.
    if len(stiffness) < 22:
        return [f"{launch.name} pd_stiffness too short to score ankle roll"]
    left_roll, right_roll = float(stiffness[15]), float(stiffness[21])
    left_pitch, right_pitch = float(stiffness[14]), float(stiffness[20])
    if left_roll != TRAIN_ANKLE_ROLL_P or right_roll != TRAIN_ANKLE_ROLL_P:
        errors.append(
            f"{launch.name} Ankle_Roll PD {left_roll}/{right_roll} is not official train p60"
        )
    if left_roll == ROBOT_ANKLE_ROLL_P or right_roll == ROBOT_ANKLE_ROLL_P:
        errors.append(f"{launch.name} Ankle_Roll was rewritten to robot p25")
    if left_pitch != TRAIN_ANKLE_PITCH_P or right_pitch != TRAIN_ANKLE_PITCH_P:
        errors.append(
            f"{launch.name} Ankle_Pitch PD {left_pitch}/{right_pitch} is not official train p50"
        )
    return errors


def check_scripts_present(repo: Path) -> list[str]:
    errors = []
    for rel in (
        "bhuman/sim2sim/README.md",
        "bhuman/sim2sim/run-mujoco.sh",
        "bhuman/sim2sim/verify-policy.sh",
        "bhuman/sim2sim/verify_policy.py",
        "bhuman/sim2sim/mujoco_walk.py",
        "bhuman/sim2sim/run-sim2sim-gate.sh",
    ):
        if not (repo / rel).is_file():
            errors.append(f"missing {rel}")
    return errors


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo_from()
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    errors.extend(check_scripts_present(repo))
    readme = repo / "bhuman/sim2sim/README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if "344→13" not in text and "344->13" not in text:
            errors.append("sim2sim/README.md must keep the official walk 344→13 contract visible")
        else:
            notes.append("sim2sim README still names walk 344→13")

    recorded = repo / "bhuman/sim2sim" / RECORDED_RUN / "result.json"
    recorded_report = None
    if recorded.is_file():
        recorded_report = check_recorded_result(recorded)
        errors.extend(recorded_report.get("errors") or [])
        if recorded_report.get("ok"):
            notes.append(f"recorded {RECORDED_RUN} stays (*,344) actor-only, robot_connected=false")
    else:
        warnings.append(f"recorded result missing: {RECORDED_RUN}/result.json")

    try:
        official_train_pd_untouched(repo)
        notes.append("official K1.yaml live PD still Ankle_Roll p60 (not robot p25)")
    except AssertionError as exc:
        errors.append(str(exc))

    for obs_dim, act_dim, label in FOREIGN_OVERPASS:
        try:
            refuse_foreign_policy(obs_dim, act_dim)
            errors.append(f"refuse_foreign_policy must reject {label}")
        except ValueError:
            notes.append(f"negative dim: {label} refused as a walk overpass")

    for claim, label in (
        ({"unified": True, "source": "train_yaml", "Ankle_Roll": 60.0}, "unified PD groups"),
        ({"source": "train_yaml", "Ankle_Roll": ROBOT_ANKLE_ROLL_P}, "train YAML rewritten to p25"),
        ({"source": "official_walk", "Ankle_Roll": 80.0}, "train Ankle_Roll drifted off p60"),
        ({"family": "huoshen_t1", "Ankle_Roll": 60.0}, "Huoshen T1 PD family"),
        ({"family": "nusim"}, "NUSim PD family"),
    ):
        try:
            refuse_pd_claim(claim)
            errors.append(f"refuse_pd_claim must reject {label}")
        except ValueError:
            notes.append(f"negative PD: {label} refused")
    try:
        refuse_pd_claim({"source": "official_walk", "Ankle_Roll": TRAIN_ANKLE_ROLL_P, "unified": False})
        notes.append("official train PD declaration Ankle_Roll p60 accepted")
    except ValueError as exc:
        errors.append(f"official train PD p60 must be accepted: {exc}")

    probe = probe_stack()
    skipped = not probe["ready"]
    if skipped:
        for reason in probe["skip_reasons"]:
            warnings.append(f"sim2sim stack: {reason}")
        warnings.append("sim2sim live replay skipped (no mujoco/weights); skeleton only")
        notes.append("live run-mujoco.sh not invoked")
    else:
        notes.append("stack looks present; skeleton still will not auto-run")
        if probe["auto_run_requested"]:
            notes.append(
                "SIM2SIM_GATE_RUN=1 is set, but this skeleton does not spawn "
                "run-mujoco.sh (operator must run it explicitly)"
            )
        else:
            notes.append("SIM2SIM_GATE_RUN unset; skip live replay even if stack exists")

    return {
        "ok": not errors,
        "skipped": skipped,
        "implemented": False,
        "walk_contract": f"{WALK_OBS}->{WALK_ACT}",
        "probe": probe,
        "recorded": recorded_report,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "operator_replay": "bash bhuman/sim2sim/run-mujoco.sh --seconds 120",
    }


def main() -> int:
    report = run()
    status = "PASS" if report["ok"] else "FAIL"
    skip = " SKIP" if report.get("skipped") else ""
    print(f"[sim2sim-gate] {status}{skip} walk {report['walk_contract']} implemented=false")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["warnings"]:
        print(f"[warn] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

