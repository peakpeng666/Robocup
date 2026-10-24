#!/usr/bin/env python3
"""PR #4 index grouped nav + volume health; GAP stays open."""
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
    rel = "bhuman/k1-training/scripts/pr4_index_nav.py"
    spec = importlib.util.spec_from_file_location("pr4_index_nav_test", repo / rel)
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
        errors.append("pr4-index-nav test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("pr4-index-nav flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_index_nav_frozen(repo)
        notes.append("assert_index_nav_frozen: grouped nav + volume; GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "index missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate grouped nav")
        else:
            notes.append("honest SKIP: grouped nav not fabricated")
    elif snap:
        ids = [row.get("id") for row in (snap.get("groups") or [])]
        expected = ["walk", "kick", "standup", "handoff", "artifacts", "GAP"]
        if ids != expected:
            errors.append(f"index groups drifted: {ids}")
        else:
            notes.append("groups frozen: walk / kick / standup / handoff / artifacts / GAP")
        gap = snap.get("gap") or {}
        if gap.get("gap_closed") or gap.get("status") != "GAP" or snap.get("pr_index_claims_gap_closed"):
            errors.append("PR4-INDEX must keep status=GAP / gap_closed=false")
        else:
            notes.append("walk↔kick GAP stays open")
        vol = snap.get("volume") or {}
        if vol.get("files") != 335 or not vol.get("no_more_large_binaries"):
            errors.append("volume-health pin must keep ~335 files / 勿再塞大二进制")
        else:
            notes.append("volume health: ~+191k / 335 files; no more large binaries")

    try:
        mod.refuse_pr_index_claims_gap_closed(
            {"pr_index_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("PR4-INDEX GAP-closed claim must raise")
    except ValueError:
        notes.append("negative: PR4-INDEX GAP-closed claim refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/pr4-index-nav-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (blob.get("gap") or {}).get("gap_closed") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep GAP open / walk 344→13")
        else:
            notes.append("wrote manifests/pr4-index-nav-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during pr4-index-nav test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "gap_closed": False,
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[pr4-index] {'PASS' if report['ok'] else 'FAIL'} "
        "grouped nav + volume health; GAP open; walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
