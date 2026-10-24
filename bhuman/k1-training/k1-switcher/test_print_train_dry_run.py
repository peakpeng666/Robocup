#!/usr/bin/env python3
"""Print-only train dry-run: official --task K1; never spawn train.py."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
from contextlib import redirect_stdout
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
    rel = "bhuman/k1-training/scripts/print_train_dry_run.py"
    spec = importlib.util.spec_from_file_location("print_train_dry_run_test", repo / rel)
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
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("train dry-run test imported Gym")

    dry = _load(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    src = (repo / "bhuman/k1-training/scripts/print_train_dry_run.py").read_text(
        encoding="utf-8"
    )

    if not _source_never_spawns_train(src):
        errors.append("print_train_dry_run.py must not subprocess train.py")
    else:
        notes.append("source does not spawn train.py")
    if "import subprocess" in src:
        errors.append("print_train_dry_run.py must not import subprocess")
    else:
        notes.append("no subprocess import in dry-run generator")

    try:
        dry.refuse_exec_flag(["--exec"])
        errors.append("--exec must be refused")
    except ValueError:
        notes.append("negative: --exec refused")

    try:
        dry.refuse_foreign_task("K1_Reactive")
        errors.append("K1_Reactive must be refused as first-train task")
    except ValueError:
        notes.append("negative: --task K1_Reactive refused")

    try:
        live = dry.build_dry_run(repo)
        if live.get("task") != "K1" or live.get("walk") != "344→13":
            errors.append("dry-run draft must stay official --task K1 344→13")
        if live.get("will_run_train_py") or live.get("trainable"):
            errors.append("dry-run must stay will_run_train_py=false / TRAINABLE=false")
        if live.get("dry_run_success_means_trainable"):
            errors.append("dry-run success must not mean trainable")
        if live.get("banner") != "必须先告知用户并等待明确开训":
            errors.append("banner must be 必须先告知用户并等待明确开训")
        if "--task K1" not in (live.get("train_py_draft") or ""):
            errors.append("train.py draft must contain --task K1")
        if "K1_Reactive" in (live.get("train_py_draft") or ""):
            errors.append("train.py draft must not name K1_Reactive")
        notes.append(
            f"live dry-run ready_gpu={live.get('ready_gpu')} missing={live.get('missing')}"
        )
        if not live.get("ready_gpu"):
            if not live.get("missing"):
                errors.append("ready=false must list missing items")
            else:
                notes.append(f"ready=false listed missing {live.get('missing')}")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    complete = {
        "cuda": {"ok": True, "detail": "injected"},
        "isaacgym_or_alt": {"ok": True, "detail": "injected"},
        "disk": {"ok": True, "detail": "injected"},
        "official_k1_task": {"ok": True, "detail": "injected", "task": "K1"},
        "checkpoint": {"ok": True, "detail": "injected"},
    }
    try:
        ready = dry.build_dry_run(repo, facts=complete)
        if not ready.get("ready_gpu"):
            errors.append("injected complete facts must yield ready_gpu=true")
        elif ready.get("will_run_train_py") or ready.get("trainable"):
            errors.append("ready_gpu=true still must not train")
        else:
            notes.append("injected ready=true still print-only / will_run_train_py=false")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = dry.main([])
    printed = buf.getvalue()
    if code != 0:
        errors.append(f"dry-run main must exit 0, got {code}")
    missing_print = [
        needle
        for needle in (
            "必须先告知用户并等待明确开训",
            "--task K1",
            "344→13",
            "will_run_train_py=false",
            "干跑成功 ≠ 可训",
        )
        if needle not in printed
    ]
    if missing_print:
        errors.append(f"printed dry-run missing {missing_print}")
    else:
        notes.append("printed banner + official --task K1 draft; exit 0")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during train dry-run test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[train-dry-run] {'PASS' if report['ok'] else 'FAIL'} "
        "print-only --task K1; 干跑成功 ≠ 可训"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
