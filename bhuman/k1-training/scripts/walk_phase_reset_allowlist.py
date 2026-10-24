"""Read-only WalkPhase continue vs new resetHistoryData allowlist.

Sibling of policy_switch_history_gap. This pin records *who* may reset:

  RESET   WalkingEngine constructor
          WalkPhase ctor else-branch (lastPhase is not a continuing WalkPhase)
  KEEP    continuing WalkPhase:
          (lastPhase.type == walk || stand) && dynamic_cast<WalkPhase*>

getNextTargetRequest walk↔kick is NOT on this allowlist (honest GAP).
A new/non-continue WalkPhase that skips the required reset is FAIL.
Never writes WalkingEngine.cpp or K1.yaml. TRAINABLE=false.
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

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from simulated_speed_diff import (  # noqa: E402
    KICK_ONNX,
    WALK_DEFAULT_ONNX,
    flatten_cfg,
)
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-phase-reset-allowlist-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CONTINUE_PREDICATE = (
    "(lastPhase.type == MotionPhase::walk || lastPhase.type == MotionPhase::stand) && walkPhase"
)
CONTINUE_CAST = "const WalkPhase* walkPhase = dynamic_cast<const WalkPhase*>(&lastPhase);"
CTOR_SIG = "WalkPhase::WalkPhase(WalkingEngine& engine, Pose2f useStepTarget, const MotionPhase& lastPhase)"
CPP_NEEDLES = (
    CTOR_SIG,
    CONTINUE_CAST,
    CONTINUE_PREDICATE,
    "engine.resetHistoryData()",
    "void WalkingEngine::resetHistoryData()",
    "void WalkPhase::getNextTargetRequest",
)
EXPECTED_CALL_SITES = (
    "WalkingEngine constructor",
    "WalkPhase ctor else-branch (non-continue)",
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
        f"WalkPhase reset allowlist is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"WalkPhase reset allowlist is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_continue_phase_skips_required_reset(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("continue-skips-required-reset claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("lastPhase") or "")
    if (
        claim.get("continue_phase_skips_required_reset")
        or claim.get("treat_new_as_continue")
        or claim.get("skip_required_reset")
        or (
            source
            in {
                "DummyPhase",
                "playDead",
                "getup",
                "GetUp",
                "new WalkPhase",
                "non-continue",
            }
            and (
                claim.get("skip_reset")
                or claim.get("as_continue")
                or claim.get("resets") is False
            )
        )
    ):
        raise ValueError(
            "a non-continue WalkPhase must call resetHistoryData; "
            "do not treat DummyPhase / getup / playDead as a continuing WalkPhase"
        )


def _assert_slot(flat: dict[str, str], label: str) -> None:
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in SLOT_KEYS.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


def _call_sites(cpp_text: str) -> list[str]:
    sites: list[str] = []
    for raw in cpp_text.splitlines():
        line = raw.strip()
        if "resetHistoryData()" not in line or line.startswith("void "):
            continue
        if line.startswith("//"):
            continue
        sites.append(line)
    return sites


def _getnext_has_reset(cpp_text: str) -> bool:
    start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    if start < 0:
        return False
    end = cpp_text.find("\nvoid ", start + 1)
    body = cpp_text[start:end] if end > start else cpp_text[start:]
    return "resetHistoryData()" in body


def _ctor_else_has_reset(cpp_text: str) -> bool:
    start = cpp_text.find(CTOR_SIG)
    if start < 0:
        return False
    end = cpp_text.find("void WalkPhase::getNextTargetRequest", start)
    body = cpp_text[start:end] if end > start else cpp_text[start:]
    if CONTINUE_PREDICATE not in body or CONTINUE_CAST not in body:
        return False
    else_idx = body.find("else")
    reset_idx = body.find("engine.resetHistoryData()")
    return reset_idx > else_idx >= 0


def _skip_source(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "continue_phase_skips_required_reset": False,
        "note": "do not invent WalkPhase reset sites when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("WalkPhase reset allowlist leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    if not default_path.is_file() or not cpp_rel:
        return _skip_source("Default walkingEngine.cfg or WalkingEngine.cpp missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing WalkPhase reset needles {missing}")
    if not _ctor_else_has_reset(cpp_text):
        raise AssertionError("WalkPhase ctor else-branch must call resetHistoryData")
    if _getnext_has_reset(cpp_text):
        raise AssertionError(
            "getNextTargetRequest must not gain resetHistoryData without a re-audit"
        )
    sites = _call_sites(cpp_text)
    if len(sites) != 2:
        raise AssertionError(
            f"resetHistoryData call-site drift: expected 2, got {sites}"
        )
    if "engine.resetHistoryData();" not in sites or not any(
        re.fullmatch(r"resetHistoryData\(\);", s) for s in sites
    ):
        raise AssertionError(f"resetHistoryData call sites drifted: {sites}")

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        if "void resetHistoryData()" not in h_text:
            raise AssertionError(f"{h_rel} missing resetHistoryData declaration")

    empty = map_skill_request(None)
    if not empty.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {"default": DEFAULT_WALK_REL, "cpp": cpp_rel, "header": h_rel},
        "continue_phase": {
            "predicate": CONTINUE_PREDICATE,
            "cast": "dynamic_cast<const WalkPhase*>(&lastPhase)",
            "resets": False,
            "types": ["walk", "stand"],
        },
        "reset_when": list(EXPECTED_CALL_SITES),
        "not_reset": [
            "WalkPhase::getNextTargetRequest walk↔kick compiled bypass (GAP)",
            "continuing WalkPhase (walk/stand + WalkPhase*)",
        ],
        "call_sites": sites,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kick_numInput": KICK_OBS,
        },
        "continue_phase_skips_required_reset": False,
        "gap_closed": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "resetHistoryData only on WalkingEngine ctor and non-continue "
            "WalkPhase; continue = walk/stand + WalkPhase*; walk↔kick switch "
            "is not on this allowlist"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
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
        "motorParameters.cfg",
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_walk_phase_reset_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("WalkPhase reset allowlist leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate reset sites")
        return snap
    if snap.get("continue_phase_skips_required_reset") or snap.get("gap_closed"):
        raise AssertionError("continue-skip / gap-closed flags leaked")
    cont = snap.get("continue_phase") or {}
    if cont.get("resets") or CONTINUE_PREDICATE not in str(cont.get("predicate")):
        raise AssertionError("continue-phase predicate drifted")
    if snap.get("reset_when") != list(EXPECTED_CALL_SITES):
        raise AssertionError("reset-when allowlist drifted")
    if len(snap.get("call_sites") or []) != 2:
        raise AssertionError("resetHistoryData must stay exactly two call sites")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS:
        raise AssertionError("walk slot must stay 344")
    try:
        refuse_continue_phase_skips_required_reset(
            {
                "continue_phase_skips_required_reset": True,
                "source": "DummyPhase",
                "skip_reset": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_continue_phase_skips_required_reset must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("WalkPhase reset allowlist imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_walk_phase_reset_frozen(repo)
        notes.append("assert_walk_phase_reset_frozen: ctor + non-continue only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: reset allowlist not fabricated")
    elif snap:
        notes.append("continue = walk/stand + WalkPhase*; does not reset")
        notes.append("reset = WalkingEngine ctor + new non-continue WalkPhase")
        notes.append("getNextTargetRequest walk↔kick still not on the allowlist")

    try:
        refuse_continue_phase_skips_required_reset(
            {
                "continue_phase_skips_required_reset": True,
                "source": "DummyPhase",
                "skip_reset": True,
            }
        )
        errors.append("non-continue skip required reset must raise")
    except ValueError:
        notes.append("negative: non-continue skip required reset refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during WalkPhase reset audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during WalkPhase reset audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "continue_phase_skips_required_reset": False,
        "gap_closed": False,
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
        print(f"[phase-reset] FAIL {exc}")
        return 1
    print(
        f"[phase-reset] {snap.get('status')} "
        f"reset_when={snap.get('reset_when')}; continue keeps buffer; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
