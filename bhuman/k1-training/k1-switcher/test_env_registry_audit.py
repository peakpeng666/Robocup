#!/usr/bin/env python3
"""Official train.py registry: K1 in; reactive/estimators/switcher out."""
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
    rel = "bhuman/k1-training/scripts/env_registry_audit.py"
    spec = importlib.util.spec_from_file_location("env_registry_audit_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("env registry audit test imported Gym")

    audit = _load(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    src = (repo / "bhuman/k1-training/scripts/env_registry_audit.py").read_text(
        encoding="utf-8"
    )
    if "subprocess" in src or "train.py --task" in src:
        errors.append("registry audit must not spawn train.py")
    else:
        notes.append("audit is read-only (no train.py spawn)")

    try:
        live = audit.audit(repo)
        if live.get("official_k1_registered") is not True:
            errors.append("official K1 must be registered")
        if live.get("bypass_registered"):
            errors.append(f"bypass leaked into registry {live.get('bypass_registered')}")
        if live.get("walk") != "344→13" or live.get("trainable"):
            errors.append("audit must stay walk 344→13 / TRAINABLE=false")
        tasks = live.get("official_tasks") or []
        if "K1" not in tasks:
            errors.append("official_tasks must include K1")
        notes.append("live: official K1 in; k1-reactive / estimators / switcher out")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    try:
        audit.refuse_tampered_audit(
            {
                "official_k1_registered": False,
                "bypass_registered": [],
                "official_tasks": ["K1"],
                "trainable": False,
                "write_yaml": False,
            }
        )
        errors.append("tampered official_k1_registered=false must fail")
    except ValueError:
        notes.append("negative: dropped official K1 refused")

    try:
        audit.refuse_tampered_audit(
            {
                "official_k1_registered": True,
                "bypass_registered": ["K1_Reactive"],
                "official_tasks": ["K1"],
                "trainable": False,
                "write_yaml": False,
            }
        )
        errors.append("tampered bypass_registered must fail")
    except ValueError:
        notes.append("negative: K1_Reactive listed as registered refused")

    try:
        audit.refuse_leaked_init(
            "from envs.k1 import K1\nfrom envs.k1_reactive import K1_Reactive\n"
        )
        errors.append("leaked K1_Reactive import must fail")
    except ValueError:
        notes.append("negative: leaked envs/__init__ K1_Reactive refused")

    try:
        audit.refuse_leaked_init("from envs.t1 import T1\n")
        errors.append("init missing official K1 must fail")
    except ValueError:
        notes.append("negative: missing K1 import refused")

    try:
        audit.refuse_write_yaml("K1.yaml")
        errors.append("write-back API must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    try:
        written_snap = audit.write_audit(repo)
        written = repo / "bhuman/k1-training/manifests/env-registry-audit-latest.json"
        if not written.is_file():
            errors.append("missing env-registry-audit-latest.json")
        else:
            blob = json.loads(written.read_text(encoding="utf-8"))
            if blob.get("official_k1_registered") is not True:
                errors.append("written snapshot must keep official K1 registered")
            elif blob.get("bypass_registered"):
                errors.append("written snapshot must not list bypass as registered")
            else:
                notes.append("wrote env-registry-audit-latest.json (K1 in; bypass out)")
        if written_snap.get("verdict") != "PASS":
            errors.append("write_audit verdict must be PASS")
    except (AssertionError, ValueError, OSError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during env-registry audit test")
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
        f"[env-registry] {'PASS' if report['ok'] else 'FAIL'} "
        "official K1 in; bypass not registered"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
