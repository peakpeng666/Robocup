"""Official walk stability vs draft-only proposed-key diff (read-only).

Compares walk-*-stability-v1.json algorithm keys with
configs/draft-only/*.json proposed_only keys.
Asserts every draft has draft_only:true and is not written into live paths.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False

OFFICIAL_STABILITY_RELS = (
    "bhuman/k1-training/configs/walk-reference-stability-v1.json",
    "bhuman/k1-training/configs/walk-critic-stability-v1.json",
)
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DRAFT_DIR_REL = "bhuman/k1-training/configs/draft-only"
DIFF_REL = "bhuman/k1-training/manifests/p1-draft-diff-latest.json"

LIVE_REWARDS = {
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


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(f"p1 draft diff is read-only; must not write {path or 'K1.yaml'}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a mapping")
    return data


def official_algorithm_keys(repo: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in OFFICIAL_STABILITY_RELS:
        path = repo / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        if "draft-only" in rel:
            raise AssertionError("official stability path leaked into draft-only")
        algo = _load_json(path).get("algorithm") or {}
        if not isinstance(algo, dict):
            raise ValueError(f"{rel} algorithm is not a mapping")
        out[path.name] = dict(algo)
    return out


def iter_draft_json(repo: Path) -> list[Path]:
    root = repo / DRAFT_DIR_REL
    return sorted(path for path in root.glob("*.json") if path.is_file())


def collect_draft_proposed(data: dict[str, Any]) -> dict[str, Any]:
    proposed: dict[str, Any] = {}
    for name, factor in (data.get("factors") or {}).items():
        block = (factor or {}).get("proposed_only") or {}
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            proposed[f"{name}.{key}"] = value
            proposed.setdefault(str(key), value)
    return proposed


def assert_drafts_draft_only(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    drafts = iter_draft_json(repo)
    if not drafts:
        raise ValueError("draft-only directory has no JSON drafts")
    for path in drafts:
        data = _load_json(path)
        if data.get("draft_only") is not True:
            raise AssertionError(f"{path.name} missing draft_only:true")
        if data.get("apply_to_live") is True or data.get("config_patch") is True:
            raise AssertionError(f"{path.name} must not be a live config_patch")
        if data.get("trainable") is not False:
            raise AssertionError(f"{path.name} must stay TRAINABLE=false")
        rows.append(
            {
                "name": path.name,
                "draft_only": True,
                "proposed_keys": sorted(
                    k for k in collect_draft_proposed(data) if "." in k
                ),
                "proposed": collect_draft_proposed(data),
            }
        )
    return rows


def live_paths_untouched(repo: Path, drafts: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    if "still_proportion: 0.1" not in yaml_text:
        raise AssertionError("live still_proportion drifted off 0.1")
    if "still_proportion: 0.25" in yaml_text:
        raise AssertionError("draft still_proportion 0.25 leaked into live K1.yaml")
    if "draft-only" in yaml_text or "walk-p1-factors" in yaml_text:
        raise AssertionError("draft-only leaked into live K1.yaml")
    notes.append("K1.yaml live rewards / dims untouched")

    for rel in OFFICIAL_STABILITY_RELS:
        text = (repo / rel).read_text(encoding="utf-8")
        lowered = text.lower()
        if "draft-only" in lowered or "walk-p1-factors" in lowered:
            raise AssertionError(f"{rel} imported draft-only")
        if '"draft_only": true' in lowered:
            raise AssertionError(f"{rel} must not carry draft_only")
        notes.append(f"{Path(rel).name} has no draft-only import")

    ref = official_algorithm_keys(repo)["walk-reference-stability-v1.json"]
    if ref.get("reference_mean_penalty") != 1.0:
        raise AssertionError("live reference_mean_penalty drifted off 1.0")
    notes.append("official reference_mean_penalty stays 1.0")

    proposed = {}
    for row in drafts:
        proposed.update(row.get("proposed") or {})
    if proposed.get("commands.still_proportion") == 0.25 and "still_proportion: 0.25" in yaml_text:
        raise AssertionError("proposed still_proportion written into live YAML")
    return notes


def build_diff(
    official: dict[str, dict[str, Any]],
    drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    official_keys: set[str] = set()
    for algo in official.values():
        official_keys.update(algo)
    proposed_leaf: set[str] = set()
    proposed_full: set[str] = set()
    for row in drafts:
        for key in row.get("proposed") or {}:
            if "." in key and not key.split(".", 1)[0][0:1].isupper():
                pass
            if "." in key:
                proposed_full.add(key)
                proposed_leaf.add(key.rsplit(".", 1)[-1])
            else:
                proposed_leaf.add(key)
    overlap = sorted(official_keys & proposed_leaf)
    related = []
    for row in drafts:
        proposed = row.get("proposed") or {}
        if "commands.still_proportion" in proposed or "still_proportion" in proposed:
            related.append(
                {
                    "key": "commands.still_proportion",
                    "official": LIVE_REWARDS["still_proportion"],
                    "proposed": proposed.get("commands.still_proportion"),
                    "live_updated": False,
                }
            )
        if "reference_mean_penalty_end" in proposed:
            related.append(
                {
                    "key": "algorithm.reference_mean_penalty",
                    "official": LIVE_REWARDS["reference_mean_penalty"],
                    "proposed": {
                        "start": proposed.get("reference_mean_penalty_start"),
                        "end": proposed.get("reference_mean_penalty_end"),
                    },
                    "live_updated": False,
                }
            )
    return {
        "official_only": sorted(official_keys - proposed_leaf),
        "draft_proposed_only": sorted(proposed_leaf - official_keys),
        "draft_proposed_full": sorted(proposed_full),
        "name_overlap": overlap,
        "related_live_vs_proposed": related,
    }


def audit(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("p1 draft diff leaked WRITE_YAML/TRAINABLE")
    official = official_algorithm_keys(repo)
    drafts = assert_drafts_draft_only(repo)
    live_notes = live_paths_untouched(repo, drafts)
    snapshot = {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "read_only": True,
        "write_yaml": False,
        "trainable": False,
        "walk": "344→13",
        "sources": {
            "stability": list(OFFICIAL_STABILITY_RELS),
            "k1_yaml": K1_YAML_REL,
            "draft_dir": DRAFT_DIR_REL,
        },
        "all_drafts_draft_only": True,
        "live_paths_untouched": True,
        "official_algorithm": official,
        "drafts": [
            {"name": row["name"], "draft_only": True, "proposed_keys": row["proposed_keys"]}
            for row in drafts
        ],
        "live_rewards": dict(LIVE_REWARDS),
        "diff": build_diff(official, drafts),
        "notes": live_notes,
        "yaml_sha256": _sha256(repo / K1_YAML_REL),
    }
    return snapshot


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = audit(repo)
    path = dest or (repo / DIFF_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in __import__("sys").modules or "isaacgym" in __import__("sys").modules:
        errors.append("p1 draft diff imported Gym / Isaac Gym")

    before = _sha256(repo / K1_YAML_REL)
    try:
        snapshot = audit(repo)
        notes.append(f"drafts draft_only=true: {[row['name'] for row in snapshot['drafts']]}")
        notes.append("live paths untouched (K1.yaml + official stability-v1)")
        notes.extend(snapshot.get("notes") or [])
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snapshot = {}

    try:
        refuse_write_yaml(repo / K1_YAML_REL)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    after = _sha256(repo / K1_YAML_REL)
    if before != after:
        errors.append("K1.yaml content changed during p1 draft diff")
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
        "snapshot": {
            k: snapshot.get(k)
            for k in ("all_drafts_draft_only", "live_paths_untouched", "walk")
        }
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
        print(f"[p1-draft-diff] FAIL {exc}")
        return 1
    print(f"[p1-draft-diff] PASS walk 344→13; wrote {path}")
    print("[note] draft_only:true; live paths untouched; did not write K1.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
