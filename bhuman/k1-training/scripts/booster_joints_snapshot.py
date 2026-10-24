"""Read-only WalkingEngine boosterJoints snapshot vs joint_map.

If official source is missing: honest SKIP and empty names (do not fabricate).
If present: extract 12 legs and compare to joint_map. Walk-13 appends
gait_frequency; that name is NOT invented from boosterJoints.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
if str(_SWITCHER) not in sys.path:
    sys.path.insert(0, str(_SWITCHER))

from joint_map_contract import (  # noqa: E402
    GAIT_FREQUENCY_SLOT,
    WALK_ACTION_MAP,
    WALK_LEG_JOINTS,
    extract_joints_block,
)

TRAINABLE = False
WRITE_YAML = False
SNAPSHOT_REL = "bhuman/k1-training/manifests/booster-joints-walk13-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"

SOURCE_CANDIDATES = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
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
    raise RuntimeError(f"boosterJoints snapshot is read-only; must not write {path or 'K1.yaml'}")


def locate_walking_engine(repo: Path) -> tuple[Path | None, str | None]:
    for rel in SOURCE_CANDIDATES:
        path = repo / rel
        if path.is_file() and path.stat().st_size > 0:
            return path, rel
    return None, None


def _skip_snapshot(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "source": None,
        "booster_joints": [],
        "walk13": None,
        "matches_joint_map": None,
        "fabricated": False,
        "note": "do not invent joint names when source is missing",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("boosterJoints snapshot leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    path, rel = locate_walking_engine(repo)
    if path is None:
        return _skip_snapshot("WalkingEngine.cpp / boosterJoints source not found")
    text = path.read_text(encoding="utf-8")
    try:
        names = extract_joints_block(text, "boosterJoints")
    except ValueError as exc:
        return _skip_snapshot(f"boosterJoints block unreadable: {exc}")
    if not names:
        return _skip_snapshot("boosterJoints block empty; not fabricating names")
    matches = names == list(WALK_LEG_JOINTS)
    # gait_frequency is a semantic 13th slot, never read from boosterJoints.
    walk13 = list(names) + [GAIT_FREQUENCY_SLOT]
    if not matches:
        raise AssertionError(
            f"boosterJoints {names} drifted off joint_map {list(WALK_LEG_JOINTS)}"
        )
    if walk13 != list(WALK_ACTION_MAP):
        raise AssertionError("walk13 = 12 boosterJoints + gait_frequency drifted off joint_map")
    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_actions: 13" not in yaml_text or "num_observations: 344" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "source": rel,
        "booster_joints": names,
        "booster_joints_len": len(names),
        "walk13": walk13,
        "matches_joint_map": True,
        "fabricated": False,
        "note": "boosterJoints is 12 legs; slot 12 is gait_frequency, not a 13th motor",
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
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("boosterJoints snapshot imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated boosterJoints names")
        if snap.get("booster_joints"):
            errors.append("SKIP snapshot must not invent booster_joints names")
    elif snap:
        notes.append(f"source {snap.get('source')}: {len(snap.get('booster_joints') or [])} legs")
        notes.append("matches joint_map; walk13 appends gait_frequency (not a motor)")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before != after:
            errors.append("K1.yaml changed during boosterJoints snapshot")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
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
        print(f"[booster-joints] FAIL {exc}")
        return 1
    tag = snap.get("status") or "FAIL"
    print(f"[booster-joints] {tag} walk 344→13; wrote {path}")
    if snap.get("skipped"):
        print(f"[note] SKIP {snap.get('reason')}; no fabricated names")
    else:
        print("[note] boosterJoints 12 legs + gait_frequency; matches joint_map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
