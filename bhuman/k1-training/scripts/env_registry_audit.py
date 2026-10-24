#!/usr/bin/env python3
"""Read-only official train.py / task-registry audit.

Official K1 must be registered. k1-reactive / estimators / switcher must not.
Writes manifests/env-registry-audit-latest.json.
Never writes YAML. TRAINABLE=false. Never calls train.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK = "344→13"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
AUDIT_REL = "bhuman/k1-training/manifests/env-registry-audit-latest.json"

OFFICIAL_ENV_TREES = (
    "bhuman/MachineLearning/IsaacGymRL/envs",
    "bhuman/k1-training/src/IsaacGymRL/envs",
)
TRAIN_PY_RELS = (
    "bhuman/MachineLearning/IsaacGymRL/train.py",
    "bhuman/k1-training/src/IsaacGymRL/train.py",
)
RUNNER_RELS = (
    "bhuman/MachineLearning/IsaacGymRL/utils/runner.py",
    "bhuman/k1-training/src/IsaacGymRL/utils/runner.py",
)

OFFICIAL_TASKS = ("K1", "K1_Ball", "K1_Stand_Up")
OFFICIAL_IMPORTS = (
    "from envs.k1 import K1",
    "from envs.k1_ball import K1_Ball",
    "from envs.k1_stand_up import K1_Stand_Up",
)
BYPASS_LABELS = ("k1-reactive", "k1-estimators", "k1-switcher")
BYPASS_NEEDLES = (
    "K1_Reactive",
    "k1_reactive",
    "k1-reactive",
    "k1-estimators",
    "k1_estimators",
    "k1-switcher",
    "k1_switcher",
)
RUNNER_NEEDLES = (
    "from envs import *",
    'eval(self.cfg["basic"]["task"])',
    '"--task"',
)
IMPORT_RE = re.compile(r"^from envs\.([A-Za-z0-9_]+) import ([A-Za-z0-9_]+)\s*$")


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(f"env registry audit is read-only; must not write {path or 'K1.yaml'}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_registered_tasks(init_text: str) -> list[str]:
    names: list[str] = []
    for line in init_text.splitlines():
        match = IMPORT_RE.match(line.strip())
        if match:
            names.append(match.group(2))
    return names


def _bypass_hits(text: str) -> list[str]:
    return [needle for needle in BYPASS_NEEDLES if needle in text]


def refuse_tampered_audit(snapshot: dict[str, Any]) -> None:
    """A snapshot that drops official K1 or lists a bypass as registered must fail."""
    if not isinstance(snapshot, dict):
        raise ValueError("registry snapshot must be a mapping")
    if snapshot.get("official_k1_registered") is not True:
        raise ValueError("tampered snapshot: official K1 must stay registered")
    bypass = snapshot.get("bypass_registered") or []
    if bypass:
        raise ValueError(f"tampered snapshot: bypass must not be registered {bypass}")
    tasks = snapshot.get("official_tasks") or []
    if "K1" not in tasks:
        raise ValueError("tampered snapshot: official_tasks missing K1")
    if any(name in tasks for name in ("K1_Reactive", "Estimator", "Switcher")):
        raise ValueError("tampered snapshot: bypass task listed as official")
    if snapshot.get("trainable") or snapshot.get("write_yaml"):
        raise ValueError("tampered snapshot leaked TRAINABLE/WRITE_YAML")


def refuse_leaked_init(init_text: str) -> None:
    hits = _bypass_hits(init_text)
    if hits:
        raise ValueError(f"official envs/__init__.py must not register bypass {hits}")
    if "from envs.k1 import K1" not in init_text:
        raise ValueError("official envs/__init__.py must import K1")


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("env registry audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    trees: list[dict[str, Any]] = []
    official_k1 = True
    bypass_registered: list[str] = []
    notes: list[str] = []

    for rel in OFFICIAL_ENV_TREES:
        init = repo / rel / "__init__.py"
        text = init.read_text(encoding="utf-8") if init.is_file() else ""
        tasks = parse_registered_tasks(text)
        hits = _bypass_hits(text)
        leaked_files = [
            name
            for name in ("K1_Reactive.yaml", "k1_reactive.py", "k1_estimators.py", "k1_switcher.py")
            if (repo / rel / name).is_file()
        ]
        missing_imports = [needle for needle in OFFICIAL_IMPORTS if needle not in text]
        record = {
            "rel": rel,
            "tasks": tasks,
            "official_imports_ok": not missing_imports,
            "bypass_needles": hits,
            "leaked_files": leaked_files,
        }
        trees.append(record)
        if "K1" not in tasks or missing_imports:
            official_k1 = False
            notes.append(f"{rel}: official K1 import missing")
        else:
            notes.append(f"{rel}: official K1 / K1_Ball / K1_Stand_Up in registry")
        if hits or leaked_files:
            bypass_registered.extend(hits or leaked_files)
            notes.append(f"{rel}: bypass leak {hits or leaked_files}")

    train_py: list[dict[str, Any]] = []
    for rel in TRAIN_PY_RELS:
        text = (repo / rel).read_text(encoding="utf-8")
        hits = _bypass_hits(text)
        record = {
            "rel": rel,
            "present": True,
            "mentions_runner": "Runner" in text,
            "bypass_needles": hits,
        }
        train_py.append(record)
        if hits:
            bypass_registered.extend(hits)
        else:
            notes.append(f"{rel}: no bypass task name")

    runners: list[dict[str, Any]] = []
    for rel in RUNNER_RELS:
        text = (repo / rel).read_text(encoding="utf-8")
        missing = [needle for needle in RUNNER_NEEDLES if needle not in text]
        hits = _bypass_hits(text)
        record = {
            "rel": rel,
            "eval_task": 'eval(self.cfg["basic"]["task"])' in text,
            "from_envs_star": "from envs import *" in text,
            "missing_needles": missing,
            "bypass_needles": hits,
        }
        runners.append(record)
        if missing:
            official_k1 = False
            notes.append(f"{rel}: missing runner needles {missing}")
        else:
            notes.append(f"{rel}: eval(task) from envs import *")
        if hits:
            bypass_registered.extend(hits)

    unique_bypass = sorted(set(bypass_registered))
    snapshot = {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "walk": WALK,
        "task": "K1",
        "trainable": False,
        "write_yaml": False,
        "official_k1_registered": official_k1 and not unique_bypass,
        "official_tasks": list(OFFICIAL_TASKS),
        "bypass_checked": list(BYPASS_LABELS),
        "bypass_registered": unique_bypass,
        "trees": trees,
        "train_py": train_py,
        "runner": runners,
        "k1_yaml_sha256": _sha256(yaml_path),
        "notes": notes,
        "verdict": "PASS" if official_k1 and not unique_bypass else "FAIL",
    }
    refuse_tampered_audit(
        {
            "official_k1_registered": snapshot["official_k1_registered"],
            "bypass_registered": snapshot["bypass_registered"],
            "official_tasks": snapshot["official_tasks"],
            "trainable": snapshot["trainable"],
            "write_yaml": snapshot["write_yaml"],
        }
    )
    if snapshot["verdict"] != "PASS":
        raise AssertionError(f"official registry audit failed: {notes}")
    return snapshot


def write_audit(repo: Path | None = None, out: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    snapshot = audit(repo)
    path = out if out is not None else repo / AUDIT_REL
    if not path.is_absolute():
        path = repo / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        snapshot["wrote"] = str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        snapshot["wrote"] = str(path)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None)
    parser.add_argument("--json-out", default=AUDIT_REL)
    args = parser.parse_args()
    repo = Path(args.repo) if args.repo else None
    snapshot = write_audit(repo, Path(args.json_out))
    print(
        f"[env-registry] {snapshot['verdict']} official K1 in; "
        f"bypass {snapshot['bypass_checked']} not registered"
    )
    print(f"[write] {snapshot.get('wrote')}")
    for item in snapshot.get("notes") or []:
        print(f"[note] {item}")
    return 0 if snapshot["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
