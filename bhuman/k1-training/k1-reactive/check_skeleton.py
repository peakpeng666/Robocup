#!/usr/bin/env python3
"""Static checks for the K1_Reactive design skeleton (no GPU / Isaac Gym)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import (  # noqa: E402
    ACTION_LAYOUT,
    FORBIDDEN_ACTOR_WEIGHTS,
    HUOSHEN_T1_ACT,
    HUOSHEN_T1_OBS,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    NUM_PRIVILEGED_OBS,
    NUM_STACK,
    OBS_LAYOUT,
    TASK_NAME,
    TRAINABLE,
    WALK_ACT,
    WALK_OBS,
    assert_parallel_to_official_walk,
    layout_dims,
)
from env_stub import (  # noqa: E402
    ISAAC_GYM_TASK_REGISTERED,
    create_training_env,
    refuse_foreign_checkpoint,
)
from virtual_perception import DelayBuffer, ball_in_fov_placeholder, maybe_drop_detection  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

ISAAC_ENV_TREES = (
    "bhuman/MachineLearning/IsaacGymRL/envs",
    "bhuman/k1-training/src/IsaacGymRL/envs",
)


def _repo_from(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        raise SystemExit("PyYAML is required to check K1_Reactive.yaml")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a mapping")
    return data


def check(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo_from(repo)
    errors: list[str] = []
    notes: list[str] = []

    try:
        assert_parallel_to_official_walk()
    except AssertionError as exc:
        errors.append(str(exc))

    if layout_dims(OBS_LAYOUT) != 64 or NUM_OBSERVATIONS != 64:
        errors.append(f"obs layout {layout_dims(OBS_LAYOUT)} vs NUM_OBSERVATIONS={NUM_OBSERVATIONS}")
    if layout_dims(ACTION_LAYOUT) != 15 or NUM_ACTIONS != 15:
        errors.append("action layout is not 15")
    if TRAINABLE or ISAAC_GYM_TASK_REGISTERED:
        errors.append("skeleton marked trainable or registered")
    notes.append(
        f"baseline walk stays {WALK_OBS}→{WALK_ACT}; {TASK_NAME} is parallel {NUM_OBSERVATIONS}→{NUM_ACTIONS}"
    )
    if NUM_ACTIONS == HUOSHEN_T1_ACT and NUM_OBSERVATIONS == HUOSHEN_T1_OBS:
        errors.append("K1_Reactive must not copy the Huoshen T1 58→15 contract")
    notes.append(
        f"action count {NUM_ACTIONS} equals Huoshen T1 count but slots are head+legs+freq, not waist"
    )

    yaml_path = ROOT / "K1_Reactive.yaml"
    if not yaml_path.is_file():
        errors.append("missing K1_Reactive.yaml")
        cfg = {}
    else:
        cfg = _load_yaml(yaml_path)
        env = cfg.get("env") or {}
        meta = cfg.get("meta") or {}
        obs = cfg.get("observation") or {}
        if env.get("num_observations") != NUM_OBSERVATIONS or env.get("num_actions") != NUM_ACTIONS:
            errors.append(
                f"YAML env {env.get('num_observations')}→{env.get('num_actions')} "
                f"vs contract {NUM_OBSERVATIONS}→{NUM_ACTIONS}"
            )
        if env.get("num_stack") != NUM_STACK or env.get("num_privileged_obs") != NUM_PRIVILEGED_OBS:
            errors.append("YAML stack/priv dims drifted from contract.py")
        if env.get("trainable") is not False or meta.get("trainable") is not False:
            errors.append("YAML must keep trainable: false")
        if meta.get("registered_in_isaacgymrl") is not False:
            errors.append("YAML must keep registered_in_isaacgymrl: false")
        if env.get("num_envs") != 0:
            errors.append("YAML num_envs must stay 0 (no fake training fleet)")
        layout = obs.get("layout") or {}
        if isinstance(layout, dict) and sum(int(v) for v in layout.values()) != NUM_OBSERVATIONS:
            errors.append(f"YAML observation.layout sum {sum(layout.values())} != {NUM_OBSERVATIONS}")
        vp = cfg.get("virtual_perception") or {}
        if vp.get("delay_ms_mean") != 116 or vp.get("delay_steps_default") != 6:
            errors.append("virtual_perception delay fields drifted from 116 ms / 6 steps")

    for rel in ISAAC_ENV_TREES:
        tree = repo / rel
        init = tree / "__init__.py"
        leaked_yaml = tree / "K1_Reactive.yaml"
        leaked_py = tree / "k1_reactive.py"
        if init.is_file() and TASK_NAME in init.read_text(encoding="utf-8"):
            errors.append(f"{rel}/__init__.py must not import {TASK_NAME}")
        if leaked_yaml.is_file() or leaked_py.is_file():
            errors.append(f"{rel} must not contain a {TASK_NAME} task file (would be picked up by train.py)")
        else:
            notes.append(f"{rel}: official registry stays walk/kick/standup only")

    buf = DelayBuffer(delay_steps=6)
    for i in range(6):
        if buf.push(i) is not None:
            errors.append("DelayBuffer returned a value before 6 steps")
            break
    if buf.push(6) != 0 or buf.push(7) != 1:
        errors.append("DelayBuffer 6-step delay is wrong")
    else:
        notes.append("DelayBuffer: 6 steps ≈ 116 ms at 50 Hz")

    if ball_in_fov_placeholder((2.0, 0.0)) is not True:
        errors.append("FOV placeholder should accept a ball ahead")
    if ball_in_fov_placeholder((-1.0, 0.0)) is not False:
        errors.append("FOV placeholder should reject a ball behind")
    if maybe_drop_detection(True, 0.0) is not True:
        errors.append("dropout_prob=0 must keep a valid detection")

    try:
        refuse_foreign_checkpoint("K1_walk.pth")
    except ValueError:
        notes.append("refuse_foreign_checkpoint blocks official walk weights")
    else:
        errors.append("refuse_foreign_checkpoint accepted K1_walk.pth")
    try:
        refuse_foreign_checkpoint("model.pth")
    except ValueError:
        notes.append("refuse_foreign_checkpoint blocks Huoshen T1 model.pth")
    else:
        errors.append("refuse_foreign_checkpoint accepted Huoshen model.pth")
    try:
        create_training_env()
    except RuntimeError:
        notes.append("create_training_env() raises (stub is not a Gym task)")
    else:
        errors.append("create_training_env() must raise")

    for name in FORBIDDEN_ACTOR_WEIGHTS:
        if name in {"K1_walk.pth", "model.pth"}:
            continue

    return {
        "ok": not errors,
        "task": TASK_NAME,
        "contract": f"{NUM_OBSERVATIONS}→{NUM_ACTIONS}",
        "baseline": f"{WALK_OBS}→{WALK_ACT}",
        "trainable": TRAINABLE,
        "registered": ISAAC_GYM_TASK_REGISTERED,
        "errors": errors,
        "notes": notes,
    }


def main() -> int:
    report = check()
    print(f"[k1-reactive] {'PASS' if report['ok'] else 'FAIL'} {report['contract']} parallel to walk {report['baseline']}")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
