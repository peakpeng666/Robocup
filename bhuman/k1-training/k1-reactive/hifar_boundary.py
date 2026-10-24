"""HiFAR / Huoshen T1 boundary (no Gym, no weights loaded).

HiFAR (arXiv 2502.20061) is T1 fall recovery, not official standup 73->22
or fast 72->22, and not Huoshen soccer 58+stack50->15.

This module only refuses foreign weights / dims and checks doc pointers.
See bhuman/docs/HIFAR-VS-STANDUP.md and GLOBAL §6.1 / §6.2.
Research inputs on this checkout:
  bhuman/research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md
"""
from __future__ import annotations

from pathlib import Path

from contract import FORBIDDEN_ACTOR_WEIGHTS, HUOSHEN_T1_ACT, HUOSHEN_T1_OBS, WALK_OBS
from env_stub import refuse_foreign_checkpoint

HIFAR_ARXIV = "2502.20061"
HUOSHEN_ARXIV = "2511.03996"
RESEARCH_INPUTS = (
    "bhuman/research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md",
    "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md",
    "bhuman/docs/HIFAR-VS-STANDUP.md",
    "bhuman/docs/RESEARCH-BRANCH.md",
)
ISAAC_TREES = (
    "bhuman/MachineLearning/IsaacGymRL",
    "bhuman/k1-training/src/IsaacGymRL",
)
FORBIDDEN_MARKERS = ("HiFAR", "hifar", "huoshen", "num_stack", "history_embedding_dim")


def refuse_huoshen_obs_as_walk(obs_dim: int, act_dim: int | None = None) -> None:
    if obs_dim == HUOSHEN_T1_OBS:
        raise ValueError("Huoshen T1 58-D obs is not official walk 344")
    if obs_dim == WALK_OBS and act_dim == HUOSHEN_T1_ACT:
        raise ValueError("walk 344 cannot pair with Huoshen / reactive 15-D action as K1 walk")
    if obs_dim == 73 or obs_dim == 72:
        if act_dim == HUOSHEN_T1_ACT:
            raise ValueError("standup dims cannot load a Huoshen 15-D actor")


def refuse_t1_weight_on_k1_actor(path: str = "model.pth") -> None:
    refuse_foreign_checkpoint(path)


def official_trees_without_hifar(repo: Path) -> None:
    for rel in ISAAC_TREES:
        root = repo / rel
        if not root.is_dir():
            raise AssertionError(f"missing official tree {rel}")
        hits: list[str] = []
        for sub in ("envs", "utils"):
            folder = root / sub
            if not folder.is_dir():
                continue
            for path in folder.rglob("*"):
                if path.suffix.lower() not in {".py", ".yaml", ".yml", ".md", ".cfg"}:
                    continue
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                found = [m for m in FORBIDDEN_MARKERS if m in text]
                if found:
                    hits.append(f"{path.relative_to(repo)}:{found}")
        if hits:
            raise AssertionError(f"{rel} leaked HiFAR/Huoshen markers: {hits[:6]}")


def research_input_pointers(repo: Path) -> None:
    for rel in RESEARCH_INPUTS:
        path = repo / rel
        if not path.is_file():
            raise AssertionError(f"missing research-input {rel}")
        text = path.read_text(encoding="utf-8")
        if rel.endswith("HIFAR-VS-STANDUP.md") and HIFAR_ARXIV not in text:
            raise AssertionError("HIFAR-VS-STANDUP.md lost arXiv 2502.20061")
        if rel.endswith("GLOBAL-HUMANOID-SURVEY-20261024.md"):
            if "§6.2" not in text and "6.2 HiFAR" not in text:
                raise AssertionError("GLOBAL missing HiFAR §6.2")
            if "火神" not in text:
                raise AssertionError("GLOBAL missing 火神 §6.1")
        if rel.endswith("huoshen_findings.md") and "T1" not in text:
            raise AssertionError("huoshen_findings.md must keep the T1-not-K1 review")


def assert_hifar_boundary(repo: Path) -> None:
    try:
        refuse_t1_weight_on_k1_actor("model.pth")
    except ValueError:
        pass
    else:
        raise AssertionError("T1 model.pth must not load onto a K1 actor")
    try:
        refuse_t1_weight_on_k1_actor("K1_walk.pth")
    except ValueError:
        pass
    else:
        raise AssertionError("official walk weights must not load as a HiFAR/Huoshen actor")
    try:
        refuse_huoshen_obs_as_walk(HUOSHEN_T1_OBS, HUOSHEN_T1_ACT)
    except ValueError:
        pass
    else:
        raise AssertionError("Huoshen 58→15 must not be accepted as official walk")
    official_trees_without_hifar(repo)
    research_input_pointers(repo)
