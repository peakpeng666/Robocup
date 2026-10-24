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
    """Walk overpass only. Kick 59 / reactive 64 / NUSim 79 are not walk."""
    if obs_dim == WALK_OBS and (act_dim in (None, WALK_ACT)):
        return
    if obs_dim == KICK_OBS:
        raise ValueError("kick 59->13 checkpoint is not a walk sim2sim policy")
    if obs_dim == 64:
        raise ValueError("reactive 64 is a parallel stub; not the walk overpass")
    if obs_dim == 79:
        raise ValueError("NUSim 79 is forbidden in sim2sim")
    raise ValueError(f"sim2sim walk gate expects 344->13, got {obs_dim}->{act_dim}")


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
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key in REQUIRED_RESULT_KEYS:
        if key not in data:
            errors.append(f"{path.name} missing {key}")
    shape = data.get("observations_shape") or []
    if not (isinstance(shape, list) and len(shape) == 2 and shape[1] == WALK_OBS):
        errors.append(f"{path.name} observations_shape {shape} is not (*, 344)")
    else:
        refuse_foreign_policy(int(shape[1]), WALK_ACT)
    identity = data.get("policy_identity") or {}
    if identity.get("critic_loaded") is True:
        errors.append("recorded run loaded critic; walk overpass must be actor-only")
    if data.get("robot_connected") is not False:
        errors.append("recorded sim2sim run must keep robot_connected=false")
    checks = data.get("checks") or {}
    for name in REQUIRED_CHECKS:
        if name not in checks:
            errors.append(f"{path.name} checks missing {name}")
    policy_calls = data.get("policy_calls")
    physics_steps = data.get("physics_steps")
    if policy_calls and physics_steps and physics_steps != policy_calls * 10:
        errors.append("physics_steps != policy_calls * 10 (dt 0.002, decimation 10)")
    return {"path": str(path), "ok": not errors, "errors": errors, "status": data.get("status")}


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
        refuse_foreign_policy(KICK_OBS, 13)
        errors.append("refuse_foreign_policy must reject kick 59")
    except ValueError:
        notes.append("kick 59 refused as a walk overpass policy")

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
