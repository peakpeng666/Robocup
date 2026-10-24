#!/usr/bin/env python3
"""Kick + standup train dry-run: print-only 59→13 / 73→22; would_train=false."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/kick_standup_train_dry_run.py"
    spec = importlib.util.spec_from_file_location(
        "kick_standup_train_dry_run_test", repo / rel
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_never_spawns_train(src: str) -> bool:
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "train.py" not in line:
            continue
        if any(
            tok in line
            for tok in (
                "subprocess.",
                "os.system(",
                "os.exec",
                "Popen(",
                "check_call(",
                "check_output(",
            )
        ):
            return False
    return True


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick/standup train dry-run test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.AUTO_TRAIN
        or mod.WOULD_TRAIN
    ):
        errors.append("kick/standup train dry-run flags leaked")

    src = (repo / "bhuman/k1-training/scripts/kick_standup_train_dry_run.py").read_text(
        encoding="utf-8"
    )
    if not _source_never_spawns_train(src):
        errors.append("kick_standup_train_dry_run.py must not subprocess train.py")
    else:
        notes.append("source does not spawn train.py")
    if "import subprocess" in src:
        errors.append("kick_standup_train_dry_run.py must not import subprocess")
    else:
        notes.append("no subprocess import in sibling dry-run generator")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_kick_standup_train_dry_run_frozen(repo)
        notes.append("assert_kick_standup_train_dry_run_frozen: would_train=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"kick/standup checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: kick 59 / standup 73 / fast note / would_train=false")
    dry = (snap.get("dry_run") or {})
    kick = dry.get("kick") or {}
    standup = dry.get("standup") or {}
    fast = dry.get("fast") or {}
    if kick.get("dims") != "59→13" or standup.get("dims") != "73→22":
        errors.append("sibling dims drifted")
    else:
        notes.append("kick 59→13 / standup 73→22 print-only")
    if fast.get("train_py_draft") or fast.get("isaac_registered"):
        errors.append("fast standup must stay note-only / not Isaac")
    else:
        notes.append("fast 72→22 note only; not an Isaac train task")
    if snap.get("would_train") or snap.get("will_run_train_py") or snap.get("ready_gpu"):
        errors.append("kick/standup dry-run leaked would_train / ready_gpu")
    else:
        notes.append("would_train=false; ready_gpu=false; print-only")
    if (
        snap.get("generated_cmd_as_launch_auth")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("kick/standup dry-run must stay not-launch-auth / GAP open")
    else:
        notes.append("printed cmds ≠ launch authorization; GAP open")

    try:
        mod.refuse_generated_cmd_as_launch_auth(
            {"generated_cmd_as_launch_auth": True, "would_train": True, "this_pin": True}
        )
        errors.append("generated_cmd_as_launch_auth must raise")
    except ValueError:
        notes.append("negative: generated cmd as launch authorization refused")
    try:
        mod.refuse_foreign_train_task("K1_fast_standup")
        errors.append("K1_fast_standup as train task must raise")
    except ValueError:
        notes.append("negative: fast standup as Isaac train task refused")
    try:
        mod.refuse_exec_flag(["--exec"])
        errors.append("--exec must be refused")
    except ValueError:
        notes.append("negative: --exec refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/kick-standup-train-dry-run-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("would_train")
            or blob.get("will_run_train_py")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep would_train=false / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/kick-standup-train-dry-run-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick/standup dry-run test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during sibling dry-run test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick/standup dry-run test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-standup-dry-run] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_Ball 59→13 / K1_Stand_Up 73→22 print-only; would_train=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
