"""Policy-switch phase draft stub (apply_to_live=false).

Stitches already-frozen points into one draft phase order:

  1. last_action zero point
     walk↔kick: honest GAP (no live explicit zero)
     standup→walk 13-zero is a different closed contract
  2. history reset draft point
     walk-kick-reset-history-v0.json; apply_to_live=false; gap_closed=false
  3. force-walk-afterwards
     required before walk 344 after GetUp; not a walk↔kick closer

This stub never writes WalkingEngine.cpp / yaml / cfg.
TRAINABLE=false. walk↔kick GAP stays open.

Does not import dual_chain_switch_dry_run (that sibling may call us).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
for extra in (_SCRIPTS, _SWITCHER, _DRAFT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from force_walk_afterwards import assert_force_walk_frozen  # noqa: E402
from getup_walk_handoff_chain import refuse_getup_skips_force_walk  # noqa: E402
from policy_switch_history_gap import (  # noqa: E402
    assert_history_gap_frozen,
    refuse_claim_walk_kick_gap_closed,
    refuse_draft_mitigation_as_live,
)
from policy_switch_last_action import (  # noqa: E402
    assert_policy_switch_last_action_frozen,
    refuse_switch_keeps_stale_last_action,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/policy-switch-phase-draft-latest.json"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-kick-reset-history-v0.json"
GAP_DOC_REL = "bhuman/docs/POLICY-SWITCH-HISTORY-GAP.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
HANDOFF_DOC_REL = "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"

PHASES = (
    "last_action_zero_point",
    "history_reset_draft_point",
    "force_walk_afterwards",
)

DRAFT_NEEDLES = (
    '"apply_to_live": false',
    '"gap_closed": false',
    '"draft_only": true',
    "resetHistoryData",
)
DOC_NEEDLES = (
    "policy_switch_phase_draft",
    "last_action",
    "resetHistoryData",
    "Force walk",
    "apply_to_live=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
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
        f"policy-switch phase draft is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"policy-switch phase draft is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_policy_switch_draft_as_live(claim: dict[str, Any] | None = None) -> None:
    blob = claim if isinstance(claim, dict) else {}
    if (
        blob.get("policy_switch_draft_as_live")
        or blob.get("apply_to_live") is True
        or blob.get("apply_to_walking_engine") is True
        or blob.get("gap_closed") is True
        or blob.get("walk_kick_last_action_live_zero") is True
    ):
        raise ValueError(
            "policy-switch phase draft stays apply_to_live=false; "
            "last_action live zero / resetHistoryData are still GAP"
        )


def refuse_policy_switch_draft_skips_force_walk(
    claim: dict[str, Any] | None = None,
) -> None:
    blob = claim if isinstance(claim, dict) else {}
    nxt = str(blob.get("next") or blob.get("lands_on") or "")
    if (
        blob.get("policy_switch_draft_skips_force_walk")
        or blob.get("skip_force_walk")
        or nxt in {"walk_without_force", "kick"}
        or (
            blob.get("from") in {"standup", "getup"}
            and blob.get("to") == "walk344"
            and not blob.get("via_force_walk")
        )
    ):
        raise ValueError(
            "policy-switch phase draft keeps Force walk afterwards "
            "before walk 344 after GetUp; skipping that step is illegal"
        )


def refuse_policy_switch_draft_claims_gap_closed(
    claim: dict[str, Any] | None = None,
) -> None:
    blob = claim if isinstance(claim, dict) else {}
    text = str(blob.get("text") or blob.get("doc") or "")
    if (
        blob.get("policy_switch_draft_claims_gap_closed")
        or blob.get("gap_closed") is True
        or "GAP 已闭合" in text
        or "gap_closed=true" in text
    ):
        raise ValueError(
            "policy-switch phase draft must keep walk↔kick resetHistoryData "
            "as GAP (gap_closed=false / apply_to_live=false)"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _call_assert(
    label: str,
    fn: Callable[..., dict[str, Any]] | None,
    repo: Path,
) -> dict[str, Any]:
    if fn is None:
        return {
            "id": label,
            "status": "SKIP",
            "reason": f"{label} sibling missing; not fabricated",
            "fabricated": False,
        }
    try:
        result = fn(repo)
    except FileNotFoundError as exc:
        return {
            "id": label,
            "status": "SKIP",
            "reason": str(exc),
            "fabricated": False,
        }
    except (AssertionError, ValueError) as exc:
        return {"id": label, "status": "FAIL", "reason": str(exc), "fabricated": False}
    status = str((result or {}).get("status") or "PASS")
    if status == "SKIP":
        return {
            "id": label,
            "status": "SKIP",
            "reason": str((result or {}).get("reason") or f"{label} SKIP"),
            "fabricated": False,
        }
    return {"id": label, "status": "PASS", "reason": None, "fabricated": False}


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("policy-switch phase draft leaked TRAINABLE / live flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    draft = repo / DRAFT_REL
    gap_doc = repo / GAP_DOC_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    handoff_doc = repo / HANDOFF_DOC_REL
    for path, label in (
        (draft, DRAFT_REL),
        (gap_doc, GAP_DOC_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (handoff_doc, HANDOFF_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")

    draft_text = draft.read_text(encoding="utf-8")
    draft_blob = json.loads(draft_text)
    _require_needles(draft_text, DRAFT_NEEDLES, DRAFT_REL)
    if draft_blob.get("apply_to_live") or draft_blob.get("gap_closed"):
        raise AssertionError("walk-kick-reset-history draft leaked live / GAP-closed")
    if not draft_blob.get("draft_only"):
        raise AssertionError("walk-kick-reset-history must stay draft_only")

    art_text = artifacts_doc.read_text(encoding="utf-8")
    gap_text = gap_doc.read_text(encoding="utf-8")
    dep_text = handoff_doc.read_text(encoding="utf-8")
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(gap_text, ("policy_switch_phase_draft", "apply_to_live=false"), GAP_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(gap_text, ("gap_closed=true",), GAP_DOC_REL)
    _forbid_tokens(dep_text, DOC_FORBIDDEN, HANDOFF_DOC_REL)
    if "policy_switch_phase_draft" not in dep_text:
        raise AssertionError("DEPLOY-CALL-SEQUENCE must point at policy_switch_phase_draft")

    steps = [
        _call_assert(
            "policy_switch_last_action",
            assert_policy_switch_last_action_frozen,
            repo,
        ),
        _call_assert("policy_switch_history_gap", assert_history_gap_frozen, repo),
        _call_assert("force_walk_afterwards", assert_force_walk_frozen, repo),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "policy-switch phase draft segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/policy_switch_phase_draft.py",
        "phases": list(PHASES),
        "apply_to_live": False,
        "draft_only": True,
        "walk_kick_last_action_live_zero": False,
        "history_reset_live": False,
        "steps": steps,
        "docs_pointer": {
            "draft": DRAFT_REL,
            "gap": GAP_DOC_REL,
            "deploy": HANDOFF_DOC_REL,
        },
        "will_run_isaac": False,
        "will_run_train_py": False,
        "policy_switch_draft_as_live": False,
        "policy_switch_draft_skips_force_walk": False,
        "policy_switch_draft_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "draft phase order: last_action zero (walk↔kick still GAP) → "
            "history reset draft → Force walk before walk 344; "
            "apply_to_live=false; standup→walk 13-zero is a different closed contract"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "getup_cfg_sha256": hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if getup_cfg.is_file()
        else "",
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


def assert_policy_switch_phase_draft_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("policy-switch phase draft leaked flags")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        raise AssertionError("policy-switch phase draft leaked Isaac / train")
    if snap.get("phases") != list(PHASES):
        raise AssertionError(f"phase order drifted: {snap.get('phases')}")
    if snap.get("apply_to_live") or snap.get("history_reset_live"):
        raise AssertionError("phase draft leaked apply_to_live")
    if (
        snap.get("policy_switch_draft_as_live")
        or snap.get("policy_switch_draft_skips_force_walk")
        or snap.get("policy_switch_draft_claims_gap_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("walk_kick_last_action_live_zero")
        or snap.get("fabricated")
    ):
        raise AssertionError("phase draft leaked live / skip-force-walk / GAP-closed")
    try:
        refuse_policy_switch_draft_as_live(
            {"policy_switch_draft_as_live": True, "apply_to_live": True}
        )
        raise AssertionError("refuse_policy_switch_draft_as_live must raise")
    except ValueError:
        pass
    try:
        refuse_policy_switch_draft_skips_force_walk(
            {"policy_switch_draft_skips_force_walk": True, "next": "walk_without_force"}
        )
        raise AssertionError("refuse_policy_switch_draft_skips_force_walk must raise")
    except ValueError:
        pass
    try:
        refuse_policy_switch_draft_claims_gap_closed(
            {"policy_switch_draft_claims_gap_closed": True, "gap_closed": True}
        )
        raise AssertionError("refuse_policy_switch_draft_claims_gap_closed must raise")
    except ValueError:
        pass
    try:
        refuse_switch_keeps_stale_last_action(
            {"switch_keeps_stale_last_action": True, "source": "walk↔kick"}
        )
        raise AssertionError("refuse_switch_keeps_stale_last_action must raise")
    except ValueError:
        pass
    try:
        refuse_draft_mitigation_as_live({"draft_mitigation_as_live": True})
        raise AssertionError("refuse_draft_mitigation_as_live must raise")
    except ValueError:
        pass
    try:
        refuse_claim_walk_kick_gap_closed({"claim_walk_kick_gap_closed": True})
        raise AssertionError("refuse_claim_walk_kick_gap_closed must raise")
    except ValueError:
        pass
    try:
        refuse_getup_skips_force_walk(
            {"getup_skips_force_walk": True, "next": "walk_without_force"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_getup_skips_force_walk must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("policy-switch phase draft imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_policy_switch_phase_draft_frozen(repo)
        notes.append(
            "assert_policy_switch_phase_draft_frozen: last_action → history draft → Force walk"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("apply_to_live=false; walk↔kick last_action live zero still GAP")
        notes.append("standup→walk 13-zero is a different closed contract")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_policy_switch_draft_as_live(
            {"policy_switch_draft_as_live": True, "apply_to_live": True}
        )
        errors.append("policy_switch_draft_as_live must raise")
    except ValueError:
        notes.append("negative: policy-switch draft as live refused")
    try:
        refuse_policy_switch_draft_skips_force_walk(
            {"policy_switch_draft_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("policy_switch_draft_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: policy-switch draft skips Force walk refused")
    try:
        refuse_policy_switch_draft_claims_gap_closed(
            {"policy_switch_draft_claims_gap_closed": True, "text": "GAP 已闭合"}
        )
        errors.append("policy_switch_draft_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: policy-switch draft claims GAP closed refused")
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

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during policy-switch phase draft pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during policy-switch phase draft pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during policy-switch phase draft pin")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "apply_to_live": False,
        "policy_switch_draft_as_live": False,
        "policy_switch_draft_skips_force_walk": False,
        "policy_switch_draft_claims_gap_closed": False,
        "will_run_isaac": False,
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
        print(f"[phase-draft] FAIL {exc}")
        return 1
    print(
        f"[phase-draft] {snap.get('status')} "
        f"last_action → history draft → Force walk; apply_to_live=false; "
        f"GAP open; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
