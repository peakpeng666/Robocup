"""Read-only walk↔kick historyBuffer GAP inventory (not closed).

Sibling of policy_switch_last_action. This pin records the *risk
sheet* and the draft-only mitigation, not the apply-site dims:

  GAP     getNextTargetRequest walk↔kick does not call resetHistoryData
  NOT     standup→walk 13-zero last_action (already closed)
  ISOL    kick 59 does not consume walk historyBuffer
  RISK    no explicit zero; walk after kick may see kick-period lastActions
  DRAFT   walk-kick-reset-history-v0.json; apply_to_live=false; gap_closed=false

Claiming the GAP is closed, the draft is live, or standup-zero fixes
walk↔kick is FAIL. Never writes WalkingEngine.cpp or K1.yaml.
TRAINABLE=false.
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
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE, _DRAFT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    require_draft_only_flag,
)
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
SNAPSHOT_REL = "bhuman/k1-training/manifests/policy-switch-history-gap-latest.json"
DOC_REL = "bhuman/docs/POLICY-SWITCH-HISTORY-GAP.md"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-kick-reset-history-v0.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.updateHistoryData(lastTarget)",
    "engine.walkPolicy.apply()",
    "policy.apply()",
    "*input++ = data.lastActions.angles[j]",
    "*input++ = lastTarget.angles[j]",
)
DOC_NEEDLES = (
    "GAP",
    "resetHistoryData",
    "344→13",
    "standup",
    "draft_only",
    "historyBuffer",
)
SWITCH_ZERO_NEEDLE = "resetHistoryData();"


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
        f"history-gap audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"history-gap audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_claim_walk_kick_gap_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("gap-closed claim must be a mapping")
    if (
        claim.get("claim_walk_kick_gap_closed")
        or claim.get("gap_closed")
        or claim.get("closed")
        or claim.get("merged")
        or claim.get("status") in {"closed", "merged", "applied"}
    ):
        raise ValueError(
            "walk↔kick resetHistoryData GAP is still open; "
            "do not mark it closed / merged / applied"
        )


def refuse_draft_mitigation_as_live(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("draft-as-live claim must be a mapping")
    if (
        claim.get("draft_mitigation_as_live")
        or claim.get("apply_to_live")
        or claim.get("apply_to_walking_engine")
        or claim.get("applied_to_cpp")
        or claim.get("config_patch")
    ):
        raise ValueError(
            "walk-kick-reset-history draft must stay draft_only; "
            "it is not live WalkingEngine / K1.yaml / train.py"
        )


def refuse_standup_zero_as_walk_kick_fix(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-zero-as-fix claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("standup_zero_as_walk_kick_fix")
        or claim.get("standup_closes_walk_kick")
        or (
            source
            in {
                "last_action_reset",
                "standup→walk",
                "getup_done",
                "13-zero",
            }
            and (
                claim.get("closes_walk_kick_gap")
                or claim.get("gap_closed")
                or claim.get("same_contract")
            )
        )
    ):
        raise ValueError(
            "standup→walk 13-zero last_action is a different closed contract; "
            "it does not fix the walk↔kick resetHistoryData GAP"
        )


def _assert_slot(flat: dict[str, str], label: str) -> None:
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in SLOT_KEYS.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


def _getnext_has_reset(cpp_text: str) -> bool:
    start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    if start < 0:
        return False
    end = cpp_text.find("\nvoid ", start + 1)
    body = cpp_text[start:end] if end > start else cpp_text[start:]
    return SWITCH_ZERO_NEEDLE in body


def _skip_source(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "fabricated": False,
        "gap_closed": False,
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "note": "do not invent a closed GAP when source or draft is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("history-gap audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    draft_path = repo / DRAFT_REL
    doc_path = repo / DOC_REL
    if not default_path.is_file() or not cpp_rel:
        return _skip_source("Default walkingEngine.cfg or WalkingEngine.cpp missing")
    if not draft_path.is_file():
        return _skip_source("draft-only walk-kick-reset-history-v0.json missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing history-gap needles {missing}")
    if _getnext_has_reset(cpp_text):
        raise AssertionError(
            "getNextTargetRequest now calls resetHistoryData; "
            "re-audit before claiming the draft was merged"
        )
    if "DRAFT ONLY" in cpp_text or "walk-kick-reset-history" in cpp_text:
        raise AssertionError("draft mitigation leaked into official WalkingEngine.cpp")

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    require_draft_only_flag(draft)
    refuse_as_official_config_patch(draft)
    if draft.get("apply_to_live") or draft.get("apply_to_walking_engine") or draft.get("gap_closed"):
        raise AssertionError("draft must keep apply_to_live=false and gap_closed=false")
    proposed = draft.get("proposed_only") or {}
    if proposed.get("call") != "engine.resetHistoryData()":
        raise AssertionError("draft proposed call drifted off resetHistoryData")
    if (draft.get("gap") or {}).get("closed"):
        raise AssertionError("draft gap.closed must stay false")

    if not doc_path.is_file():
        raise AssertionError(f"missing {DOC_REL}")
    doc = doc_path.read_text(encoding="utf-8")
    missing_doc = [n for n in DOC_NEEDLES if n not in doc]
    if missing_doc:
        raise AssertionError(f"{DOC_REL} missing risk needles {missing_doc}")

    empty = map_skill_request(None)
    kicked = map_skill_request("shoot", want_kick=True)
    if not empty.is_official_walk() or kicked.contract != "59→13":
        raise AssertionError("empty must stay walk; want_kick must stay kick 59→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "draft": DRAFT_REL,
            "doc": DOC_REL,
        },
        "gap": {
            "id": "walk_kick_resetHistoryData",
            "scope": "getNextTargetRequest compiled bypass walk↔kick only",
            "not_scope": "standup→walk last_action 13-zero (already closed)",
            "explicit_zero": False,
            "closed": False,
            "status": "GAP",
            "fabricated": False,
        },
        "isolation": {
            "kick_consumes_walk_history": False,
            "walk_fills_from_historyBuffer": True,
            "kick_fills_from_lastTarget": True,
            "history_still_updates_during_kick": True,
            "residual_risk": "kick→walk may see kick-period lastActions in the 10-frame window",
        },
        "draft": {
            "rel": DRAFT_REL,
            "draft_only": True,
            "apply_to_live": False,
            "apply_to_walking_engine": False,
            "gap_closed": False,
            "proposed_call": proposed.get("call"),
        },
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kick_numInput": KICK_OBS,
        },
        "claim_walk_kick_gap_closed": False,
        "draft_mitigation_as_live": False,
        "standup_zero_as_walk_kick_fix": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "walk↔kick resetHistoryData is still a GAP; kick 59 does not eat "
            "the walk window but no explicit zero; draft exists and is not live; "
            "standup 13-zero is a different closed contract"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "kick_contract": "59→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "draft_sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(),
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


def assert_history_gap_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("history-gap audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated") or snap.get("gap_closed"):
            raise AssertionError("SKIP must not fabricate a closed GAP")
        return snap
    gap = snap.get("gap") or {}
    if gap.get("closed") or gap.get("explicit_zero") or gap.get("status") != "GAP":
        raise AssertionError("walk↔kick GAP must stay open / not explicit")
    if snap.get("claim_walk_kick_gap_closed") or snap.get("draft_mitigation_as_live"):
        raise AssertionError("GAP/draft flags leaked closed/live")
    if snap.get("standup_zero_as_walk_kick_fix"):
        raise AssertionError("standup 13-zero must not be marked as the walk↔kick fix")
    isol = snap.get("isolation") or {}
    if isol.get("kick_consumes_walk_history"):
        raise AssertionError("kick must not be marked as consuming walk history")
    draft = snap.get("draft") or {}
    if draft.get("apply_to_live") or draft.get("gap_closed"):
        raise AssertionError("draft must stay not-live and gap_closed=false")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS:
        raise AssertionError("walk slot must stay 344")
    try:
        refuse_claim_walk_kick_gap_closed({"claim_walk_kick_gap_closed": True, "closed": True})
        raise AssertionError("refuse_claim_walk_kick_gap_closed must raise")
    except ValueError:
        pass
    try:
        refuse_draft_mitigation_as_live({"draft_mitigation_as_live": True, "apply_to_live": True})
        raise AssertionError("refuse_draft_mitigation_as_live must raise")
    except ValueError:
        pass
    try:
        refuse_standup_zero_as_walk_kick_fix(
            {
                "standup_zero_as_walk_kick_fix": True,
                "source": "last_action_reset",
                "closes_walk_kick_gap": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_standup_zero_as_walk_kick_fix must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("history-gap audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    cpp_path = next((repo / rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_cpp = hashlib.sha256(cpp_path.read_bytes()).hexdigest() if cpp_path else ""
    try:
        snap = assert_history_gap_frozen(repo)
        notes.append("assert_history_gap_frozen: GAP open; draft not live")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source or draft missing"))
        notes.append("honest SKIP: GAP / draft not fabricated")
    elif snap:
        notes.append("walk↔kick resetHistoryData still GAP; standup 13-zero is other contract")
        notes.append("kick 59 does not eat walk window; residual: no explicit zero")
        notes.append("draft walk-kick-reset-history-v0 is draft_only / not live")

    for fn, claim, label in (
        (
            refuse_claim_walk_kick_gap_closed,
            {"claim_walk_kick_gap_closed": True, "closed": True},
            "claim walk↔kick GAP closed",
        ),
        (
            refuse_draft_mitigation_as_live,
            {"draft_mitigation_as_live": True, "apply_to_live": True},
            "draft mitigation as live",
        ),
        (
            refuse_standup_zero_as_walk_kick_fix,
            {
                "standup_zero_as_walk_kick_fix": True,
                "source": "last_action_reset",
                "closes_walk_kick_gap": True,
            },
            "standup 13-zero as walk↔kick fix",
        ),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

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
            errors.append("K1.yaml changed during history-gap audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during history-gap audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if cpp_path:
        after_cpp = hashlib.sha256(cpp_path.read_bytes()).hexdigest()
        if before_cpp != after_cpp:
            errors.append("WalkingEngine.cpp changed during history-gap audit")
        else:
            notes.append("official WalkingEngine.cpp untouched")

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
        "gap_closed": False,
        "claim_walk_kick_gap_closed": False,
        "draft_mitigation_as_live": False,
        "standup_zero_as_walk_kick_fix": False,
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
        print(f"[hist-gap] FAIL {exc}")
        return 1
    gap = snap.get("gap") or {}
    print(
        f"[hist-gap] {snap.get('status')} gap={gap.get('status')} "
        f"closed={gap.get('closed')}; draft not live; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
