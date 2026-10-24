#!/usr/bin/env python3
"""Print-only first-train command draft for official walk --task K1.

Never spawns train.py. Never starts Isaac Gym.
Dry-run success ≠ trainable. TRAINABLE=false. Never writes YAML.

If probe_reserved_gpu ready=false, list missing items and still exit 0.
Banner: 必须先告知用户并等待明确开训.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WILL_RUN_TRAIN_PY = False
WILL_RUN_ISAAC_GYM = False
BANNER = "必须先告知用户并等待明确开训"
WALK = "344→13"
OFFICIAL_TASK = "K1"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
PROBE_REL = "bhuman/k1-training/scripts/probe_reserved_gpu.py"

LOCAL_VENV = "~/.venvs/bh-gym"
LOCAL_BH_PY = "$HOME/.venvs/bh-gym/bin/python"
LOCAL_WORKTREE = "$HOME/Desktop/Robocup-pr4"
LOCAL_LINKS = ("third_party", "downloads", "cache")
WRAPPER_DRAFT = (
    "bash bhuman/k1-training/scripts/run_walk_stability.sh 4096 25 7 warm-start"
)
TRAIN_PY_DRAFT = (
    "$BH_PY bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1 "
    "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
    "--headless true --checkpoint <operator-local K1_walk.pth> --load_mode warm-start"
)
LOCAL_WRAPPER_DRAFT = (
    f"cd {LOCAL_WORKTREE} && BH_PY={LOCAL_BH_PY} {WRAPPER_DRAFT}"
)
LOCAL_TRAIN_PY_DRAFT = (
    f"cd {LOCAL_WORKTREE} && {LOCAL_BH_PY} "
    "bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1 "
    "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
    "--headless true --checkpoint <operator-local K1_walk.pth> --load_mode warm-start"
)
FORBIDDEN_TASKS = frozenset(
    {
        "K1_Reactive",
        "K1_reactive",
        "reactive",
        "k1-reactive",
        "huoshen",
        "Huoshen",
        "nusim",
        "NUSim",
    }
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load_probe(repo: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "probe_reserved_gpu_dry_run", repo / PROBE_REL
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {PROBE_REL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refuse_foreign_task(task: str) -> None:
    if task != OFFICIAL_TASK or task in FORBIDDEN_TASKS:
        raise ValueError(
            f"first-train draft must be official --task {OFFICIAL_TASK} 344→13, "
            f"not {task!r}"
        )


def refuse_exec_flag(argv: list[str] | None = None) -> None:
    """This generator is print-only; --exec / --run / --train are forbidden."""
    args = argv if argv is not None else sys.argv[1:]
    banned = {"--exec", "--run", "--train", "--execute"}
    hit = [item for item in args if item in banned or item.startswith("--exec=")]
    if hit:
        raise ValueError(f"print_train_dry_run is print-only; refused {hit}")


def official_walk_frozen(repo: Path) -> None:
    text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off 344→13")


def build_dry_run(
    repo: Path | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the printed draft. Does not spawn train.py."""
    if TRAINABLE or WRITE_YAML or WILL_RUN_TRAIN_PY:
        raise AssertionError("dry-run leaked TRAINABLE / WRITE_YAML / will_run_train_py")
    repo = _repo(repo)
    official_walk_frozen(repo)
    refuse_foreign_task(OFFICIAL_TASK)
    probe = _load_probe(repo)
    checklist = probe.build_checklist(repo, facts)
    ready = bool(checklist.get("ready"))
    missing = list(checklist.get("missing") or [])
    return {
        "ok": True,
        "verdict": "DRY-RUN",
        "walk": WALK,
        "task": OFFICIAL_TASK,
        "trainable": False,
        "write_yaml": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "dry_run_success_means_trainable": False,
        "ready_gpu": ready,
        "missing": missing,
        "banner": BANNER,
        "wrapper_draft": WRAPPER_DRAFT,
        "train_py_draft": TRAIN_PY_DRAFT,
        "local_venv": LOCAL_VENV,
        "local_bh_py": LOCAL_BH_PY,
        "local_worktree": LOCAL_WORKTREE,
        "local_links": list(LOCAL_LINKS),
        "local_wrapper_draft": LOCAL_WRAPPER_DRAFT,
        "local_train_py_draft": LOCAL_TRAIN_PY_DRAFT,
        "note": "干跑成功 ≠ 可训；本脚本不调用 train.py / 不启 Isaac",
    }


def render(report: dict[str, Any]) -> str:
    bar = "=" * 64
    missing = report.get("missing") or []
    missing_line = (
        f"[dry-run] ready_gpu=false missing: {', '.join(missing)}"
        if not report.get("ready_gpu")
        else "[dry-run] ready_gpu=true (still print-only; do not train)"
    )
    return "\n".join(
        [
            bar,
            f"  {BANNER}",
            "  干跑成功 ≠ 可训；本脚本不调用 train.py / 不启 Isaac",
            bar,
            missing_line,
            f"[dry-run] official first train stays --task {OFFICIAL_TASK} {WALK}",
            f"[draft] {report['wrapper_draft']}",
            f"[draft] {report['train_py_draft']}",
            f"[local] venv={report.get('local_venv')} worktree={report.get('local_worktree')}",
            f"[local] {report.get('local_wrapper_draft')}",
            f"[local] {report.get('local_train_py_draft')}",
            "[dry-run] will_run_train_py=false will_run_isaac_gym=false",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    refuse_exec_flag(argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None)
    args = parser.parse_args(argv)
    repo = Path(args.repo) if args.repo else None
    report = build_dry_run(repo)
    print(render(report))
    # ready=false is a successful dry-run, not a contract failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
