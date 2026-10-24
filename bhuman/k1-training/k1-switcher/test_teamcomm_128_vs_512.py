#!/usr/bin/env python3
"""Official TeamMessageContainer 128 B vs HSL 512 B: do not mix."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from teamcomm_128_vs_512 import (  # noqa: E402
    DOC_REL,
    HSL_BUDGET_B,
    IMPLEMENTED,
    OFFICIAL_CONTAINER_B,
    TRAINABLE,
    WRITE_YAML,
    assert_contrast_frozen,
    probe_bandwidth,
    refuse_fake_bandwidth_pass,
    refuse_mix_128_512,
    refuse_write_yaml,
    write_snapshot,
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
        errors.append("128-vs-512 test imported Gym")
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        errors.append("128-vs-512 flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = assert_contrast_frozen(repo)
        notes.append("assert_contrast_frozen: 128 ≠ 512; purposes distinct")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        skipped = True
        if snap.get("official_container_b") not in (None, OFFICIAL_CONTAINER_B):
            errors.append("SKIP must not invent a non-128 official size")
        else:
            notes.append("honest SKIP: official size not fabricated")
        warnings.append(str(snap.get("reason") or "source missing"))
    elif snap:
        if snap.get("hsl_budget_b") != HSL_BUDGET_B:
            errors.append("HSL budget drifted off 512")
        else:
            notes.append("HSL GameController budget 512 B")
        official = snap.get("official_container_b")
        if official != OFFICIAL_CONTAINER_B:
            errors.append(f"official container must stay 128 when source is present, got {official}")
        else:
            notes.append("official TeamMessageContainer data[128]")
        if official == HSL_BUDGET_B or snap.get("same_number"):
            errors.append("do not mix official 128 with HSL 512")
        else:
            notes.append("128 and 512 are different purposes")
        if snap.get("overwrite_128_with_512") or snap.get("label_128_as_hsl_satisfied"):
            errors.append("contrast must keep overwrite/label flags false")
        if snap.get("teammate_into_344"):
            errors.append("128-vs-512 must keep teammate_into_344 false")

    doc = repo / DOC_REL
    if not doc.is_file():
        errors.append(f"missing {DOC_REL}")
    else:
        notes.append("TEAMCOMM-128-VS-512.md present")

    for claim, label in (
        ({"overwrite_128_with_512": True}, "overwrite 128 with 512"),
        ({"official_container_b": 512}, "official_container=512"),
        ({"label_128_as_hsl_satisfied": True}, "128 labeled HSL-satisfied"),
        ({"hsl_budget_b": 128}, "HSL budget=128"),
        ({"mix": True}, "mix 128/512"),
        ({"same_number": True}, "same_number"),
        ({"interchangeable": True}, "interchangeable"),
        ({"bandwidth_pass_without_wlan": True}, "bandwidth PASS without WLAN"),
    ):
        try:
            refuse_mix_128_512(claim)
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

    out = repo / "bhuman/k1-training/manifests/teamcomm-128-vs-512-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("overwrite_128_with_512") or blob.get("label_128_as_hsl_satisfied"):
            errors.append("written snapshot mixed 128/512")
        elif blob.get("status") == "PASS" and blob.get("official_container_b") != 128:
            errors.append("written PASS snapshot must record official 128")
        else:
            notes.append("wrote manifests/teamcomm-128-vs-512-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during 128-vs-512 test")
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
        f"[128-vs-512] {'PASS' if report['ok'] else 'FAIL'} "
        "official 128 ≠ HSL 512; not mixed; WLAN SKIP"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
