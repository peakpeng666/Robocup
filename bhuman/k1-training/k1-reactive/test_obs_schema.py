#!/usr/bin/env python3
"""Validate obs-contract-v1.json against frozen walk/reactive dims."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from obs_schema import EXPECTED, check_schema, load_schema  # noqa: E402


def run(repo: Path | None = None) -> dict[str, Any]:
    report = check_schema(repo)
    errors = list(report.get("errors") or [])
    notes = list(report.get("notes") or [])
    data = load_schema(repo)
    walk = (data.get("skills") or {}).get("walk") or {}
    if "344" not in str(walk.get("relation_to_walk_344", "")) and walk.get("obs") != 344:
        errors.append("walk skill must stay the 344 baseline")
    if set(EXPECTED) - set((data.get("skills") or {})):
        errors.append(f"schema skills missing {set(EXPECTED) - set(data.get('skills') or {})}")
    else:
        notes.append("schema lists walk/kick/standup/fast_standup/reactive")
    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[obs-schema] {'PASS' if report['ok'] else 'FAIL'} walk 344 + reactive 64")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
