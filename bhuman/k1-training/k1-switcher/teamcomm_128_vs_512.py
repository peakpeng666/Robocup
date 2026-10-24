"""Official TeamMessageContainer 128 B vs HSL GameController 512 B.

Different purposes. Do not mix the numbers:
- official 128 = B-Human rule-book `TeamMessageContainer::data[N]`
- HSL 512 = GameController team-message *budget* (max payload)
Must not overwrite official 128 with 512, and must not label 128 as
"HSL budget already satisfied". Bandwidth without robot/WLAN stays SKIP.
Never writes K1.yaml. TRAINABLE=false.

See TEAMCOMM-128-VS-512.md and compressed_teamcomm_shape.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compressed_teamcomm_shape import (  # noqa: E402
    CONTAINER_RELS,
    HSL_BUDGET_B,
    extract_container_bytes,
    locate_first,
)
from teamcomm_budget import probe_bandwidth, refuse_fake_bandwidth_pass  # noqa: E402

TRAINABLE = False
IMPLEMENTED = False
WRITE_YAML = False
OFFICIAL_CONTAINER_B = 128
DOC_REL = "bhuman/docs/TEAMCOMM-128-VS-512.md"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/teamcomm-128-vs-512-latest.json"
DOC_NEEDLES = (
    "128",
    "512",
    "用途不同",
    "不得混用",
    "不得用 512 覆盖",
    "不得把 128 误标",
    "带宽",
    "SKIP",
    "344→13",
)
CONTAINER_RE = re.compile(r"char\s+data\[(\d+)\]")


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"128-vs-512 contrast is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_mix_128_512(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("128/512 claim must be a mapping")
    if claim.get("overwrite_128_with_512") or claim.get("official_container_b") == HSL_BUDGET_B:
        raise ValueError("must not overwrite official TeamMessageContainer 128 with HSL 512")
    if claim.get("hsl_budget_b") == OFFICIAL_CONTAINER_B or claim.get("label_128_as_hsl_satisfied"):
        raise ValueError("must not label official 128 as HSL 512 budget already satisfied")
    if claim.get("same_number") or claim.get("mix") or claim.get("interchangeable"):
        raise ValueError("128 and 512 have different purposes; do not mix the numbers")
    if claim.get("bandwidth_pass_without_wlan"):
        raise ValueError("bandwidth measure must stay SKIP without robot/WLAN")


def recorded_contrast(repo: Path) -> dict[str, Any]:
    doc = repo / DOC_REL
    if not doc.is_file():
        raise AssertionError(f"missing {DOC_REL}")
    text = doc.read_text(encoding="utf-8")
    missing = [needle for needle in DOC_NEEDLES if needle not in text]
    if missing:
        raise AssertionError(f"{DOC_REL} missing anchors {missing}")
    if "覆盖官方 128" in text and "不得用 512 覆盖" not in text:
        raise AssertionError("doc must forbid overwriting official 128 with 512")
    return {
        "doc": DOC_REL,
        "hsl_budget_b": HSL_BUDGET_B,
        "official_container_b": OFFICIAL_CONTAINER_B,
        "same_number": False,
        "purposes": {
            "128": "B-Human TeamMessageContainer rule-book data[N]",
            "512": "HSL GameController team-message budget (max)",
        },
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        raise AssertionError("128-vs-512 contrast leaked flags")
    repo = _repo(repo)
    contrast = recorded_contrast(repo)
    container, container_rel = locate_first(repo, CONTAINER_RELS)
    official_b = None
    if container is None:
        status = "SKIP"
        reason = "TeamMessageContainer.h not found; not fabricating 128"
    else:
        official_b = extract_container_bytes(container.read_text(encoding="utf-8"))
        if official_b is None:
            status = "SKIP"
            reason = "TeamMessageContainer data[N] unreadable; not fabricating size"
        else:
            status = "PASS"
            reason = None
            if official_b != OFFICIAL_CONTAINER_B:
                raise AssertionError(
                    f"official container drifted to data[{official_b}]; expected 128"
                )
            if official_b == HSL_BUDGET_B:
                raise AssertionError("official container must not silently equal HSL 512")

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    bandwidth = probe_bandwidth()
    if bandwidth.get("status") == "PASS":
        raise AssertionError("bandwidth measure must stay SKIP without robot/WLAN")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "skipped": status == "SKIP",
        "reason": reason,
        "sources": {"container": container_rel, "doc": DOC_REL},
        "hsl_budget_b": HSL_BUDGET_B,
        "official_container_b": official_b,
        "same_number": False,
        "purposes": contrast["purposes"],
        "overwrite_128_with_512": False,
        "label_128_as_hsl_satisfied": False,
        "teammate_into_344": False,
        "bandwidth": bandwidth,
        "fabricated": False,
        "note": (
            "HSL 512 is a budget ceiling; official data[128] is the on-robot container. "
            "Do not mix. Do not claim 128 satisfies 512. Bandwidth SKIP without WLAN."
        ),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_contrast_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        raise AssertionError("128-vs-512 leaked flags")
    if snap.get("hsl_budget_b") != HSL_BUDGET_B:
        raise AssertionError("HSL budget drifted off 512")
    if snap.get("same_number") or snap.get("overwrite_128_with_512"):
        raise AssertionError("128/512 contrast drifted")
    if not snap.get("skipped") and snap.get("official_container_b") != OFFICIAL_CONTAINER_B:
        raise AssertionError("official container must stay 128 when source is present")
    try:
        refuse_mix_128_512({"overwrite_128_with_512": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_mix_128_512 must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("128-vs-512 contrast imported Gym")
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        errors.append("128-vs-512 flags leaked")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = assert_contrast_frozen(repo)
        notes.append("assert_contrast_frozen: 128 ≠ 512; purposes distinct")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: official size not fabricated")
    elif snap:
        notes.append(
            f"official container {snap.get('official_container_b')} B; "
            f"HSL budget {snap.get('hsl_budget_b')} B; not the same number"
        )

    live = probe_bandwidth()
    if live.get("status") == "PASS":
        errors.append("bandwidth must not PASS without robot/WLAN")
    else:
        notes.append("bandwidth measure SKIP (no robot / WLAN)")

    for claim, label in (
        ({"overwrite_128_with_512": True}, "overwrite 128 with 512"),
        ({"official_container_b": 512}, "official_container=512"),
        ({"label_128_as_hsl_satisfied": True}, "128 labeled HSL-satisfied"),
        ({"hsl_budget_b": 128}, "HSL budget=128"),
        ({"mix": True}, "mix 128/512"),
    ):
        try:
            refuse_mix_128_512(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_fake_bandwidth_pass({"status": "PASS", "kind": "wlan"})
        errors.append("fake WLAN PASS must raise")
    except ValueError:
        notes.append("negative: fake WLAN PASS refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before != after:
            errors.append("K1.yaml changed during 128-vs-512 contrast")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped") or live.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[128-vs-512] FAIL {exc}")
        return 1
    print(
        f"[128-vs-512] {snap.get('status')} official {snap.get('official_container_b')} "
        f"≠ HSL {snap.get('hsl_budget_b')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
