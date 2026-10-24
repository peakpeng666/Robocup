#!/usr/bin/env python3
"""Official sibling tasks: K1_Ball / Stand_Up ≠ walk baseline; no merge into 344."""
from __future__ import annotations

import hashlib
import importlib.util
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
    rel = "bhuman/k1-training/scripts/official_sibling_tasks_audit.py"
    spec = importlib.util.spec_from_file_location("sibling_tasks_audit_test", repo / rel)
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
        errors.append("sibling-task audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("sibling-task audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_siblings_frozen(repo)
        notes.append("assert_siblings_frozen: default K1 344→13; siblings not baseline")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    if data.get("default_task") != "K1" or data.get("may_merge_into_344"):
        errors.append("default walk / merge-into-344 contract drifted")
    k1 = {row["task"]: row for row in (data.get("k1_siblings") or [])}
    if set(k1) != {"K1_Ball", "K1_Stand_Up"}:
        errors.append(f"K1 sibling set drifted: {sorted(k1)}")
    else:
        if (k1["K1_Ball"].get("obs"), k1["K1_Ball"].get("act")) != (59, 13):
            errors.append("K1_Ball drifted off 59→13")
        if (k1["K1_Stand_Up"].get("obs"), k1["K1_Stand_Up"].get("act")) != (73, 22):
            errors.append("K1_Stand_Up drifted off 73→22")
        notes.append("K1_Ball 59→13 / K1_Stand_Up 73→22; not walk baseline")

    t1 = {row["task"] for row in (data.get("t1_registered_not_k1") or [])}
    if t1 != {"T1", "T1_Ball", "T1_Stand_Up"}:
        errors.append(f"T1 registered set drifted: {sorted(t1)}")
    else:
        notes.append("T1 / T1_Ball / T1_Stand_Up registered ≠ K1 walk")

    deploy = data.get("deploy_only") or []
    if any(row.get("registered") for row in deploy):
        errors.append("fast standup must stay unregistered")
    else:
        notes.append("K1_fast_standup 72→22 deploy-only, not an Isaac task")

    for task in ("K1_Ball", "K1_Stand_Up", "T1", "K1_fast_standup"):
        try:
            mod.refuse_sibling_as_walk_baseline(task)
            errors.append(f"{task} as walk baseline must raise")
        except ValueError:
            notes.append(f"negative: {task} as walk baseline refused")

    try:
        mod.refuse_merge_sibling_into_344(
            {"task": "K1_Ball", "concat_into": 344, "extra_obs": 59}
        )
        errors.append("merge K1_Ball into 344 must raise")
    except ValueError:
        notes.append("negative: sibling concat-into-344 refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = mod.write_audit(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during sibling-task audit")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[sibling-tasks] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_Ball/Stand_Up ≠ walk; no merge into 344"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
