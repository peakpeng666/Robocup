#!/usr/bin/env python3
"""Walk obs assembly 10×32+24=344; refuse reactive concat; no fabricate."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from obs_assembly import (  # noqa: E402
    DOC_REL,
    formula,
    refuse_reactive_concat_as_walk,
    assert_obs_assembly_frozen,
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
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("obs assembly test imported Gym")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        frozen = assert_obs_assembly_frozen(repo)
        notes.append(f"assembly {frozen.get('formula')} sources present")
        if frozen.get("via_reactive"):
            errors.append("assembly must not mark via_reactive")
        else:
            notes.append("deploy default official walk; not reactive concat")
        if frozen.get("sources", {}).get("history_buffer_skip"):
            notes.append(
                frozen["sources"].get("history_buffer_note")
                or "WalkingEngine.h missing; not fabricating"
            )
        else:
            notes.append("WalkingEngine.h RingBuffer<HistoryData, 10>")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))

    if formula() != "10×32+24=344":
        errors.append(f"formula drifted: {formula()}")

    if not (repo / DOC_REL).is_file():
        errors.append(f"missing {DOC_REL}")
    else:
        text = (repo / DOC_REL).read_text(encoding="utf-8")
        for needle in ("344→13", "10×32+24", "不经", "k1-reactive", "WalkingEngine"):
            if needle not in text:
                errors.append(f"{DOC_REL} missing {needle}")
        else:
            notes.append("OBS-ASSEMBLY-344.md: deploy stays official walk")

    for bad in (
        {"via_reactive": True, "obs": 344},
        {"obs": 64},
        {"obs": 3200},
        {"latent_into_344": True},
        {"obs": 59},
    ):
        try:
            refuse_reactive_concat_as_walk(bad)
            errors.append(f"must refuse {bad}")
        except ValueError:
            notes.append(f"negative: refused {bad}")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during obs-assembly test")
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
        f"[obs-assembly] {'PASS' if report['ok'] else 'FAIL'} "
        "10×32+24=344; not reactive concat"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
