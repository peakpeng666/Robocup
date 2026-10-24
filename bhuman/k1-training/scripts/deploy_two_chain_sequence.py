"""Read-only deploy-sequence two-chain pin (docs + machine contract).

Rewrites the deploy-call对照 so it matches playball_not_kick_policy:

  Chain A (official behavior):
    SkillBehavior → PlayBall → WalkToBallAndKick / Dribble
    → MotionRequest pose → WalkingEngine still default walkPolicy 344→13.

  Chain B (deploy bypass):
    only SkillSelectContext.want_kick=true AND all other walk-stay false
    → kickPolicy.apply() 59→13.

DEPLOY-CALL-SEQUENCE.md must keep these two chains separate.
Drawing PlayBall / WalkToBallAndKick as the kick net is forbidden.
Claiming the walk↔kick GAP closed is forbidden.
Chain A must not be declared equal to chain B.

Does not re-audit playball_not_kick_policy / skill_behavior_write_chain /
kick_policy_apply_dims wholesale. Never writes K1.yaml. TRAINABLE=false.
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
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from bt_skill_select import SkillSelectContext, select_skill  # noqa: E402
from deploy_call import DeployCall, SEQUENCE, TRAINABLE as DEPLOY_TRAINABLE  # noqa: E402
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/deploy-two-chain-sequence-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
DEPLOY_DOC_REL = "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"
PLAYBALL_SNAP_REL = "bhuman/k1-training/manifests/playball-not-kick-policy-latest.json"

SIBLINGS = (
    "playball_not_kick_policy.py",
    "skill_behavior_write_chain.py",
    "kick_policy_apply_dims.py",
    "walk_stay_remaining.py",
    "kick_engine_boundary.py",
    "deploy_call.py",
)

CHAINS = (
    {
        "id": "chain_a_official_behavior",
        "name": "链 A（官方行为 / 运动请求）",
        "hop": (
            "SkillBehaviorControl",
            "PlayBall",
            "WalkToBallAndKick / Dribble",
            "MotionRequest.motion pose",
            "WalkingEngine walkPolicy 344→13",
        ),
        "writes": "MotionRequest.motion",
        "values": ("walkToBallAndKick", "dribble"),
        "selects": "walkPolicy",
        "contract": "344→13",
        "applies_kick_policy": False,
        "is_kick_net": False,
    },
    {
        "id": "chain_b_deploy_bypass",
        "name": "链 B（部署旁路 / CompiledNN kick 槽）",
        "hop": (
            "SkillSelectContext.want_kick=true",
            "all other walk-stay false",
            "WalkingEngine kickPolicy.apply() 59→13",
        ),
        "writes": "kickPolicy.apply()",
        "selects": "kickPolicy",
        "contract": "59→13",
        "legal_when": "want_kick=true AND walk-stay all false",
        "official_want_kick_field": False,
    },
)

DOC_NEEDLES = (
    "链 A",
    "链 B",
    "walkPolicy **344→13**",
    "kickPolicy.apply() **59→13**",
    "SkillSelectContext.want_kick=true",
    "MotionRequest.motion",
    "WalkToBallAndKick",
    "gap_closed=false",
    "官方踢球技能 ≠ kick 网",
    "deploy_two_chain_sequence.py",
    "walk_to_ball_engine_no_onnx.py",
)
DOC_FORBIDDEN = (
    "PlayBall / WalkToBallAndKickEngine → kick **59→13**",
    "PlayBall → kickPolicy",
    "PlayBall → kick **59→13**",
    "chain A = chain B",
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
        f"deploy two-chain sequence is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"deploy two-chain sequence is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_deploy_seq_draws_playball_as_kick_net(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("deploy-seq-draws-playball-as-kick-net claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("doc") or "")
    if (
        claim.get("deploy_seq_draws_playball_as_kick_net")
        or claim.get("playball_drawn_as_kick_net")
        or claim.get("chain_a_is_kick_net")
        or (
            source
            in {
                "PlayBall",
                "WalkToBallAndKick",
                "WalkToBallAndKickEngine",
                "chain_a",
                "链 A",
                "DEPLOY-CALL-SEQUENCE",
                "DEPLOY-CALL-SEQUENCE.md",
            }
            and (
                claim.get("selects") == "kickPolicy"
                or claim.get("contract") == "59→13"
                or claim.get("is_kick_net")
                or claim.get("applies_kick_policy") is True
                or claim.get("skill") == "kick"
            )
        )
    ):
        raise ValueError(
            "deploy sequence must not draw PlayBall / WalkToBallAndKick as the "
            "kick net; chain A stays MotionRequest pose → walkPolicy 344→13"
        )


def refuse_chain_a_equals_chain_b(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("chain-a-equals-chain-b claim must be a mapping")
    if (
        claim.get("chain_a_equals_chain_b")
        or claim.get("same_chain")
        or claim.get("playball_is_kick_slot")
        or (
            claim.get("chain_a") == claim.get("chain_b")
            and claim.get("chain_a") is not None
        )
        or (
            claim.get("a_contract") == "59→13"
            and claim.get("b_contract") == "59→13"
        )
    ):
        raise ValueError(
            "chain A (PlayBall pose / walkPolicy 344→13) is not chain B "
            "(deploy want_kick → kickPolicy 59→13)"
        )


def refuse_deploy_doc_claims_gap_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("deploy-doc-claims-gap-closed claim must be a mapping")
    source = str(claim.get("source") or claim.get("doc") or "")
    if (
        claim.get("deploy_doc_claims_gap_closed")
        or claim.get("gap_closed") is True
        or claim.get("walk_kick_gap_closed")
        or (
            source
            in {
                "DEPLOY-CALL-SEQUENCE",
                "DEPLOY-CALL-SEQUENCE.md",
                "deploy_two_chain_sequence",
            }
            and (
                claim.get("status") == "CLOSED"
                or claim.get("gap") == "closed"
                or claim.get("closed") is True
            )
        )
    ):
        raise ValueError(
            "DEPLOY-CALL-SEQUENCE must keep walk↔kick GAP open "
            "(status=GAP / gap_closed=false); draft is not live"
        )


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
        "kick": "59→13",
        "deploy_seq_draws_playball_as_kick_net": False,
        "chain_a_equals_chain_b": False,
        "deploy_doc_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "note": "do not invent deploy two-chain sequence when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or DEPLOY_TRAINABLE:
        raise AssertionError("deploy two-chain leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    doc_path = repo / DEPLOY_DOC_REL
    if not doc_path.is_file():
        return _skip_source("DEPLOY-CALL-SEQUENCE.md missing; not fabricating two-chain doc")
    doc = doc_path.read_text(encoding="utf-8")
    missing = [n for n in DOC_NEEDLES if n not in doc]
    if missing:
        raise AssertionError(f"{DEPLOY_DOC_REL} missing two-chain needles {missing}")
    leaked = [n for n in DOC_FORBIDDEN if n in doc]
    if leaked:
        raise AssertionError(
            f"{DEPLOY_DOC_REL} draws chain A as kick net or closes GAP: {leaked}"
        )
    if "gap_closed=true" in doc or "GAP 已闭合" in doc:
        raise AssertionError("deploy doc claimed walk↔kick GAP closed")

    empty = map_skill_request(None)
    empty_bt = select_skill(SkillSelectContext())
    shoot = map_skill_request("shoot")
    kick = select_skill(SkillSelectContext(want_kick=True))
    tick = DeployCall().tick()
    if not empty.is_official_walk() or not empty_bt.is_official_walk():
        raise AssertionError("empty SkillRequest / SkillSelectContext must stay walk 344→13")
    if shoot.skips_walk or not shoot.is_official_walk():
        raise AssertionError("official shoot without want_kick must stay walk 344→13")
    if kick.skill != "kick" or "59→13" not in kick.contract:
        raise AssertionError("deploy want_kick=True must select kick 59→13")
    if tick.skill != "walk" or tick.contract != "344→13":
        raise AssertionError("DeployCall default tick must stay walk 344→13")
    if SEQUENCE[0]["layer"] != "BehaviorControl / Skill":
        raise AssertionError("deploy SEQUENCE must still start at BehaviorControl")

    playball_snap = repo / PLAYBALL_SNAP_REL
    playball: dict[str, Any] = {}
    if playball_snap.is_file():
        playball = json.loads(playball_snap.read_text(encoding="utf-8"))
        if playball.get("playball_as_kick_policy") or playball.get("walk") != "344→13":
            raise AssertionError("playball snapshot drifted; do not re-audit by inventing a new chain")
        ids = [row.get("id") for row in (playball.get("chains") or [])]
        if ids and ids != ["behavior_motion_request", "compilednn_kick_slot"]:
            raise AssertionError(f"playball two-chain ids drifted: {ids}")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (_SWITCHER / name).is_file()
        and not (_REACTIVE / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}; do not re-audit by inventing them")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "chains": list(CHAINS),
        "doc": {
            "rel": DEPLOY_DOC_REL,
            "needles": list(DOC_NEEDLES),
            "forbidden_absent": list(DOC_FORBIDDEN),
        },
        "chain_a": {
            "name": "链 A（官方行为 / 运动请求）",
            "selects": "walkPolicy",
            "contract": "344→13",
            "is_kick_net": False,
        },
        "chain_b": {
            "name": "链 B（部署旁路 / CompiledNN kick 槽）",
            "selects": "kickPolicy",
            "contract": "59→13",
            "legal_when": "want_kick=true AND walk-stay all false",
        },
        "chain_a_equals_chain_b": False,
        "deploy_seq_draws_playball_as_kick_net": False,
        "deploy_doc_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "cross": {
            "empty_skill_request": empty.skill,
            "empty_bt": empty_bt.skill,
            "shoot_without_want_kick": shoot.skill,
            "deploy_want_kick": kick.skill,
            "deploy_call_default": tick.skill,
            "playball_snapshot_walk": playball.get("walk"),
        },
        "fabricated": False,
        "note": (
            "deploy sequence keeps two chains: official PlayBall pose stays "
            "walkPolicy 344→13; kickPolicy 59→13 is deploy want_kick only; "
            "doc must not draw chain A as the kick net; GAP stays open"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else "",
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


def assert_two_chain_sequence_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("deploy two-chain leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate deploy two-chain")
        return snap
    ids = [row.get("id") for row in (snap.get("chains") or [])]
    expected = [row["id"] for row in CHAINS]
    if ids != expected:
        raise AssertionError(f"deploy two-chain table drifted: {ids}")
    if (snap.get("chain_a") or {}).get("is_kick_net") or (snap.get("chain_a") or {}).get("contract") != "344→13":
        raise AssertionError("chain A must stay walkPolicy 344→13, not a kick net")
    if (snap.get("chain_b") or {}).get("contract") != "59→13":
        raise AssertionError("chain B must stay kickPolicy 59→13")
    if snap.get("chain_a_equals_chain_b") or snap.get("deploy_seq_draws_playball_as_kick_net"):
        raise AssertionError("deploy sequence leaked chain A as kick net / A=B")
    if snap.get("deploy_doc_claims_gap_closed") or snap.get("walk_kick_gap_closed") or snap.get("gap_closed"):
        raise AssertionError("deploy doc leaked GAP-closed")
    try:
        refuse_deploy_seq_draws_playball_as_kick_net(
            {
                "deploy_seq_draws_playball_as_kick_net": True,
                "source": "PlayBall",
                "selects": "kickPolicy",
            }
        )
        raise AssertionError("refuse_deploy_seq_draws_playball_as_kick_net must raise")
    except ValueError:
        pass
    try:
        refuse_chain_a_equals_chain_b({"chain_a_equals_chain_b": True, "same_chain": True})
        raise AssertionError("refuse_chain_a_equals_chain_b must raise")
    except ValueError:
        pass
    try:
        refuse_deploy_doc_claims_gap_closed(
            {
                "deploy_doc_claims_gap_closed": True,
                "source": "DEPLOY-CALL-SEQUENCE.md",
                "gap_closed": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_deploy_doc_claims_gap_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("deploy two-chain imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_two_chain_sequence_frozen(repo)
        notes.append("assert_two_chain_sequence_frozen: 链 A ≠ 链 B; empty=walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        notes.append("honest SKIP: deploy two-chain not fabricated")
    elif snap:
        notes.append("chain A: PlayBall pose → walkPolicy 344→13 (not kick net)")
        notes.append("chain B: want_kick + walk-stay → kickPolicy 59→13")
        notes.append("DEPLOY-CALL-SEQUENCE.md keeps two chains; GAP stays open")
        notes.append("siblings referenced, not re-audited: playball / skill_behavior / kick_apply")

    for fn, claim, label in (
        (
            refuse_deploy_seq_draws_playball_as_kick_net,
            {
                "deploy_seq_draws_playball_as_kick_net": True,
                "source": "PlayBall",
                "selects": "kickPolicy",
            },
            "deploy seq draws PlayBall as kick net",
        ),
        (
            refuse_chain_a_equals_chain_b,
            {"chain_a_equals_chain_b": True, "same_chain": True},
            "chain A equals chain B",
        ),
        (
            refuse_deploy_doc_claims_gap_closed,
            {
                "deploy_doc_claims_gap_closed": True,
                "source": "DEPLOY-CALL-SEQUENCE.md",
                "gap_closed": True,
            },
            "deploy doc claims GAP closed",
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
            errors.append("K1.yaml changed during deploy two-chain audit")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during deploy two-chain audit")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "kick": "59→13",
        "deploy_seq_draws_playball_as_kick_net": False,
        "chain_a_equals_chain_b": False,
        "deploy_doc_claims_gap_closed": False,
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
        print(f"[deploy-2ch] FAIL {exc}")
        return 1
    print(
        f"[deploy-2ch] {snap.get('status')} "
        f"链 A ≠ 链 B; default walk {snap.get('walk')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
