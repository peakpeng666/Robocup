"""GetUp → Force-walk-afterwards → walk 344 handoff (read-only).

Deepens getup_walk_handoff_chain / force_walk_afterwards without replacing them:

  * Force walk afterwards cannot be skipped
  * Regular standup 73→22 / K1.onnx stays isolated from fast 72→22
  * Return is walkPolicy 344→13 / K1_walk.onnx
  * Overlay PASS is not field-ready standup

Does not import standup_eval_artifact_crosscheck.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/getup_force_walk_handoff.py
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

from force_walk_afterwards import (  # noqa: E402
    GETUP_ENGINE_RELS,
    locate_first,
    refuse_getup_done_direct_kick,
    refuse_stay_on_standup_after_getup,
)
from getup_walk_handoff_chain import (  # noqa: E402
    refuse_force_walk_lands_on_kick,
    refuse_getup_skips_force_walk,
)
from standup_fast_isolation_matrix import (  # noqa: E402
    refuse_isolation_matrix_cross_wires_slots,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
FIELD_READY = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/getup-force-walk-handoff-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "force_walk_not_skipped",
    "standup_73_22_isolated",
    "fast_72_22_isolated",
    "return_walk_344",
    "pass_not_field_ready_standup",
)

EDGES = (
    {
        "id": "force_walk_comment",
        "needle": "Force walk afterwards",
        "selects": "theWalkGenerator",
        "contract": "344→13",
    },
    {
        "id": "force_walk_create",
        "needle": "theWalkGenerator.createPhase",
        "selects": "walk",
        "contract": "344→13",
    },
)

GETUP_CFG_NEEDLES = (
    "policyName = K1.onnx",
    "numInput = 73",
    "numOutput = 22",
    "policyNameFast = K1_fast_standup.onnx",
    "numInputFast = 72",
    "numOutputFast = 22",
)
WALK_CFG_NEEDLES = (
    "modelName = K1_walk.onnx",
    "numInput = 344",
)
DOC_NEEDLES = (
    "getup_force_walk_handoff",
    "Force walk afterwards",
    "73→22",
    "TRAINABLE=false",
    "gap_closed=false",
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
        f"GetUp force-walk handoff overlay is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"GetUp force-walk handoff overlay is read-only; "
        f"must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_handoff_pass_as_field_ready_standup(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("handoff-pass-as-field-ready-standup claim must be a mapping")
    if (
        claim.get("handoff_pass_as_field_ready_standup")
        or claim.get("as_field_ready_standup")
        or claim.get("field_ready_standup")
        or claim.get("field_ready") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("field_ready") or claim.get("live_standup") or claim.get("competition_ready"))
        )
    ):
        raise ValueError(
            "GetUp→force-walk→walk344 overlay PASS is not field-ready standup; "
            "73→22 / 72→22 stay isolated; Force walk afterwards cannot be skipped"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _inventory_edges(repo: Path) -> list[dict[str, Any]]:
    cpp, rel = locate_first(repo, GETUP_ENGINE_RELS)
    if cpp is None:
        raise AssertionError("GetUpEngine.cpp missing; overlay must not fabricate force-walk")
    text = cpp.read_text(encoding="utf-8")
    found: list[dict[str, Any]] = []
    for edge in EDGES:
        if edge["needle"] not in text:
            raise AssertionError(f"{rel} missing edge {edge['id']}")
        found.append({**edge, "path": rel})
    return found


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("GetUp force-walk handoff leaked TRAINABLE / field_ready")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    edges = _inventory_edges(repo)
    getup_cfg = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    if not getup_cfg.is_file() or not walk_cfg.is_file():
        raise AssertionError("getUpEngine.cfg / walkingEngine.cfg missing")
    getup_text = getup_cfg.read_text(encoding="utf-8")
    walk_text = walk_cfg.read_text(encoding="utf-8")
    _require_needles(getup_text, GETUP_CFG_NEEDLES, GETUP_CFG_REL)
    _require_needles(walk_text, WALK_CFG_NEEDLES, WALK_CFG_REL)
    if "policyName = K1_fast_standup.onnx" in getup_text:
        raise AssertionError("regular GetUp policyName must not be fast ONNX")
    if "numInputFast = 73" in getup_text:
        raise AssertionError("fast slot must not claim 73")
    if "numInput = 72" in getup_text.split("policyNameFast", 1)[0]:
        raise AssertionError("regular GetUp numInput must stay 73")
    if "modelName = K1.onnx" in walk_text or "modelName = K1_fast_standup.onnx" in walk_text:
        raise AssertionError("walk modelName must stay K1_walk.onnx")

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
        "entry": "python3 bhuman/k1-training/scripts/getup_force_walk_handoff.py",
        "checklist": list(CHECKLIST),
        "edges": edges,
        "standup": "73→22",
        "fast": "72→22",
        "walk": "344→13",
        "force_walk_skipped": False,
        "handoff_pass_as_field_ready_standup": False,
        "field_ready": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "GetUp must pass Force walk afterwards; 73→22 / 72→22 isolated; "
            "return walk 344→13; overlay PASS ≠ field-ready standup"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
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
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_getup_force_walk_handoff_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("GetUp force-walk handoff leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"GetUp force-walk checklist drifted: {snap.get('checklist')}")
    if snap.get("force_walk_skipped") or snap.get("field_ready"):
        raise AssertionError("force-walk skipped or field_ready leaked")
    if snap.get("handoff_pass_as_field_ready_standup") or snap.get("apply_to_live"):
        raise AssertionError("handoff leaked field-ready standup / apply_to_live")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("GetUp force-walk leaked ready_gpu / would_train / GAP-closed")
    ids = [row.get("id") for row in (snap.get("edges") or [])]
    if ids != [edge["id"] for edge in EDGES]:
        raise AssertionError(f"GetUp force-walk edge ids drifted: {ids}")
    try:
        refuse_handoff_pass_as_field_ready_standup(
            {
                "handoff_pass_as_field_ready_standup": True,
                "as_field_ready_standup": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_handoff_pass_as_field_ready_standup must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("GetUp force-walk handoff imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_getup_force_walk_handoff_frozen(repo)
        notes.append("assert_getup_force_walk_handoff_frozen: force-walk required")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("GetUp → Force walk afterwards → walk 344→13; 73→22 / 72→22 isolated")
        notes.append("overlay PASS ≠ field-ready standup")

    try:
        refuse_handoff_pass_as_field_ready_standup(
            {"status": "PASS", "field_ready": True, "this_pin": True}
        )
        errors.append("handoff_pass_as_field_ready_standup must raise")
    except ValueError:
        notes.append("negative: overlay PASS as field-ready standup refused")
    try:
        refuse_getup_skips_force_walk({"getup_skips_force_walk": True, "skip_force_walk": True})
        errors.append("refuse_getup_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: skip Force walk afterwards refused")
    try:
        refuse_force_walk_lands_on_kick({"force_walk_lands_on_kick": True, "source": "force_walk"})
        errors.append("refuse_force_walk_lands_on_kick must raise")
    except ValueError:
        notes.append("negative: force-walk lands on kick refused")
    try:
        refuse_stay_on_standup_after_getup({"stay_on_standup_after_getup": True})
        errors.append("refuse_stay_on_standup_after_getup must raise")
    except ValueError:
        notes.append("negative: stay on standup after getup refused")
    try:
        refuse_getup_done_direct_kick({"getup_done_direct_kick": True})
        errors.append("refuse_getup_done_direct_kick must raise")
    except ValueError:
        notes.append("negative: getup_done direct kick refused")
    try:
        refuse_isolation_matrix_cross_wires_slots({"from": "standup", "to": "fast"})
        errors.append("refuse_isolation_matrix_cross_wires_slots must raise")
    except ValueError:
        notes.append("negative: 73→22 / 72→22 cross-wire refused")
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

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
        (getup_cfg, before_getup, "getUpEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during GetUp force-walk handoff")
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
        "handoff_pass_as_field_ready_standup": False,
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
        print(f"[getup-handoff] FAIL {exc}")
        return 1
    print(
        f"[getup-handoff] {snap.get('status')} "
        f"force-walk required; 73→22 / 72→22 isolated; "
        f"PASS ≠ field-ready standup; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
