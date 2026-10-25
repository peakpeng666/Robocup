"""Resolved locations of the B-Human foundation and of Forge's own state.

ROBOCUP_ROOT overrides the project root; everything else is derived from it so the
system never depends on the working directory it was started from.
"""
import os
from pathlib import Path

ROOT = Path(os.environ.get("ROBOCUP_ROOT", Path(__file__).resolve().parents[2])).resolve()
FORGE = ROOT / "forge"

# Foundation (read-only for Forge).
BH_OFFICIAL = ROOT / "bhuman/BHumanCodeRelease"
BH_VALIDATION = ROOT / "bhuman/local-k1-validation-20261019"
BH_LOCAL = BH_VALIDATION / "bhuman-local"
BH_LOCAL_RUNS = BH_VALIDATION / "runs"
BH_SIM_LOCK = BH_VALIDATION / ".bhuman-sim.lock"
TRAINING = ROOT / "bhuman/k1-training"
ISAACGYMRL = TRAINING / "src/IsaacGymRL"
SIM2SIM = ROOT / "bhuman/sim2sim"
BOOSTER_SDK = ROOT / "booster/booster_robotics_sdk"
GC_CONFIG_2026 = ROOT / "26game_controller/game_controller/config"

OFFICIAL_UPSTREAM = {
    "BHumanCodeRelease": "2e3374ba896da8288607f9a1881b876642fe18b8",
    "MachineLearning": "c3fed817e6e8fd06418bea824b1f1ab0157379d2",
}
TRAINING_SOURCE_FINGERPRINT = "efd4263eec489211e1266760e72df219c4bd405431047bf2001679632af5844c"

# Forge state.
PACKS = FORGE / "packs"
STRATEGIES = FORGE / "strategies"
ARENAS = FORGE / "arena"
RUNS = FORGE / "runs"
VARIANTS = FORGE / "variants"
THIRD_PARTY = FORGE / "third_party"
STATE = FORGE / "run"
DB_PATH = FORGE / "forge.db"

INTERPRETERS = {
    "bh_gym": Path.home() / ".venvs/bh-gym/bin/python",          # Py3.8 + Isaac Gym Preview 4 (training mainline)
    "mujoco": Path.home() / ".venvs/mujoco-sim2sim/bin/python",    # Py3.12 + MuJoCo 3.8 (sim2sim)
    "forge": Path.home() / ".venvs/forge/bin/python",            # Py3.12 control plane
    "mjlab": Path.home() / ".venvs/forge-mjlab/bin/python",      # Py3.12 + MuJoCo Warp (second training backend)
}

SIMROBOT_RELEASE = BH_LOCAL / "Build/Linux/SimRobot/Release/SimRobot"


def rel(path) -> str:
    """Path relative to ROOT for display; absolute if outside."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)
