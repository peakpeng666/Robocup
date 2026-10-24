#!/usr/bin/env python3
"""CompressedTeamCommunication shape: 512 HSL / official container; not into 344."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compressed_teamcomm_shape import (  # noqa: E402
    HSL_BUDGET_B,
    IMPLEMENTED,
    TRAINABLE,
    WRITE_YAML,
    assert_shape_frozen,
    extract_snapshot,
    probe_bandwidth,
    refuse_fake_bandwidth_pass,
    refuse_oversize_vs_hsl,
    refuse_oversize_vs_official,
    refuse_teamcomm_into_344,
    refuse_write_yaml,
    write_snapshot,
    _skip_snapshot,
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
    warnings: list[str] = []
    skipped = False

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("teamcomm shape test imported Gym")
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        errors.append("teamcomm shape flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = assert_shape_frozen(repo)
        notes.append("assert_shape_frozen: stream types; HSL 512; not into 344")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        skipped = True
        if snap.get("stream_types") or snap.get("stream_classes"):
            errors.append("SKIP must not fabricate stream types")
        else:
            notes.append("honest SKIP: empty types, not fabricated")
        warnings.append(str(snap.get("reason") or "source missing"))
    elif snap:
        if snap.get("hsl_budget_b") != HSL_BUDGET_B:
            errors.append("HSL budget drifted off 512")
        else:
            notes.append("HSL GameController budget 512 B")
        official = snap.get("official_container_b")
        if official is None:
            errors.append("found streams must also record official container or SKIP size")
        else:
            notes.append(f"official TeamMessageContainer data[{official}]")
            if official == HSL_BUDGET_B:
                errors.append("do not silently equate official container with HSL 512")
            else:
                notes.append("honest: official container ≠ HSL 512")
        types = snap.get("stream_types") or []
        if "IntegerType" not in types or "FloatType" not in types:
            errors.append("stream type declarations missing IntegerType/FloatType")
        else:
            notes.append(f"parsed {len(types)} CompressedTeamCommunication types")
        if "CompressedTeamCommunicationIn" not in (snap.get("stream_classes") or []):
            errors.append("CompressedTeamCommunicationIn declaration missing")
        if snap.get("schema_status") == "SKIP":
            skipped = True
            notes.append("teamMessage.def schema SKIP (not in checkout)")
        if snap.get("teammate_into_344"):
            errors.append("shape stub must keep teammate_into_344 false")

    skip_blank = _skip_snapshot("unit-test missing source")
    if skip_blank.get("stream_types") or skip_blank.get("official_container_b"):
        errors.append("SKIP helper must not invent types/size")
    else:
        notes.append("SKIP helper leaves types empty")

    try:
        refuse_oversize_vs_hsl(513)
        errors.append("513 B HSL payload must raise")
    except ValueError:
        notes.append("negative: payload >512 B HSL refused")

    official = (snap or extract_snapshot(repo)).get("official_container_b")
    if official:
        try:
            refuse_oversize_vs_official(official + 1, official)
            errors.append("payload above official container must raise")
        except ValueError:
            notes.append(f"negative: payload >{official} B official refused")

    for claim, label in (
        ({"teammate_into_344": True, "obs": 344}, "teammate_into_344"),
        ({"compressed_into_344": True, "obs": 344}, "compressed_into_344"),
        ({"obs": 344, "teamcomm_dim": 8}, "teamcomm_dim on 344"),
    ):
        try:
            refuse_teamcomm_into_344(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    live = probe_bandwidth()
    if live.get("status") == "PASS":
        errors.append("bandwidth must not PASS without robot/WLAN")
    else:
        skipped = True
        notes.append("bandwidth measure SKIP (no robot / WLAN)")

    try:
        refuse_fake_bandwidth_pass({"status": "PASS", "kind": "wlan"})
        errors.append("fake WLAN PASS must raise")
    except ValueError:
        notes.append("negative: fake WLAN PASS refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = write_snapshot(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    out = repo / "bhuman/k1-training/manifests/compressed-teamcomm-shape-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("skipped") and blob.get("stream_types"):
            errors.append("written SKIP snapshot fabricated types")
        elif blob.get("status") == "PASS" and blob.get("teammate_into_344"):
            errors.append("written PASS snapshot must keep teammate out of 344")
        else:
            notes.append("wrote manifests/compressed-teamcomm-shape-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during teamcomm shape test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": skipped,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[teamcomm-shape] {'PASS' if report['ok'] else 'FAIL'} "
        "HSL 512 / official container; not into 344; WLAN SKIP"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
