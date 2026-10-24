"""Domain-rand / disturbance draft validator (read-only; no GPU).

Deepens disturbance_curriculum_audit without replacing it:

  * Official K1 walk live push_* / friction / mass stay frozen
  * Draft C_disturbance_curriculum stays draft_only / proposed_only
  * mass / friction / push curricula keys are inventoried if present
  * Kick / standup randomization is noted (not walk DR)
  * apply_to_live=false
  * Validator PASS is not live domain randomization

TRAINABLE=false. walk↔kick GAP stays open.
Does not import pd_gain_domain_gap_negatives or
simrobot_six_robot_acceptance_gap.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/domain_rand_disturbance_draft_validator.py
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
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
for extra in (_SCRIPTS, _DRAFT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    require_draft_only_flag,
)
from disturbance_curriculum_audit import (  # noqa: E402
    LIVE_PUSH,
    refuse_overwrite_live_push,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
K1_STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
SNAPSHOT_REL = "bhuman/k1-training/manifests/domain-rand-disturbance-draft-validator-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
FACTOR = "C_disturbance_curriculum"

CHECKLIST = (
    "walk_live_push_friction_mass_frozen",
    "draft_only_disturbance_keys",
    "mass_friction_push_inventory",
    "apply_to_live_false",
    "validator_pass_not_live_dr",
)

LIVE_DR_NEEDLES = (
    "push_interval_s: 5.",
    "push_duration_s: 2.",
    "static_friction: 1.0",
    "dynamic_friction: 1.0",
    "base_mass:",
    "other_mass:",
)
LIVE_DR_RANGES = {
    "friction": "range: [0.3, 1.5]",
    "base_mass": "range: [0.8, 1.2]",
    "other_mass": "range: [0.98, 1.02]",
}
DRAFT_DR_FRAGMENTS = ("mass", "friction", "push_")
DOC_NEEDLES = (
    "domain_rand_disturbance_draft_validator",
    "apply_to_live=false",
    "push_interval_s",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
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
        f"domain-rand draft validator is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"domain-rand draft validator is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_apply_to_live(data: dict[str, Any]) -> None:
    refuse_as_official_config_patch(data)
    if data.get("apply_to_live") is True:
        raise ValueError("domain-rand / disturbance draft must not set apply_to_live")


def refuse_validator_pass_as_live_dr(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("validator-pass-as-live-dr claim must be a mapping")
    if (
        claim.get("validator_pass_as_live_dr")
        or claim.get("as_live_dr")
        or claim.get("apply_validator_pass")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and claim.get("live")
        )
    ):
        raise ValueError(
            "domain-rand draft validator PASS is not live DR; "
            "apply_to_live=false; official push_* / friction / mass stay frozen"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _load_draft(repo: Path) -> dict[str, Any]:
    path = repo / DRAFT_REL
    if not path.is_file():
        raise AssertionError(f"missing {DRAFT_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("walk-p1-factors draft must be a mapping")
    return data


def _inventory_draft_dr_keys(proposed: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for name in proposed:
        lowered = str(name).lower()
        if any(frag in lowered for frag in DRAFT_DR_FRAGMENTS):
            found.append(str(name))
    return found


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("domain-rand validator leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    _require_needles(yaml_text, LIVE_DR_NEEDLES, K1_YAML_REL)
    for label, needle in LIVE_DR_RANGES.items():
        if needle not in yaml_text:
            raise AssertionError(f"official {label} range drifted off {needle}")

    draft = _load_draft(repo)
    require_draft_only_flag(draft)
    refuse_apply_to_live(draft)
    factors = draft.get("factors") or {}
    disturbance = factors.get(FACTOR) or {}
    proposed = disturbance.get("proposed_only") or {}
    if disturbance.get("rewrites_344"):
        raise AssertionError("C_disturbance_curriculum must not rewrite 344")
    refuse_overwrite_live_push(
        {"target": "k1.yaml", "proposed_only": proposed, "keys": proposed}
    )
    draft_dr_keys = _inventory_draft_dr_keys(proposed)
    for key in draft_dr_keys:
        if str(proposed.get(key)) in {"5.0", "5.", 5.0, 5}:
            raise AssertionError("draft must stay proposed, not copy live push as applied")

    ball_text = (repo / K1_BALL_YAML_REL).read_text(encoding="utf-8")
    stand_text = (repo / K1_STAND_YAML_REL).read_text(encoding="utf-8")
    kick_note = {
        "task": "K1_Ball",
        "dims": "59→13",
        "has_ball_mass": "ball_mass:" in ball_text,
        "has_ball_friction": "ball_friction:" in ball_text,
        "is_walk_dr": False,
        "note": "kick randomization is a sibling; not the K1 walk DR curriculum",
    }
    standup_note = {
        "task": "K1_Stand_Up",
        "dims": "73→22",
        "has_base_mass": "base_mass:" in stand_text,
        "is_walk_dr": False,
        "note": "standup randomization is a sibling; not the K1 walk DR curriculum",
    }

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/domain_rand_disturbance_draft_validator.py",
        "checklist": list(CHECKLIST),
        "live_push": dict(LIVE_PUSH),
        "live_dr_ranges": dict(LIVE_DR_RANGES),
        "draft_rel": DRAFT_REL,
        "draft_only": True,
        "apply_to_live": False,
        "disturbance_proposed_only": dict(proposed),
        "draft_mass_friction_push_keys": draft_dr_keys,
        "kick_note": kick_note,
        "standup_note": standup_note,
        "validator_pass_as_live_dr": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "read-only draft mass/friction/push inventory; apply_to_live=false; "
            "validator PASS ≠ live DR"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
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
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_domain_rand_disturbance_draft_validator_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("domain-rand validator leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"domain-rand checklist drifted: {snap.get('checklist')}")
    if snap.get("apply_to_live") or snap.get("validator_pass_as_live_dr"):
        raise AssertionError("domain-rand leaked apply_to_live / live-DR")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("domain-rand leaked ready_gpu / would_train / GAP-closed")
    try:
        refuse_validator_pass_as_live_dr(
            {"validator_pass_as_live_dr": True, "as_live_dr": True, "this_pin": True}
        )
        raise AssertionError("refuse_validator_pass_as_live_dr must raise")
    except ValueError:
        pass
    try:
        refuse_overwrite_live_push(
            {"target": "k1.yaml", "keys": ["push_interval_s", "friction"]}
        )
        raise AssertionError("refuse_overwrite_live_push must raise")
    except ValueError:
        return snap
    raise AssertionError("refuse_overwrite_live_push must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("domain-rand draft validator imported Gym")

    yaml_path = repo / K1_YAML_REL
    ball = repo / K1_BALL_YAML_REL
    stand = repo / K1_STAND_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest() if ball.is_file() else ""
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_domain_rand_disturbance_draft_validator_frozen(repo)
        notes.append("assert_domain_rand_disturbance_draft_validator_frozen: apply_to_live=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        keys = snap.get("draft_mass_friction_push_keys") or []
        notes.append(
            "live walk push/friction/mass frozen; "
            f"draft mass/friction/push keys={keys or 'absent (honest)'}"
        )
        notes.append("validator PASS ≠ live DR")

    try:
        refuse_validator_pass_as_live_dr(
            {"status": "PASS", "live": True, "this_pin": True}
        )
        errors.append("validator_pass_as_live_dr must raise")
    except ValueError:
        notes.append("negative: validator PASS as live DR refused")
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
        (ball, before_ball, "K1_Ball.yaml"),
        (stand, before_stand, "K1_Stand_Up.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during domain-rand validator")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "validator_pass_as_live_dr": False,
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
        print(f"[domain-rand] FAIL {exc}")
        return 1
    print(
        f"[domain-rand] {snap.get('status')} "
        f"live push/friction/mass frozen; apply_to_live=false; "
        f"PASS ≠ live DR; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
