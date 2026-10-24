"""Observation history-window contract (read-only; no GPU).

Shapes / lengths:

  * walk    K1           344→13  = 10×32+24  (history_size 10)
  * kick    K1_Ball       59→13  current-frame; no walk history window
  * standup K1_Stand_Up   73→22  current-frame; no walk history window

Cross-skill history reuse without resetHistoryData is the open GAP.
Does not replace history_buffer_shape / policy_switch_history_gap / obs_schema.

TRAINABLE=false. apply_to_live=false.
Does not import reward_curriculum_draft_validator or ci_gate_wiring.

Runnable: python3 bhuman/k1-training/scripts/obs_history_window_contract.py
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
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from history_buffer_shape import FORMULA  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS = 344
WALK_ACT = 13
WALK_HISTORY = 10
WALK_FRAME = 32
WALK_TAIL = 24
KICK_OBS = 59
KICK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
K1_STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/obs-history-window-contract-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
GAP_DOC_REL = "bhuman/docs/POLICY-SWITCH-HISTORY-GAP.md"

CHECKLIST = (
    "walk_344_10x32_24",
    "kick_59_no_walk_window",
    "standup_73_no_walk_window",
    "cross_skill_reuse_is_gap",
    "gap_closed_false",
)

WINDOWS = {
    "walk": {
        "task": "K1",
        "obs": WALK_OBS,
        "act": WALK_ACT,
        "dims": "344→13",
        "history_size": WALK_HISTORY,
        "frame": WALK_FRAME,
        "tail": WALK_TAIL,
        "formula": FORMULA,
    },
    "kick": {
        "task": "K1_Ball",
        "obs": KICK_OBS,
        "act": KICK_ACT,
        "dims": "59→13",
        "history_size": None,
        "walk_window": False,
        "note": "current-frame 59; does not eat walk 10×32 historyBuffer",
    },
    "standup": {
        "task": "K1_Stand_Up",
        "obs": STANDUP_OBS,
        "act": STANDUP_ACT,
        "dims": "73→22",
        "history_size": None,
        "walk_window": False,
        "note": "current-frame 73; standup 13-zero ≠ this walk↔kick GAP",
    },
}

DOC_NEEDLES = (
    "obs_history_window_contract",
    "344→13",
    "59→13",
    "73→22",
    "10×32+24",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "competition_ready=true",
)
GAP_DOC_NEEDLES = (
    "obs_history_window_contract",
    "344→13",
    "59→13",
    "73→22",
    "gap_closed=false",
)
GAP_DOC_FORBIDDEN = (
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
        f"obs history-window contract is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"obs history-window contract is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_walk_window_as_kick(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-window-as-kick claim must be a mapping")
    if (
        claim.get("walk_window_as_kick")
        or claim.get("reuse_344_as_59")
        or (
            claim.get("from_obs") == 344
            and claim.get("to_obs") == 59
            and not claim.get("reset")
        )
    ):
        raise ValueError(
            "walk 344 10×32+24 window must not be reused as kick 59 without reset; "
            "that cross-skill reuse is the open GAP"
        )


def refuse_cross_skill_history_reuse_as_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("cross-skill-history-reuse-as-closed claim must be a mapping")
    if (
        claim.get("cross_skill_history_reuse_as_closed")
        or claim.get("gap_closed") is True
        or claim.get("reuse_without_reset_ok")
        or claim.get("history_reuse_closed")
    ):
        raise ValueError(
            "cross-skill history reuse without resetHistoryData stays an open GAP; "
            "gap_closed=false; draft only"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _require_yaml_dims(path: Path, obs: int, act: int, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    if f"num_observations: {obs}" not in text or f"num_actions: {act}" not in text:
        raise AssertionError(f"{label} drifted off {obs}→{act}")
    return text


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("history-window contract leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    walk_text = _require_yaml_dims(repo / K1_YAML_REL, WALK_OBS, WALK_ACT, "K1.yaml")
    kick_text = _require_yaml_dims(repo / K1_BALL_YAML_REL, KICK_OBS, KICK_ACT, "K1_Ball.yaml")
    stand_text = _require_yaml_dims(
        repo / K1_STAND_YAML_REL, STANDUP_OBS, STANDUP_ACT, "K1_Stand_Up.yaml"
    )
    if "history_size: 10" not in walk_text or "num_base_observations: 32" not in walk_text:
        raise AssertionError("official walk history window drifted off 10×32")
    if "num_last_observations: 24" not in walk_text:
        raise AssertionError("official walk tail drifted off 24")
    if WALK_HISTORY * WALK_FRAME + WALK_TAIL != WALK_OBS:
        raise AssertionError("walk formula 10×32+24 drifted off 344")
    if "history_size:" in kick_text or "history_size:" in stand_text:
        raise AssertionError("kick/standup unexpectedly grew a walk history_size")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    gap_doc = repo / GAP_DOC_REL
    if not compat.is_file() or not artifacts.is_file() or not gap_doc.is_file():
        raise AssertionError("COMPAT / ARTIFACTS / POLICY-SWITCH-HISTORY-GAP missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    gap_text = gap_doc.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(gap_text, GAP_DOC_NEEDLES, GAP_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(gap_text, GAP_DOC_FORBIDDEN, GAP_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/obs_history_window_contract.py",
        "checklist": list(CHECKLIST),
        "windows": WINDOWS,
        "formula": FORMULA,
        "cross_skill_history_reuse_as_closed": False,
        "walk_window_as_kick": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "walk 10×32+24=344 vs kick 59 vs standup 73; "
            "cross-skill reuse without reset is the open GAP"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
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


def assert_obs_history_window_contract_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("history-window contract leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"history-window checklist drifted: {snap.get('checklist')}")
    if snap.get("gap_closed") or snap.get("cross_skill_history_reuse_as_closed"):
        raise AssertionError("history-window leaked GAP-closed")
    if snap.get("windows", {}).get("walk", {}).get("formula") != FORMULA:
        raise AssertionError("walk formula drifted")
    try:
        refuse_cross_skill_history_reuse_as_closed(
            {"cross_skill_history_reuse_as_closed": True, "gap_closed": True}
        )
        raise AssertionError("refuse_cross_skill_history_reuse_as_closed must raise")
    except ValueError:
        pass
    try:
        refuse_walk_window_as_kick(
            {"walk_window_as_kick": True, "from_obs": 344, "to_obs": 59}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_walk_window_as_kick must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("obs history-window contract imported Gym")

    yaml_path = repo / K1_YAML_REL
    ball = repo / K1_BALL_YAML_REL
    stand = repo / K1_STAND_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest() if ball.is_file() else ""
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_obs_history_window_contract_frozen(repo)
        notes.append("assert_obs_history_window_contract_frozen: GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("walk 10×32+24=344; kick 59 / standup 73 have no walk window")
        notes.append("cross-skill reuse without reset stays the open GAP")

    try:
        refuse_cross_skill_history_reuse_as_closed({"reuse_without_reset_ok": True})
        errors.append("cross_skill_history_reuse_as_closed must raise")
    except ValueError:
        notes.append("negative: cross-skill history reuse as closed refused")
    try:
        refuse_walk_window_as_kick({"from_obs": 344, "to_obs": 59, "reset": False})
        errors.append("walk_window_as_kick must raise")
    except ValueError:
        notes.append("negative: walk 344 window as kick 59 refused")
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
                errors.append(f"{label} changed during history-window contract")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "gap_closed": False,
        "cross_skill_history_reuse_as_closed": False,
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
        print(f"[history-window] FAIL {exc}")
        return 1
    print(
        f"[history-window] {snap.get('status')} "
        f"walk 10×32+24=344 / kick 59 / standup 73; "
        f"cross-skill reuse GAP open; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
