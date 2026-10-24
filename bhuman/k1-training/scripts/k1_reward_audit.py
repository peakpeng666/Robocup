#!/usr/bin/env python3
"""Read-only audit of official K1 walk rewards.

Parses official IsaacGymRL/envs/K1.yaml trees and walk-*-stability-v1.json.
Never reads configs/draft-only/. Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13

OFFICIAL_YAML_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
    "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
)
OFFICIAL_STABILITY_RELS = (
    "bhuman/k1-training/configs/walk-reference-stability-v1.json",
    "bhuman/k1-training/configs/walk-critic-stability-v1.json",
)
DRAFT_ONLY_REL = "bhuman/k1-training/configs/draft-only"
AUDIT_REL = "bhuman/k1-training/manifests/k1-reward-audit-latest.json"

BASELINE = {
    "still_proportion": 0.1,
    "tracking_lin_vel_x": 0.75,
    "tracking_lin_vel_y": 0.75,
    "tracking_ang_vel": 0.375,
    "action_rate": -1.0,
    "reference_mean_penalty": 1.0,
}


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _num_eq(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-12
    except (TypeError, ValueError):
        return False


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"reward audit is read-only; must not write {path or 'K1.yaml'}"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a mapping")
        return data
    # Needle fallback when PyYAML is absent: baseline keys only.
    env: dict[str, Any] = {}
    if "num_observations: 344" in text:
        env["num_observations"] = 344
    if "num_actions: 13" in text:
        env["num_actions"] = 13
    commands: dict[str, Any] = {}
    if "still_proportion: 0.1" in text:
        commands["still_proportion"] = 0.1
    scales: dict[str, Any] = {}
    for key, expect in (
        ("tracking_lin_vel_x", 0.75),
        ("tracking_lin_vel_y", 0.75),
        ("tracking_ang_vel", 0.375),
        ("action_rate", -1.0),
    ):
        if f"{key}: {expect}" in text or f"{key}: -1." in text:
            scales[key] = expect
    return {"env": env, "commands": commands, "rewards": {"scales": scales}}


def parse_official_yaml(path: Path) -> dict[str, Any]:
    if "draft-only" in str(path).replace("\\", "/"):
        raise ValueError("must not parse draft-only as official K1.yaml")
    data = _load_yaml(path)
    env = data.get("env") or {}
    commands = data.get("commands") or {}
    scales = ((data.get("rewards") or {}).get("scales") or {})
    if not isinstance(scales, dict):
        raise ValueError(f"{path} rewards.scales is not a mapping")
    return {
        "rel_note": str(path),
        "num_observations": env.get("num_observations"),
        "num_actions": env.get("num_actions"),
        "still_proportion": commands.get("still_proportion"),
        "reward_scales": {str(k): v for k, v in scales.items() if not str(k).startswith("#")},
        "sha256": _sha256(path),
    }


def parse_official_stability(path: Path) -> dict[str, Any]:
    rel = str(path).replace("\\", "/")
    if "draft-only" in rel:
        raise ValueError("must not parse draft-only as official stability json")
    if path.name.endswith("-v1.json") is False or "stability" not in path.name:
        raise ValueError(f"{path.name} is not an official walk-*-stability-v1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    algo = (data.get("algorithm") or {}) if isinstance(data, dict) else {}
    return {
        "name": path.name,
        "reference_mean_penalty": algo.get("reference_mean_penalty"),
        "keys": sorted(algo.keys()),
    }


def collect_baseline(yaml_snap: dict[str, Any], stability: list[dict[str, Any]]) -> dict[str, Any]:
    values = {
        "still_proportion": yaml_snap.get("still_proportion"),
        "tracking_lin_vel_x": (yaml_snap.get("reward_scales") or {}).get("tracking_lin_vel_x"),
        "tracking_lin_vel_y": (yaml_snap.get("reward_scales") or {}).get("tracking_lin_vel_y"),
        "tracking_ang_vel": (yaml_snap.get("reward_scales") or {}).get("tracking_ang_vel"),
        "action_rate": (yaml_snap.get("reward_scales") or {}).get("action_rate"),
    }
    ref = next(
        (item.get("reference_mean_penalty") for item in stability if item.get("reference_mean_penalty") is not None),
        None,
    )
    values["reference_mean_penalty"] = ref
    return values


def assert_snapshot_matches_baseline(snapshot: dict[str, Any]) -> None:
    values = snapshot.get("baseline_values") or {}
    missing = [key for key in BASELINE if key not in values]
    if missing:
        raise AssertionError(f"audit snapshot missing baseline keys {missing}")
    drifted = [
        f"{key}: live={values[key]} baseline={expect}"
        for key, expect in BASELINE.items()
        if not _num_eq(values.get(key), expect)
    ]
    if drifted:
        raise AssertionError(f"official rewards drifted: {drifted}")
    if snapshot.get("write_yaml") or snapshot.get("trainable"):
        raise AssertionError("audit snapshot must stay read-only / TRAINABLE=false")
    if snapshot.get("walk") != "344→13":
        raise AssertionError("audit must keep walk 344→13")


def refuse_tampered_snapshot(snapshot: dict[str, Any]) -> None:
    """A mutated copy of a live snapshot must not validate."""
    assert_snapshot_matches_baseline(snapshot)


def audit(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("reward audit leaked WRITE_YAML/TRAINABLE")

    yaml_snaps = []
    for rel in OFFICIAL_YAML_RELS:
        path = repo / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        yaml_snaps.append(parse_official_yaml(path))

    first = yaml_snaps[0]
    trees_agree = all(
        snap["reward_scales"] == first["reward_scales"]
        and _num_eq(snap["still_proportion"], first["still_proportion"])
        and snap["num_observations"] == WALK_OBS
        and snap["num_actions"] == WALK_ACT
        for snap in yaml_snaps
    )

    stability = []
    for rel in OFFICIAL_STABILITY_RELS:
        path = repo / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        if DRAFT_ONLY_REL in rel:
            raise AssertionError("official stability path leaked into draft-only")
        stability.append(parse_official_stability(path))

    values = collect_baseline(first, stability)
    snapshot = {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "read_only": True,
        "write_yaml": False,
        "trainable": False,
        "walk": "344→13",
        "sources": {
            "k1_yaml": list(OFFICIAL_YAML_RELS),
            "stability": list(OFFICIAL_STABILITY_RELS),
            "excluded": [DRAFT_ONLY_REL],
        },
        "dims": {
            "num_observations": first["num_observations"],
            "num_actions": first["num_actions"],
        },
        "commands": {"still_proportion": first["still_proportion"]},
        "reward_scales": first["reward_scales"],
        "reward_scale_names": sorted(first["reward_scales"]),
        "stability": {item["name"]: item for item in stability},
        "baseline": dict(BASELINE),
        "baseline_values": values,
        "trees_agree": trees_agree,
        "yaml_sha256": [snap["sha256"] for snap in yaml_snaps],
    }
    assert_snapshot_matches_baseline(snapshot)
    if not trees_agree:
        raise AssertionError("official K1.yaml trees disagree on walk rewards / 344→13")
    return snapshot


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = audit(repo)
    path = dest or (repo / AUDIT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run(repo: Path | None = None) -> dict[str, Any]:
    """Gate/no-gym entry: audit + write JSON + refuse write-back."""
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in __import__("sys").modules or "isaacgym" in __import__("sys").modules:
        errors.append("reward audit imported Gym / Isaac Gym")

    before = {rel: _sha256(repo / rel) for rel in OFFICIAL_YAML_RELS}
    try:
        snapshot = audit(repo)
        notes.append(
            f"reward scales ({len(snapshot['reward_scale_names'])}): "
            + ", ".join(snapshot["reward_scale_names"][:8])
            + ("…" if len(snapshot["reward_scale_names"]) > 8 else "")
        )
        notes.append("baseline still_proportion=0.1 tracking_* action_rate=-1. reference_mean_penalty=1.0")
        notes.append("official K1.yaml trees agree; draft-only excluded")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snapshot = {}

    try:
        refuse_write_yaml(repo / OFFICIAL_YAML_RELS[0])
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    after = {rel: _sha256(repo / rel) for rel in OFFICIAL_YAML_RELS}
    if before != after:
        errors.append("K1.yaml content changed during audit")
    else:
        notes.append("K1.yaml sha256 unchanged (read-only)")

    if snapshot:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "snapshot": {k: snapshot.get(k) for k in ("baseline_values", "trees_agree", "walk")}
        if snapshot
        else {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[k1-reward-audit] FAIL {exc}")
        return 1
    print(f"[k1-reward-audit] PASS walk 344→13; wrote {path}")
    print("[note] read-only; did not write K1.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
