"""Read-only GetUpEngine 22-D joint-order snapshot.

Extracts upperBodyJoints + lowerBodyJoints from official GetUpEngine.cpp.
Cross-asserts kick_standup_joint_map / STANDUP_ACTION_MAP.
Missing source → honest SKIP and empty names (do not fabricate).
T1 getUpEngine.cfg is not the K1 22-D map.
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
    GETUP_ENGINE_REL,
    STANDUP_ACTION_MAP,
    extract_joints_block,
    extract_official_standup_map,
)
from kick_standup_joint_map import STANDUP_SLOT12_NAME, extract_maps  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
SNAPSHOT_REL = "bhuman/k1-training/manifests/getup-engine-standup22-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
T1_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/T1/getUpEngine.cfg"

SOURCE_CANDIDATES = (GETUP_ENGINE_REL,)


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
        f"GetUpEngine snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def locate_getup_engine(repo: Path) -> tuple[Path | None, str | None]:
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
        "upper_body": [],
        "lower_body": [],
        "standup22": [],
        "slot12": None,
        "matches_joint_map": None,
        "matches_kick_standup": None,
        "fabricated": False,
        "note": "do not invent GetUpEngine joint names when source is missing",
        "trainable": False,
        "write_yaml": False,
        "standup": "73→22",
        "walk": "344→13",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("GetUpEngine snapshot leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    path, rel = locate_getup_engine(repo)
    if path is None:
        return _skip_snapshot("GetUpEngine.cpp source not found")
    text = path.read_text(encoding="utf-8")
    try:
        upper = extract_joints_block(text, "upperBodyJoints")
        lower = extract_joints_block(text, "lowerBodyJoints")
        names = extract_official_standup_map(text)
    except (ValueError, AssertionError) as exc:
        return _skip_snapshot(f"GetUpEngine joint blocks unreadable: {exc}")
    if not names:
        return _skip_snapshot("GetUpEngine joint blocks empty; not fabricating names")
    if names != list(STANDUP_ACTION_MAP):
        raise AssertionError(
            f"GetUpEngine 22-D drifted off joint_map: {names}"
        )
    if names[12] != STANDUP_SLOT12_NAME:
        raise AssertionError(f"GetUpEngine[12] drifted off {STANDUP_SLOT12_NAME}")
    if upper + lower != names:
        raise AssertionError("upper+lower must equal GetUpEngine 22-D map")

    cross = extract_maps(repo)
    kick_names = (cross.get("standup") or {}).get("names") or []
    matches_kick = kick_names == names if kick_names else None
    if kick_names and not matches_kick:
        raise AssertionError("GetUpEngine 22-D drifted off kick_standup_joint_map")

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_actions: 13" not in yaml_text or "num_observations: 344" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    t1_cfg = repo / T1_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "source": rel,
        "upper_body": upper,
        "upper_len": len(upper),
        "lower_body": lower,
        "lower_len": len(lower),
        "standup22": names,
        "standup22_len": len(names),
        "slot12": names[12],
        "slot12_is_motor": True,
        "matches_joint_map": True,
        "matches_kick_standup": matches_kick,
        "t1_cfg_present": t1_cfg.is_file(),
        "t1_cfg_is_k1_standup22": False,
        "fabricated": False,
        "note": (
            "GetUpEngine 22 = 10 upper + 12 legs; [12]=lHipYaw motor; "
            "T1 getUpEngine.cfg is not the K1 map"
        ),
        "trainable": False,
        "write_yaml": False,
        "standup": "73→22",
        "fast_standup": "72→22",
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


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("GetUpEngine snapshot imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated GetUpEngine names")
        if snap.get("standup22") or snap.get("upper_body") or snap.get("lower_body"):
            errors.append("SKIP snapshot must not invent standup22 names")
    elif snap:
        notes.append(
            f"source {snap.get('source')}: {snap.get('standup22_len')} joints; "
            f"[12]={snap.get('slot12')}"
        )
        notes.append("matches joint_map + kick_standup_joint_map")

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
            errors.append("K1.yaml changed during GetUpEngine snapshot")
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
        "standup": "73→22",
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
        print(f"[getup-engine] FAIL {exc}")
        return 1
    tag = snap.get("status") or "FAIL"
    print(f"[getup-engine] {tag} standup 73→22; wrote {path}")
    if snap.get("skipped"):
        print(f"[note] SKIP {snap.get('reason')}; no fabricated names")
    else:
        print("[note] GetUpEngine 22 = 10 upper + 12 legs; [12]=lHipYaw motor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
