#!/usr/bin/env python3
"""Official walk-*-stability-v1 audit: keys + baseline; draft-only excluded."""
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
    rel = "bhuman/k1-training/scripts/walk_stability_presets_audit.py"
    spec = importlib.util.spec_from_file_location(
        "walk_stability_presets_audit_test", repo / rel
    )
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
        errors.append("walk stability audit imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("walk stability audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_audit_frozen(repo)
        notes.append("assert_audit_frozen: official pair; draft-only excluded")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    official = data.get("official") or []
    if official != [
        "walk-reference-stability-v1.json",
        "walk-critic-stability-v1.json",
    ]:
        errors.append(f"official preset set drifted: {official}")
    else:
        notes.append("official walk-reference + walk-critic stability-v1")

    presets = {row["name"]: row for row in (data.get("presets") or [])}
    ref = presets.get("walk-reference-stability-v1.json") or {}
    if ref.get("reference_mean_penalty") != 1.0:
        errors.append("reference_mean_penalty baseline drifted off 1.0")
    else:
        notes.append("reference_mean_penalty=1.0 on walk-reference-stability-v1")
    critic = presets.get("walk-critic-stability-v1.json") or {}
    if critic.get("reference_mean_penalty") is not None:
        errors.append("critic preset must not carry reference_mean_penalty")
    elif critic:
        notes.append("critic preset has no reference_mean_penalty (honest)")

    if data.get("draft_pollution") or data.get("stability_script_reads_draft"):
        errors.append("draft-only polluted official presets")
    else:
        notes.append("draft-only did not pollute official presets / run_walk_stability.sh")

    try:
        mod.refuse_draft_pollution(
            '{"draft_only": true, "note": "walk-p1-factors"}',
            "tampered-official",
        )
        errors.append("draft_only official text must raise")
    except ValueError:
        notes.append("negative: draft_only / walk-p1-factors in official refused")

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
        errors.append("K1.yaml changed during walk stability audit")
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
        f"[walk-stability] {'PASS' if report['ok'] else 'FAIL'} "
        "official presets; draft-only excluded"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
