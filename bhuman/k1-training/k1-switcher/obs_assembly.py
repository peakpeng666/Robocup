"""Read-only walk observation assembly: 10×32+24=344.

Checks official YAML / t1.py / WalkingEngine needles.
Does not fabricate C++ fields. Deploy default stays official walk,
not reactive concat. TRAINABLE=false. Never writes YAML.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
WALK_FRAMES = 10
WALK_FRAME_DIM = 32
WALK_TAIL_DIM = 24

FRAME_LAYOUT = (
    ("projected_gravity", 3),
    ("base_ang_vel", 3),
    ("leg_pos", 12),
    ("executed_leg_action", 12),
    ("ball_xy_placeholder", 2),
)
TAIL_LAYOUT = (
    ("command_vx_vy_wyaw", 3),
    ("gait_cos_sin", 2),
    ("leg_vel", 12),
    ("raw_frequency", 1),
    ("ball_flag_placeholder", 3),
    ("direction_sin_cos", 2),
    ("range_placeholder", 1),
)

K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
T1_PY_REL = "bhuman/k1-training/src/IsaacGymRL/envs/t1.py"
WALKING_ENGINE_H_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h"
)
WALKING_ENGINE_CPP_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)
DOC_REL = "bhuman/docs/OBS-ASSEMBLY-344.md"


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def formula() -> str:
    return f"{WALK_FRAMES}×{WALK_FRAME_DIM}+{WALK_TAIL_DIM}={WALK_OBS}"


def layout_sum(layout: tuple[tuple[str, int], ...]) -> int:
    return sum(dim for _name, dim in layout)


def refuse_reactive_concat_as_walk(claim: dict[str, Any]) -> None:
    """Deploy default is official walk, not reactive concat onto 344."""
    if not isinstance(claim, dict):
        raise ValueError("assembly claim must be a mapping")
    if claim.get("via_reactive") or claim.get("concat_reactive"):
        raise ValueError("deploy walk 344 must not go through reactive concat")
    obs = claim.get("obs") or claim.get("flat")
    if obs in {64, 64 * 50, 3200, 345, 343, 59, 73, 72}:
        raise ValueError(f"{obs} must not impersonate walk assembly 344")
    if claim.get("latent_into_344") or claim.get("teammate_into_344"):
        raise ValueError("latent / teammate state must not enter walk 344")


def validate_assembly_shapes() -> dict[str, Any]:
    if layout_sum(FRAME_LAYOUT) != WALK_FRAME_DIM:
        raise AssertionError("frame layout drifted off 32")
    if layout_sum(TAIL_LAYOUT) != WALK_TAIL_DIM:
        raise AssertionError("tail layout drifted off 24")
    if WALK_FRAMES * WALK_FRAME_DIM + WALK_TAIL_DIM != WALK_OBS:
        raise AssertionError("10×32+24 drifted off 344")
    return {"ok": True, "formula": formula(), "walk": "344→13"}


def extract_official_needles(repo: Path | None = None) -> dict[str, Any]:
    """Read-only. Missing deploy source → note the path, do not invent names."""
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("obs assembly leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    sources: dict[str, Any] = {}
    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    missing_yaml = [
        needle
        for needle in (
            "num_observations: 344",
            "num_base_observations: 32",
            "num_last_observations: 24",
            "history_size: 10",
            "num_actions: 13",
        )
        if needle not in yaml_text
    ]
    if missing_yaml:
        raise AssertionError(f"K1.yaml assembly needles missing {missing_yaml}")
    sources["k1_yaml"] = K1_YAML_REL

    t1 = (repo / T1_PY_REL).read_text(encoding="utf-8")
    if "num_base_obs * self.num_history + self.num_last_obs" not in t1:
        raise AssertionError("t1.py missing num_obs = base*history + last formula")
    if "obs_buf.roll(shifts=-1" not in t1:
        raise AssertionError("t1.py missing history roll (left-shift)")
    sources["t1_py"] = T1_PY_REL

    header = repo / WALKING_ENGINE_H_REL
    cpp = repo / WALKING_ENGINE_CPP_REL
    if header.is_file():
        h_text = header.read_text(encoding="utf-8")
        if "RingBuffer<HistoryData, 10>" not in h_text:
            raise AssertionError("WalkingEngine.h historyBuffer is not 10")
        sources["walking_engine_h"] = WALKING_ENGINE_H_REL
        sources["history_buffer_skip"] = False
    else:
        sources["walking_engine_h"] = None
        sources["history_buffer_skip"] = True
        sources["history_buffer_note"] = f"missing {WALKING_ENGINE_H_REL}; not fabricating"

    if cpp.is_file():
        c_text = cpp.read_text(encoding="utf-8")
        for needle in ("data.gravity", "data.gyro", "measuredAngles", "lastActions", "rawFrequency"):
            if needle not in c_text:
                raise AssertionError(f"WalkingEngine.cpp missing {needle}")
        sources["walking_engine_cpp"] = WALKING_ENGINE_CPP_REL
    else:
        sources["walking_engine_cpp"] = None
        sources["cpp_note"] = f"missing {WALKING_ENGINE_CPP_REL}; not fabricating field names"

    if not (repo / DOC_REL).is_file():
        raise AssertionError(f"missing {DOC_REL}")
    return {
        "formula": formula(),
        "sources": sources,
        "deploy_default": "official walk 344→13",
        "via_reactive": False,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def assert_obs_assembly_frozen(repo: Path | None = None) -> dict[str, Any]:
    shapes = validate_assembly_shapes()
    extracted = extract_official_needles(repo)
    refuse_reactive_concat_as_walk({"via_reactive": False, "obs": WALK_OBS})
    return {**shapes, **extracted}
