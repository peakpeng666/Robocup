"""Walk-stability still/speed/stand inventory vs WalkingEngine (read-only).

Deepens walk_stability_presets_audit without replacing it:

  * still: K1.yaml still_proportion 0.1 vs WalkingEngine timeLowWalkSpeedForStand
  * speed: Default configuredParameters fast/normal/slow gears
  * stand: standAnkleStiffness 60/80 + standInterpolationVelocity
  * official walk-*-stability-v1 JSON must not rewrite those plant keys
  * Overlay PASS is not a competition-ready gait

Does not import competition_walk_allowlist_tighten.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/walk_stability_preset_inventory.py
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

from simulated_speed_diff import flatten_cfg  # noqa: E402
from speed_gear_diff import DEFAULT_GEARS  # noqa: E402
from walk_stability_presets_audit import (  # noqa: E402
    EXPECTED_OFFICIAL,
    assert_audit_frozen,
    refuse_draft_pollution,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
FIELD_READY = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-stability-preset-inventory-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
STILL_YAML = "still_proportion: 0.1"
STILL_ENGINE = "timeLowWalkSpeedForStand = 1000"
STAND_NEEDLES = (
    "standAnkleStiffness = {min = 60; max = 80;}",
    "standInterpolationVelocity = 70deg",
)
STABILITY_FORBIDDEN = (
    "still_proportion",
    "standAnkleStiffness",
    "standInterpolationVelocity",
    "timeLowWalkSpeedForStand",
    "fastWalkSpeed",
    "normalWalkSpeed",
    "slowWalkSpeed",
    "configuredParameters",
)

CHECKLIST = (
    "still_preset_inventory",
    "speed_preset_inventory",
    "stand_preset_inventory",
    "stability_json_not_rewrite_engine",
    "pass_not_competition_ready_gait",
)
DOC_NEEDLES = (
    "walk_stability_preset_inventory",
    "still/speed/stand",
    "TRAINABLE=false",
    "gap_closed=false",
    "PASS ≠ competition-ready gait",
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
        f"walk-stability preset inventory is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk-stability preset inventory is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_walk_stability_pass_as_competition_ready_gait(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-stability-pass-as-competition-ready-gait claim must be a mapping")
    if (
        claim.get("walk_stability_pass_as_competition_ready_gait")
        or claim.get("as_competition_ready_gait")
        or claim.get("competition_ready_gait")
        or claim.get("competition_ready") is True
        or claim.get("field_ready") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("competition_ready") or claim.get("live_gait") or claim.get("field_ready"))
        )
    ):
        raise ValueError(
            "walk-stability still/speed/stand inventory PASS is not a competition-ready gait; "
            "official walk-*-stability-v1 must not rewrite WalkingEngine plant keys"
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("walk-stability preset inventory leaked TRAINABLE / field_ready")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    if STILL_YAML not in yaml_text:
        raise AssertionError("official K1.yaml still_proportion drifted off 0.1")

    audit = assert_audit_frozen(repo)
    if audit.get("official") != list(EXPECTED_OFFICIAL):
        raise AssertionError("official walk-*-stability-v1 set drifted")

    walk_cfg = repo / WALK_CFG_REL
    if not walk_cfg.is_file():
        raise AssertionError("Default walkingEngine.cfg missing")
    walk_text = walk_cfg.read_text(encoding="utf-8")
    if STILL_ENGINE not in walk_text:
        raise AssertionError("WalkingEngine missing timeLowWalkSpeedForStand = 1000")
    _require_needles(walk_text, STAND_NEEDLES, WALK_CFG_REL)
    if "still_proportion" in walk_text:
        raise AssertionError("WalkingEngine must not carry train still_proportion")
    flat = flatten_cfg(walk_text)
    drifted = [
        f"{key}={flat.get(key)} ≠ {want}"
        for key, want in DEFAULT_GEARS.items()
        if flat.get(key) != want
    ]
    if drifted:
        raise AssertionError("Default speed gears drifted: " + "; ".join(drifted))

    for row in audit.get("presets") or []:
        blob = json.dumps(row.get("algorithm") or {}, ensure_ascii=False)
        refuse_draft_pollution(blob, row.get("name") or "preset")
        leaked = [tok for tok in STABILITY_FORBIDDEN if tok in blob]
        if leaked:
            raise AssertionError(
                f"{row.get('name')} must not rewrite WalkingEngine still/speed/stand ({leaked})"
            )

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/walk_stability_preset_inventory.py",
        "checklist": list(CHECKLIST),
        "official": list(EXPECTED_OFFICIAL),
        "still": {
            "yaml": STILL_YAML,
            "walking_engine": STILL_ENGINE,
            "same_contract": False,
        },
        "speed": dict(DEFAULT_GEARS),
        "stand": {
            "standAnkleStiffness": {"min": "60", "max": "80"},
            "standInterpolationVelocity": "70deg",
        },
        "stability_json_rewrites_engine": False,
        "walk_stability_pass_as_competition_ready_gait": False,
        "field_ready": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "still/speed/stand inventoried vs WalkingEngine; "
            "walk-*-stability-v1 does not rewrite plant keys; "
            "overlay PASS ≠ competition-ready gait"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest(),
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
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_walk_stability_preset_inventory_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("walk-stability preset inventory leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"walk-stability inventory checklist drifted: {snap.get('checklist')}")
    if snap.get("stability_json_rewrites_engine") or snap.get("field_ready"):
        raise AssertionError("stability JSON rewrote engine or field_ready leaked")
    if snap.get("walk_stability_pass_as_competition_ready_gait") or snap.get("apply_to_live"):
        raise AssertionError("inventory leaked competition-ready gait / apply_to_live")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("walk-stability inventory leaked ready_gpu / would_train / GAP-closed")
    if (snap.get("still") or {}).get("same_contract"):
        raise AssertionError("still_proportion must stay a train command, not a WalkingEngine key")
    try:
        refuse_walk_stability_pass_as_competition_ready_gait(
            {
                "walk_stability_pass_as_competition_ready_gait": True,
                "as_competition_ready_gait": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_walk_stability_pass_as_competition_ready_gait must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk-stability preset inventory imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_walk_stability_preset_inventory_frozen(repo)
        notes.append("assert_walk_stability_preset_inventory_frozen: still/speed/stand vs engine")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("still_proportion 0.1 ≠ WalkingEngine timeLowWalkSpeedForStand")
        notes.append("Default speed gears + stand 60/80 inventoried; stability JSON does not rewrite")
        notes.append("overlay PASS ≠ competition-ready gait")

    try:
        refuse_walk_stability_pass_as_competition_ready_gait(
            {"status": "PASS", "competition_ready": True, "this_pin": True}
        )
        errors.append("walk_stability_pass_as_competition_ready_gait must raise")
    except ValueError:
        notes.append("negative: overlay PASS as competition-ready gait refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(walk_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during walk-stability preset inventory")
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
        "field_ready": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "walk_stability_pass_as_competition_ready_gait": False,
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
        print(f"[walk-stability-inventory] FAIL {exc}")
        return 1
    print(
        f"[walk-stability-inventory] {snap.get('status')} "
        f"still/speed/stand vs WalkingEngine; "
        f"PASS ≠ competition-ready gait; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
