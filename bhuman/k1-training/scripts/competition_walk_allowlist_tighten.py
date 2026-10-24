"""Tighten CompetitionWalk vs Default allowlist; forbid silent cfg edits.

Deepens competition_walk_diff without replacing it:

  * Documents the frozen 14-key allowed diff set
  * Pins CompetitionWalk / 11v11 walkingEngine.cfg hashes
  * Silent Competition cfg edits FAIL
  * Net slot stays 344→13 / K1_walk.onnx
  * Overlay PASS is not apply_to_live / competition-ready gait

Does not import walk_stability_preset_inventory.
Does not write K1.yaml / walkingEngine.cfg.

Runnable: python3 bhuman/k1-training/scripts/competition_walk_allowlist_tighten.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from competition_walk_diff import (  # noqa: E402
    ALLOWED_COMPETITION_DIFFS,
    COMP11_WALK_REL,
    COMP_WALK_REL,
    DEFAULT_WALK_REL,
    assert_competition_diff_frozen,
    refuse_competition_diff_net_slot,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/competition-walk-allowlist-tighten-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
DEFAULT_WALK_SHA256 = "c6fc603b80ee4347a17739ff592d1d9825b04da3987214b309450b9f1feb4611"
COMPETITION_WALK_SHA256 = "a0a8af819ada04442de3dfb73dba5895bdd7c7ff577a13624f55ccddbf19f10e"

CHECKLIST = (
    "allowlist_documented_14",
    "competition_equals_11v11",
    "net_slot_stays_344",
    "hashes_frozen",
    "silent_edit_refused",
)
DOC_NEEDLES = (
    "competition_walk_allowlist_tighten",
    "14-key",
    "TRAINABLE=false",
    "gap_closed=false",
    "silent Competition",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "field_ready=true",
    "competition_ready=true",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"Competition allowlist tighten is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"Competition allowlist tighten is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_silent_competition_cfg_edit(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-competition-cfg-edit claim must be a mapping")
    if (
        claim.get("silent_competition_cfg_edit")
        or claim.get("edit_competition_cfg")
        or claim.get("write_cfg") is True
        or claim.get("apply_to_live") is True
        or claim.get("hash_drift_ok")
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("edited") or claim.get("silent_edit"))
        )
    ):
        raise ValueError(
            "CompetitionWalk / 11v11 walkingEngine.cfg is hash-pinned; "
            "silent edits outside the documented 14-key allowlist are forbidden"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("Competition allowlist tighten leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    frozen = assert_competition_diff_frozen(repo)
    if frozen.get("status") == "SKIP":
        raise AssertionError("Competition allowlist tighten must not SKIP when cfgs exist")
    if frozen.get("net_slot_diff") or frozen.get("observed_count") != 14:
        raise AssertionError("Competition allowlist drifted off 14 keys / net slot")
    if not frozen.get("competition_equals_11v11"):
        raise AssertionError("CompetitionWalk and 11v11 must stay identical")
    if set(ALLOWED_COMPETITION_DIFFS) != {
        (row["key"], row["default"], row["competition"])
        for row in (frozen.get("diffs") or [])
    }:
        raise AssertionError("documented 14-key allowlist drifted")

    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    comp11_path = repo / COMP11_WALK_REL
    default_sha = hashlib.sha256(default_path.read_bytes()).hexdigest()
    comp_sha = hashlib.sha256(comp_path.read_bytes()).hexdigest()
    comp11_sha = hashlib.sha256(comp11_path.read_bytes()).hexdigest()
    if default_sha != DEFAULT_WALK_SHA256:
        raise AssertionError("Default walkingEngine.cfg hash drifted (silent edit?)")
    if comp_sha != COMPETITION_WALK_SHA256 or comp11_sha != COMPETITION_WALK_SHA256:
        raise AssertionError("Competition walkingEngine.cfg hash drifted (silent edit forbidden)")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    allowlist = [
        {"key": key, "default": left, "competition": right}
        for key, left, right in sorted(ALLOWED_COMPETITION_DIFFS)
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/competition_walk_allowlist_tighten.py",
        "checklist": list(CHECKLIST),
        "allowlist": allowlist,
        "allowed_count": 14,
        "competition_equals_11v11": True,
        "net_slot_diff": False,
        "silent_competition_cfg_edit": False,
        "walk": "344→13",
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "field_ready": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "CompetitionWalk / 11v11 vs Default stay the documented 14-key allowlist; "
            "hashes pinned; silent Competition cfg edits forbidden; "
            "net slot 344→13; overlay PASS ≠ apply_to_live"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "default_sha256": default_sha,
        "competition_sha256": comp_sha,
        "competition_11v11_sha256": comp11_sha,
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_competition_walk_allowlist_tighten_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("Competition allowlist tighten leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"Competition allowlist checklist drifted: {snap.get('checklist')}")
    if snap.get("allowed_count") != 14 or snap.get("net_slot_diff"):
        raise AssertionError("allowlist count / net slot drifted")
    if snap.get("silent_competition_cfg_edit") or snap.get("apply_to_live"):
        raise AssertionError("silent Competition edit / apply_to_live leaked")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("Competition allowlist leaked ready_gpu / would_train / GAP-closed")
    if snap.get("competition_sha256") != COMPETITION_WALK_SHA256:
        raise AssertionError("Competition hash pin drifted")
    try:
        refuse_silent_competition_cfg_edit(
            {
                "silent_competition_cfg_edit": True,
                "edit_competition_cfg": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_silent_competition_cfg_edit must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("Competition allowlist tighten imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    comp11_path = repo / COMP11_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    before_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest() if comp11_path.is_file() else ""
    try:
        snap = assert_competition_walk_allowlist_tighten_frozen(repo)
        notes.append("assert_competition_walk_allowlist_tighten_frozen: 14-key pin")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("documented 14-key Competition vs Default allowlist; hashes frozen")
        notes.append("net slot still 344→13; CompetitionWalk == 11v11")
        notes.append("silent Competition cfg edits forbidden")

    try:
        refuse_silent_competition_cfg_edit(
            {"status": "PASS", "edited": True, "this_pin": True}
        )
        errors.append("silent_competition_cfg_edit must raise")
    except ValueError:
        notes.append("negative: silent Competition cfg edit refused")
    try:
        refuse_competition_diff_net_slot({"net_slot_diff": True, "numInput": 365})
        errors.append("refuse_competition_diff_net_slot must raise")
    except ValueError:
        notes.append("negative: Competition net-slot drift refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(comp_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of Competition walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (default_path, before_default, "Default walkingEngine.cfg"),
        (comp_path, before_comp, "CompetitionWalk walkingEngine.cfg"),
        (comp11_path, before_comp11, "CompetitionWalk11v11 walkingEngine.cfg"),
    ):
        if path.is_file() and before:
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during Competition allowlist tighten")
            else:
                notes.append(f"official {label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "silent_competition_cfg_edit": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[comp-allowlist] FAIL {exc}")
        return 1
    print(
        f"[comp-allowlist] {snap.get('status')} "
        f"14-key allowlist pinned; silent Competition edits forbidden; "
        f"wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
