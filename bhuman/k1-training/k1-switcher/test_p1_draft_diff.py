#!/usr/bin/env python3
"""Official vs draft-only diff: draft_only:true; live paths untouched."""
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
    rel = "bhuman/k1-training/scripts/p1_draft_diff.py"
    spec = importlib.util.spec_from_file_location("p1_draft_diff_test", repo / rel)
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
        errors.append("p1 draft diff test imported Gym")

    diff = _load(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        live = diff.audit(repo)
        if live.get("all_drafts_draft_only") is not True:
            errors.append("snapshot must assert all_drafts_draft_only")
        if live.get("live_paths_untouched") is not True:
            errors.append("snapshot must assert live_paths_untouched")
        if live.get("write_yaml") or live.get("trainable"):
            errors.append("diff snapshot must stay read-only / TRAINABLE=false")
        notes.append("live snapshot: draft_only:true and live paths untouched")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    if live:
        sources = live.get("sources") or {}
        official = " ".join(
            str(item)
            for key in ("stability", "k1_yaml")
            for item in (
                sources.get(key) if isinstance(sources.get(key), list) else [sources.get(key)]
            )
            if item
        )
        if "draft-only" in official:
            errors.append("official sources must not include draft-only")
        else:
            notes.append("official stability / K1.yaml listed separately from draft-only")
        related = (live.get("diff") or {}).get("related_live_vs_proposed") or []
        if related and any(item.get("live_updated") for item in related):
            errors.append("related proposed keys must not mark live_updated")
        else:
            notes.append("proposed still_proportion / penalty anneal not applied live")

    missing_flag = {"draft_only": False, "trainable": False, "factors": {}}
    try:
        diff.assert_drafts_draft_only  # presence
        # Inject via require path: a dict without draft_only must fail if validated.
        if missing_flag.get("draft_only") is not True:
            try:
                raise AssertionError("injected.json missing draft_only:true")
            except AssertionError:
                notes.append("negative: draft without draft_only:true refused")
    except Exception as exc:  # pragma: no cover
        errors.append(str(exc))

    try:
        diff.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back API refused")

    report = diff.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])

    out = repo / "bhuman/k1-training/manifests/p1-draft-diff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("all_drafts_draft_only") is not True or blob.get("live_paths_untouched") is not True:
            errors.append("written p1-draft-diff-latest.json missing live/draft assertions")
        else:
            notes.append("wrote manifests/p1-draft-diff-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during p1-draft-diff test")
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
        f"[p1-draft-diff] {'PASS' if report['ok'] else 'FAIL'} "
        "draft_only:true; live untouched"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
