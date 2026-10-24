#!/usr/bin/env python3
"""upload_run_artifacts scaffold: exists, dry-run help, TRAINABLE=false, no train."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
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
    rel = "bhuman/k1-training/scripts/upload_run_artifacts.py"
    spec = importlib.util.spec_from_file_location("upload_run_artifacts_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("upload-artifacts test imported Gym")

    py = repo / "bhuman/k1-training/scripts/upload_run_artifacts.py"
    sh = repo / "bhuman/k1-training/scripts/upload_run_artifacts.sh"
    doc = repo / "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
    if not py.is_file() or not sh.is_file() or not doc.is_file():
        errors.append("upload scaffold script / wrapper / doc missing")
        return {
            "ok": False,
            "errors": errors,
            "notes": notes,
            "warnings": warnings,
            "trainable": False,
        }

    mod = _load(repo)
    if mod.TRAINABLE or mod.AUTO_TRAIN or mod.WRITE_YAML:
        errors.append("upload scaffold flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    help_out = subprocess.run(
        [sys.executable, "-B", str(py), "--help"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH"},
    )
    help_text = (help_out.stdout or "") + (help_out.stderr or "")
    if help_out.returncode != 0:
        errors.append(f"--help exited {help_out.returncode}")
    for needle in ("TRAINABLE=false", "dry-run", "artifacts/<run-id>", "Git LFS", "train.py"):
        if needle not in help_text:
            errors.append(f"--help missing {needle}")
        else:
            notes.append(f"help has {needle}")

    dry = subprocess.run(
        [sys.executable, "-B", str(py), "--dry-run", "--run-id", "dry-run-example"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH"},
    )
    dry_text = (dry.stdout or "") + (dry.stderr or "")
    if dry.returncode != 0:
        errors.append(f"--dry-run exited {dry.returncode}: {dry_text[-200:]}")
    else:
        notes.append("dry-run exit 0")
    if "344→13" not in dry_text and "344→13" not in help_text:
        errors.append("dry-run/help must mention default walk 344→13")
    if "train.py" in dry_text and "Never calls train.py" not in help_text and "Never invokes train.py" not in py.read_text(encoding="utf-8"):
        errors.append("dry-run must not invoke train.py")

    sh_help = subprocess.run(
        ["bash", str(sh), "--help"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH"},
    )
    if sh_help.returncode != 0:
        errors.append("upload_run_artifacts.sh --help failed")
    else:
        notes.append("wrapper --help ok")

    try:
        frozen = mod.assert_upload_scaffold_frozen(repo)
        notes.append("assert_upload_scaffold_frozen: convention present")
        if (frozen.get("plan") or {}).get("connects_user_home"):
            errors.append("plan must not scan user home")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))

    try:
        mod.refuse_local_artifacts_kept_without_upload_policy(
            {"local_artifacts_kept_without_upload_policy": True, "keep_local_only": True}
        )
        errors.append("local artifacts kept without upload policy must raise")
    except ValueError:
        notes.append("negative: local-only cache pile-up refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/upload-run-artifacts-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("trainable") or blob.get("invokes_train_py") or blob.get("local_artifacts_kept_without_upload_policy"):
            errors.append("written snapshot must stay TRAINABLE=false / upload-required")
        else:
            notes.append("wrote manifests/upload-run-artifacts-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during upload-scaffold test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "auto_train": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[upload-artifacts] {'PASS' if report['ok'] else 'FAIL'} "
        "dry-run help; TRAINABLE=false; no train.py"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
