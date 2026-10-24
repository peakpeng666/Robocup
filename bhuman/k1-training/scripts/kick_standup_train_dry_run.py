"""Kick + standup train dry-run command generators (print-only; no GPU).

Mirrors walk `print_train_dry_run` for official sibling tasks:

  * kick  K1_Ball      59→13  (print only)
  * standup K1_Stand_Up 73→22  (print only)
  * fast  72→22 note only — deploy-only; not an Isaac registered task

would_train=false. Never exec train.py / Isaac.
Printed commands are not launch authorization.
TRAINABLE=false. walk↔kick GAP stays open.

Does not import local_artifact_upload_cleanup.
Does not replace print_train_dry_run (walk --task K1 stays the first-train draft).

Runnable: python3 bhuman/k1-training/scripts/kick_standup_train_dry_run.py
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
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from print_train_dry_run import (  # noqa: E402
    BANNER,
    LOCAL_BH_PY,
    LOCAL_VENV,
    LOCAL_WORKTREE,
    WILL_RUN_ISAAC_GYM,
    WILL_RUN_TRAIN_PY,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
AUTO_TRAIN = False
WOULD_TRAIN = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
K1_STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-standup-train-dry-run-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "kick_59_13_print_only",
    "standup_73_22_print_only",
    "fast_72_22_note_not_isaac",
    "would_train_false",
    "never_exec_train",
    "generated_cmd_not_launch_auth",
)

KICK_TASK = "K1_Ball"
STANDUP_TASK = "K1_Stand_Up"
FORBIDDEN_TRAIN_TASKS = frozenset(
    {
        "K1_Reactive",
        "K1_reactive",
        "reactive",
        "K1_fast_standup",
        "k1_fast_standup",
        "huoshen",
        "Huoshen",
        "nusim",
        "NUSim",
        "T1",
        "T1_Ball",
        "T1_Stand_Up",
    }
)

KICK_TRAIN_PY_DRAFT = (
    "$BH_PY bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1_Ball "
    "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
    "--headless true --checkpoint <operator-local K1_kick_inner.pth> --load_mode warm-start"
)
STANDUP_TRAIN_PY_DRAFT = (
    "$BH_PY bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1_Stand_Up "
    "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
    "--headless true --checkpoint <operator-local K1_standup.pth> --load_mode warm-start"
)
FAST_NOTE = (
    "K1_fast_standup is deploy-only 72→22; not an Isaac registered task; "
    "no train.py command; run_replay.sh does not accept K1_fast_standup"
)

DOC_NEEDLES = (
    "kick_standup_train_dry_run",
    "K1_Ball",
    "59→13",
    "K1_Stand_Up",
    "73→22",
    "72→22",
    "would_train=false",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
    "would_train=true",
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
        f"kick/standup train dry-run is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick/standup train dry-run is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_exec_flag(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    banned = {"--exec", "--run", "--train", "--execute"}
    hit = [item for item in args if item in banned or item.startswith("--exec=")]
    if hit:
        raise ValueError(f"kick_standup_train_dry_run is print-only; refused {hit}")


def refuse_foreign_train_task(task: str) -> None:
    if task in FORBIDDEN_TRAIN_TASKS or task not in {KICK_TASK, STANDUP_TASK}:
        raise ValueError(
            f"sibling dry-run tasks are {KICK_TASK} 59→13 / {STANDUP_TASK} 73→22; "
            f"not {task!r} (fast is not Isaac; walk first-train stays print_train_dry_run)"
        )


def refuse_generated_cmd_as_launch_auth(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("generated-cmd-as-launch-auth claim must be a mapping")
    if (
        claim.get("generated_cmd_as_launch_auth")
        or claim.get("launch_authorized")
        or claim.get("treat_draft_as_start")
        or claim.get("exec_printed_cmd")
        or claim.get("would_train") is True
        or (
            claim.get("will_run_train_py") is True
            and claim.get("this_pin")
        )
    ):
        raise ValueError(
            "printed kick/standup dry-run commands are not launch authorization; "
            f"would_train=false. Tell-user first: {BANNER}"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _require_yaml_dims(path: Path, obs: int, act: int, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if f"num_observations: {obs}" not in text or f"num_actions: {act}" not in text:
        raise AssertionError(f"{label} drifted off {obs}→{act}")


def build_dry_run(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or WOULD_TRAIN:
        raise AssertionError("kick/standup dry-run leaked TRAINABLE / would_train")
    if WILL_RUN_TRAIN_PY or WILL_RUN_ISAAC_GYM:
        raise AssertionError("walk dry-run sibling leaked will_run_train_py")
    repo = _repo(repo)
    _require_yaml_dims(repo / K1_YAML_REL, WALK_OBS, WALK_ACT, "K1.yaml")
    _require_yaml_dims(repo / K1_BALL_YAML_REL, KICK_OBS, KICK_ACT, "K1_Ball.yaml")
    _require_yaml_dims(repo / K1_STAND_YAML_REL, STANDUP_OBS, STANDUP_ACT, "K1_Stand_Up.yaml")
    refuse_foreign_train_task(KICK_TASK)
    refuse_foreign_train_task(STANDUP_TASK)
    return {
        "ok": True,
        "verdict": "DRY-RUN",
        "walk": "344→13",
        "kick": {
            "task": KICK_TASK,
            "dims": "59→13",
            "train_py_draft": KICK_TRAIN_PY_DRAFT,
            "local_train_py_draft": f"cd {LOCAL_WORKTREE} && {LOCAL_BH_PY} "
            "bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1_Ball "
            "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
            "--headless true --checkpoint <operator-local K1_kick_inner.pth> --load_mode warm-start",
            "would_train": False,
        },
        "standup": {
            "task": STANDUP_TASK,
            "dims": "73→22",
            "train_py_draft": STANDUP_TRAIN_PY_DRAFT,
            "local_train_py_draft": f"cd {LOCAL_WORKTREE} && {LOCAL_BH_PY} "
            "bhuman/k1-training/src/IsaacGymRL/train.py --history --task K1_Stand_Up "
            "--num_envs 4096 --max_iterations 25 --save_interval 5 --seed 7 "
            "--headless true --checkpoint <operator-local K1_standup.pth> --load_mode warm-start",
            "would_train": False,
        },
        "fast": {
            "task": None,
            "dims": "72→22",
            "isaac_registered": False,
            "train_py_draft": None,
            "would_train": False,
            "note": FAST_NOTE,
        },
        "banner": BANNER,
        "local_venv": LOCAL_VENV,
        "local_bh_py": LOCAL_BH_PY,
        "local_worktree": LOCAL_WORKTREE,
        "trainable": False,
        "would_train": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "generated_cmd_as_launch_auth": False,
        "ready_gpu": False,
        "note": "printed sibling drafts ≠ launch authorization; walk first-train stays --task K1",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or WOULD_TRAIN:
        raise AssertionError("kick/standup dry-run leaked TRAINABLE / would_train")
    repo = _repo(repo)
    dry = build_dry_run(repo)
    if dry.get("would_train") or dry.get("will_run_train_py") or dry.get("ready_gpu"):
        raise AssertionError("kick/standup dry-run leaked would_train / ready_gpu")
    kick = dry.get("kick") or {}
    standup = dry.get("standup") or {}
    fast = dry.get("fast") or {}
    if kick.get("dims") != "59→13" or standup.get("dims") != "73→22":
        raise AssertionError("sibling dry-run dims drifted")
    if "--task K1_Ball" not in str(kick.get("train_py_draft") or ""):
        raise AssertionError("kick draft missing --task K1_Ball")
    if "--task K1_Stand_Up" not in str(standup.get("train_py_draft") or ""):
        raise AssertionError("standup draft missing --task K1_Stand_Up")
    if fast.get("train_py_draft") or fast.get("isaac_registered"):
        raise AssertionError("fast standup must stay note-only / not Isaac")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    yaml_path = repo / K1_YAML_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/kick_standup_train_dry_run.py",
        "checklist": list(CHECKLIST),
        "dry_run": dry,
        "would_train": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "will_exec_train_here": False,
        "generated_cmd_as_launch_auth": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "kick 59→13 / standup 73→22 print-only; fast 72→22 note only; "
            "would_train=false; printed cmds ≠ launch authorization"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "ball_yaml_sha256": hashlib.sha256(
            (repo / K1_BALL_YAML_REL).read_bytes()
        ).hexdigest(),
        "standup_yaml_sha256": hashlib.sha256(
            (repo / K1_STAND_YAML_REL).read_bytes()
        ).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_kick_standup_train_dry_run_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or WOULD_TRAIN:
        raise AssertionError("kick/standup dry-run leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"kick/standup checklist drifted: {snap.get('checklist')}")
    if snap.get("would_train") or snap.get("will_run_train_py") or snap.get("ready_gpu"):
        raise AssertionError("kick/standup dry-run leaked would_train / ready_gpu")
    if (
        snap.get("generated_cmd_as_launch_auth")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("kick/standup dry-run leaked launch-auth / GAP-closed")
    try:
        refuse_generated_cmd_as_launch_auth(
            {
                "generated_cmd_as_launch_auth": True,
                "would_train": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_generated_cmd_as_launch_auth must raise")
    except ValueError:
        pass
    try:
        refuse_foreign_train_task("K1_fast_standup")
    except ValueError:
        return snap
    raise AssertionError("refuse_foreign_train_task(K1_fast_standup) must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick/standup train dry-run imported Gym")

    yaml_path = repo / K1_YAML_REL
    ball = repo / K1_BALL_YAML_REL
    stand = repo / K1_STAND_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest() if ball.is_file() else ""
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_kick_standup_train_dry_run_frozen(repo)
        notes.append("assert_kick_standup_train_dry_run_frozen: would_train=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("kick 59→13 / standup 73→22 print-only; fast 72→22 note only")
        notes.append("printed commands are not launch authorization")

    try:
        refuse_generated_cmd_as_launch_auth(
            {"launch_authorized": True, "exec_printed_cmd": True}
        )
        errors.append("generated_cmd_as_launch_auth must raise")
    except ValueError:
        notes.append("negative: generated cmd as launch authorization refused")
    try:
        refuse_exec_flag(["--exec"])
        errors.append("refuse_exec_flag must raise")
    except ValueError:
        notes.append("negative: --exec refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(walk_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (ball, before_ball, "K1_Ball.yaml"),
        (stand, before_stand, "K1_Stand_Up.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during kick/standup train dry-run")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "generated_cmd_as_launch_auth": False,
        "will_run_train_py": False,
    }


def main(argv: list[str] | None = None) -> int:
    refuse_exec_flag(argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[kick-standup-dry-run] FAIL {exc}")
        return 1
    dry = snap.get("dry_run") or {}
    print(
        f"[kick-standup-dry-run] {snap.get('status')} "
        f"K1_Ball 59→13 / K1_Stand_Up 73→22 print-only; "
        f"fast 72→22 note; would_train=false; wrote {path}"
    )
    print(f"[banner] {BANNER}")
    print(f"[draft] {(dry.get('kick') or {}).get('train_py_draft')}")
    print(f"[draft] {(dry.get('standup') or {}).get('train_py_draft')}")
    print(f"[note] {(dry.get('fast') or {}).get('note')}")
    print("[dry-run] would_train=false will_run_train_py=false; printed cmds ≠ launch auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
