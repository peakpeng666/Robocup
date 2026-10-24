#!/usr/bin/env python3
"""Selfcheck markdown renderer: reads JSON; short PASS/SKIP/WARN; no YAML write."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_selfcheck_summary import (  # noqa: E402
    TRAINABLE,
    WRITE_YAML,
    collect,
    refuse_write_yaml,
    render_markdown,
    write_summary,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    skipped = False

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("selfcheck summary renderer imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("renderer flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    script = repo / "bhuman/k1-training/scripts/render_selfcheck_summary.py"
    if not script.is_file():
        errors.append("missing render_selfcheck_summary.py")
    else:
        notes.append("scripts/render_selfcheck_summary.py present")

    bundle = collect(repo)
    if bundle.get("missing_sources"):
        skipped = True
        notes.append(f"selfcheck JSON missing → render SKIP stub: {bundle['missing_sources']}")
    else:
        notes.append("pr4-selfcheck-latest.json readable")

    text = render_markdown(bundle)
    for needle in ("344→13", "PASS", "SKIP", "WARN", "TRAINABLE", "ready_gpu"):
        if needle not in text:
            errors.append(f"rendered markdown missing {needle}")
    if (bundle.get("selfcheck") or {}).get("step_timings"):
        if "各步耗时" not in text or "elapsed_s" not in text:
            errors.append("rendered markdown missing step timings")
        else:
            notes.append("step timings rendered")
    if (bundle.get("selfcheck") or {}).get("verdict") != "FAIL" and "先看" in text:
        errors.append("PASS summary must stay quiet (no 先看)")
    else:
        notes.append("PASS summary has no FAIL 先看")
    fail_md = render_markdown(
        {
            "selfcheck": {
                "generated_utc": "2026-10-24T00:00:00+00:00",
                "verdict": "FAIL",
                "walk": "344→13",
                "trainable": False,
                "ready_gpu": False,
                "failed_step": "test_command_schedule_audit.py",
                "fail_hint": (
                    "先看 K1.yaml commands: 与 draft A_command_schedule "
                    "是否被当成已应用 → bhuman/k1-training/scripts/command_schedule_audit.py"
                ),
                "fail_look": "bhuman/k1-training/scripts/command_schedule_audit.py",
                "steps": ["test_command_schedule_audit.py"],
            },
            "gate": {},
            "gpu": {},
            "inventory": {},
            "joints": {},
            "missing_sources": [],
        }
    )
    if "先看" not in fail_md or "command_schedule_audit.py" not in fail_md:
        errors.append("FAIL summary must print 先看 file/test")
    else:
        notes.append("FAIL summary prints 先看 locator")
    if "长篇" in text or len(text) > 16000:
        errors.append("summary grew into a long survey")
    else:
        notes.append("short PASS/SKIP/WARN markdown (not a new survey)")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = write_summary(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
        written = out.read_text(encoding="utf-8")
        if "344→13" not in written or "PASS" not in written:
            errors.append("written PR4-SELFCHECK-LATEST.md missing anchors")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during selfcheck summary render")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "skipped": skipped,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[selfcheck-md] {'PASS' if report['ok'] else 'FAIL'} "
        "PASS/SKIP/WARN summary; no YAML write"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
