"""No-GPU dual-chain switch dry-run negatives (glue only).

Stitches already-frozen asserts into one checklist:

  * PlayBall ≠ kickPolicy (chain A pose stays walk 344→13)
  * official SkillRequest has no want_kick (deploy port default False)
  * walk↔kick stale last_action must be refused; live zero is still GAP
  * Force walk afterwards is required before walk 344
  * walk↔kick resetHistoryData GAP stays open

Calls existing assert_* from playball_not_kick_policy, skill_behavior_write_chain,
policy_switch_last_action, force_walk_afterwards, deploy_two_chain_sequence
(and getup_walk_handoff refuse for Force walk). Does not re-audit wholesale.

Missing sibling → honest SKIP that step; do not fabricate.
will_run_isaac=false. TRAINABLE=false.

Do not claim last_action is already zeroed live on walk↔kick.
standup→walk 13-zero is a different closed contract.

Runnable: python3 bhuman/k1-training/scripts/dual_chain_switch_dry_run.py
Never writes K1.yaml or official cfg.
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
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from deploy_two_chain_sequence import (  # noqa: E402
    assert_two_chain_sequence_frozen,
)
from force_walk_afterwards import assert_force_walk_frozen  # noqa: E402
from getup_walk_handoff_chain import refuse_getup_skips_force_walk  # noqa: E402
from playball_not_kick_policy import (  # noqa: E402
    assert_two_chains_frozen,
    refuse_playball_as_kick_policy,
)
from policy_switch_last_action import (  # noqa: E402
    assert_policy_switch_last_action_frozen,
    refuse_switch_keeps_stale_last_action,
)
from policy_switch_phase_draft import (  # noqa: E402
    refuse_policy_switch_draft_as_live,
)
from skill_behavior_write_chain import (  # noqa: E402
    assert_write_chain_frozen,
    refuse_want_kick_default_true,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/dual-chain-switch-dry-run-latest.json"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
HANDOFF_DOC_REL = "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"
SKILL_H_REL = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h"
)

CHECKLIST = (
    "playball_not_kick_policy",
    "skill_behavior_write_chain",
    "policy_switch_last_action",
    "force_walk_afterwards",
    "deploy_two_chain_sequence",
)
CHECKLIST_NEGATIVES = (
    "playball_as_kick_policy",
    "want_kick_on_official_skill_request",
    "walk_kick_stale_last_action",
    "getup_skips_force_walk",
    "policy_switch_draft_as_live",
)

DOC_NEEDLES = (
    "dual_chain_switch_dry_run",
    "PlayBall",
    "want_kick",
    "last_action",
    "Force walk",
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
        f"dual-chain switch dry-run pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"dual-chain switch dry-run pin is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_dual_chain_dry_run_claims_gap_closed(
    claim: dict[str, Any] | None = None,
) -> None:
    blob = claim if isinstance(claim, dict) else {}
    text = str(blob.get("text") or blob.get("doc") or "")
    if (
        blob.get("dual_chain_dry_run_claims_gap_closed")
        or blob.get("gap_closed") is True
        or blob.get("walk_kick_last_action_live_zero") is True
        or blob.get("explicit_zero_on_walk_kick") is True
        or "GAP 已闭合" in text
        or "gap_closed=true" in text
    ):
        raise ValueError(
            "dual-chain switch dry-run must keep walk↔kick last_action / "
            "resetHistoryData as GAP (gap_closed=false); "
            "do not claim last_action is already zeroed live"
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("dual-chain dry-run leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    skill_h = repo / SKILL_H_REL
    if not skill_h.is_file():
        raise AssertionError("official SkillRequest.h missing")
    skill_text = skill_h.read_text(encoding="utf-8")
    if "want_kick" in skill_text:
        raise AssertionError("official SkillRequest.h must not grow want_kick")

    artifacts_doc = repo / ARTIFACTS_DOC_REL
    handoff_doc = repo / HANDOFF_DOC_REL
    if not artifacts_doc.is_file() or not handoff_doc.is_file():
        raise AssertionError("LOCAL-RUN-ARTIFACTS / DEPLOY-CALL-SEQUENCE missing")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    dep_text = handoff_doc.read_text(encoding="utf-8")
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(dep_text, DOC_NEEDLES, HANDOFF_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(dep_text, DOC_FORBIDDEN, HANDOFF_DOC_REL)

    steps = [
        _call_assert("playball_not_kick_policy", assert_two_chains_frozen, repo),
        _call_assert("skill_behavior_write_chain", assert_write_chain_frozen, repo),
        _call_assert(
            "policy_switch_last_action",
            assert_policy_switch_last_action_frozen,
            repo,
        ),
        _call_assert("force_walk_afterwards", assert_force_walk_frozen, repo),
        _call_assert(
            "deploy_two_chain_sequence",
            assert_two_chain_sequence_frozen,
            repo,
        ),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "dual-chain dry-run segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/dual_chain_switch_dry_run.py",
        "checklist": list(CHECKLIST),
        "checklist_negatives": list(CHECKLIST_NEGATIVES),
        "steps": steps,
        "official_skill_request_want_kick": False,
        "walk_kick_last_action_live_zero": False,
        "docs_pointer": {
            "deploy": HANDOFF_DOC_REL,
            "artifacts": ARTIFACTS_DOC_REL,
            "skill_request": SKILL_H_REL,
        },
        "will_run_isaac": False,
        "will_run_train_py": False,
        "will_exec_eval_here": False,
        "playball_as_kick_policy": False,
        "want_kick_on_official_skill_request": False,
        "walk_kick_stale_last_action": False,
        "getup_skips_force_walk": False,
        "policy_switch_draft_as_live": False,
        "dual_chain_dry_run_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "glue checklist: PlayBall≠kickPolicy; official SkillRequest has no "
            "want_kick; refuse stale last_action (live zero still GAP); "
            "Force walk required before walk 344; GAP stays open; no Isaac"
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


def assert_dual_chain_dry_run_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("dual-chain dry-run leaked flags")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        raise AssertionError("dual-chain dry-run leaked Isaac / train")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"dual-chain checklist drifted: {snap.get('checklist')}")
    if snap.get("checklist_negatives") != list(CHECKLIST_NEGATIVES):
        raise AssertionError(
            f"dual-chain negatives drifted: {snap.get('checklist_negatives')}"
        )
    if (
        snap.get("official_skill_request_want_kick")
        or snap.get("walk_kick_last_action_live_zero")
        or snap.get("dual_chain_dry_run_claims_gap_closed")
        or snap.get("policy_switch_draft_as_live")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError(
            "dual-chain dry-run leaked want_kick / live last_action zero / draft-as-live / GAP-closed"
        )
    try:
        refuse_playball_as_kick_policy(
            {"playball_as_kick_policy": True, "slot": "kickPolicy"}
        )
        raise AssertionError("refuse_playball_as_kick_policy must raise")
    except ValueError:
        pass
    try:
        refuse_want_kick_default_true(
            {
                "want_kick_default_true": True,
                "official_skill_request_want_kick": True,
            }
        )
        raise AssertionError("refuse_want_kick_default_true must raise")
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
        refuse_getup_skips_force_walk(
            {"getup_skips_force_walk": True, "next": "walk_without_force"}
        )
        raise AssertionError("refuse_getup_skips_force_walk must raise")
    except ValueError:
        pass
    try:
        refuse_policy_switch_draft_as_live(
            {"policy_switch_draft_as_live": True, "apply_to_live": True}
        )
        raise AssertionError("refuse_policy_switch_draft_as_live must raise")
    except ValueError:
        pass
    try:
        refuse_dual_chain_dry_run_claims_gap_closed(
            {"dual_chain_dry_run_claims_gap_closed": True, "gap_closed": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_dual_chain_dry_run_claims_gap_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("dual-chain dry-run imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_dual_chain_dry_run_frozen(repo)
        notes.append(
            "assert_dual_chain_dry_run_frozen: PlayBall≠kick · no official want_kick · GAP open"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("glue only; existing assert_* referenced, not re-audited")
        notes.append("will_run_isaac=false; last_action live zero still GAP")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_playball_as_kick_policy(
            {"playball_as_kick_policy": True, "slot": "kickPolicy"}
        )
        errors.append("playball_as_kick_policy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        refuse_want_kick_default_true(
            {
                "want_kick_default_true": True,
                "official_skill_request_want_kick": True,
            }
        )
        errors.append("want_kick_on_official_skill_request must raise")
    except ValueError:
        notes.append("negative: official SkillRequest want_kick refused")
    try:
        refuse_switch_keeps_stale_last_action(
            {"switch_keeps_stale_last_action": True, "source": "walk↔kick"}
        )
        errors.append("walk_kick_stale_last_action must raise")
    except ValueError:
        notes.append("negative: walk↔kick stale last_action refused (live zero still GAP)")
    try:
        refuse_getup_skips_force_walk(
            {"getup_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("getup_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: GetUp skips Force walk refused")
    try:
        refuse_policy_switch_draft_as_live(
            {"policy_switch_draft_as_live": True, "apply_to_live": True}
        )
        errors.append("policy_switch_draft_as_live must raise")
    except ValueError:
        notes.append("negative: policy-switch draft as live refused")
    try:
        refuse_dual_chain_dry_run_claims_gap_closed(
            {
                "dual_chain_dry_run_claims_gap_closed": True,
                "text": "GAP 已闭合",
                "walk_kick_last_action_live_zero": True,
            }
        )
        errors.append("dual_chain_dry_run_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: dual-chain dry-run claims GAP closed refused")
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
            errors.append("K1.yaml changed during dual-chain dry-run pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during dual-chain dry-run pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during dual-chain dry-run pin")
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
        "kick": "59→13",
        "dual_chain_dry_run_claims_gap_closed": False,
        "walk_kick_last_action_live_zero": False,
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
        print(f"[dual-chain-dry-run] FAIL {exc}")
        return 1
    print(
        f"[dual-chain-dry-run] {snap.get('status')} "
        f"PlayBall≠kick · no official want_kick · stale last_action refused · "
        f"Force walk required; GAP open; no Isaac; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
