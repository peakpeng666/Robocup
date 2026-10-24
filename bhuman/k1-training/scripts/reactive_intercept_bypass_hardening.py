"""Reactive intercept bypass hardening (read-only overlay).

Deepens intercept_avoid_bypass + playball_not_kick_policy +
reactive_stub_hardening + skill_behavior_write_chain without replacing them:

  * TRAINABLE=false reaffirmed on intercept / PlayBall / reactive stubs
  * PlayBall ≠ kickPolicy (chain A pose only)
  * Intercept write-path inventory: InterceptBallInformation.intercept →
    MotionRequest.shouldInterceptBall (default false; stays walkPolicy 344→13)
  * apply_to_live=false
  * Overlay PASS is not a live kick deploy

Does not import teamcomm_shape_negatives or pr_volume_health_rescan.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/reactive_intercept_bypass_hardening.py
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

from intercept_avoid_bypass import (  # noqa: E402
    BYPASSES,
    TRAINABLE as INTERCEPT_TRAINABLE,
    refuse_intercept_as_kick_default,
)
from playball_not_kick_policy import (  # noqa: E402
    TRAINABLE as PLAYBALL_TRAINABLE,
    refuse_playball_as_kick_policy,
)
from reactive_stub_hardening import (  # noqa: E402
    TRAINABLE as REACTIVE_TRAINABLE,
    refuse_reactive_as_default_walk,
)
from skill_behavior_write_chain import (  # noqa: E402
    TRAINABLE as SBC_TRAINABLE,
    WRITE_SITES,
    refuse_intercept_info_writes_kick_policy,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/reactive-intercept-bypass-hardening-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
SBC_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
    "bhuman/k1-training/src/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
)
SBC_NEEDLE = "theMotionRequest.shouldInterceptBall = theInterceptBallInformation.intercept"

CHECKLIST = (
    "trainable_false_reaffirm",
    "playball_not_kick_policy",
    "intercept_write_path_inventory",
    "apply_to_live_false",
    "reactive_pass_not_live_kick_deploy",
)

DOC_NEEDLES = (
    "reactive_intercept_bypass_hardening",
    "apply_to_live=false",
    "shouldInterceptBall",
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
        f"reactive intercept bypass hardening is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"reactive intercept bypass hardening is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_reactive_pass_as_live_kick_deploy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("reactive-pass-as-live-kick-deploy claim must be a mapping")
    if (
        claim.get("reactive_pass_as_live_kick_deploy")
        or claim.get("as_live_kick_deploy")
        or claim.get("live_kick_deploy")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("live") or claim.get("live_kick"))
        )
    ):
        raise ValueError(
            "reactive intercept overlay PASS is not a live kick deploy; "
            "TRAINABLE=false; PlayBall ≠ kickPolicy; shouldInterceptBall stays walkPolicy"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _intercept_write_path() -> dict[str, Any]:
    site = next(
        (row for row in WRITE_SITES if row.get("id") == "intercept_info_to_motion_request"),
        None,
    )
    if site is None:
        raise AssertionError("WRITE_SITES missing intercept_info_to_motion_request")
    if site.get("from") != "InterceptBallInformation.intercept":
        raise AssertionError("intercept write-path from drifted")
    if site.get("to") != "MotionRequest.shouldInterceptBall":
        raise AssertionError("intercept write-path to drifted")
    if site.get("default") is not False:
        raise AssertionError("shouldInterceptBall default must stay false")
    if site.get("selects") != "walkPolicy" or site.get("contract") != "344→13":
        raise AssertionError("intercept write-path must stay walkPolicy 344→13")
    bypass = next((row for row in BYPASSES if row.get("id") == "shouldInterceptBall"), None)
    if bypass is None:
        raise AssertionError("BYPASSES missing shouldInterceptBall")
    if bypass.get("selects") != "walkPolicy":
        raise AssertionError("shouldInterceptBall bypass must stay walkPolicy")
    forbidden = set(bypass.get("not") or ())
    if not {"kick", "reactive", "T1"} <= forbidden:
        raise AssertionError("shouldInterceptBall bypass must refuse kick/reactive/T1")
    return {
        "id": site["id"],
        "from": site["from"],
        "to": site["to"],
        "default": False,
        "selects": "walkPolicy",
        "contract": "344→13",
        "bypass_id": bypass["id"],
        "not": sorted(forbidden),
    }


def _sbc_needle_present(repo: Path) -> bool:
    for rel in SBC_CPP_RELS:
        path = repo / rel
        if path.is_file() and SBC_NEEDLE in path.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if (
        TRAINABLE
        or WRITE_YAML
        or WRITE_CFG
        or APPLY_TO_LIVE
        or INTERCEPT_TRAINABLE
        or PLAYBALL_TRAINABLE
        or REACTIVE_TRAINABLE
        or SBC_TRAINABLE
    ):
        raise AssertionError("reactive intercept overlay leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    write_path = _intercept_write_path()
    sbc_ok = _sbc_needle_present(repo)
    if not sbc_ok:
        raise AssertionError(f"SkillBehaviorControl missing needle {SBC_NEEDLE!r}")

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
        "entry": "python3 bhuman/k1-training/scripts/reactive_intercept_bypass_hardening.py",
        "checklist": list(CHECKLIST),
        "trainable_reaffirm": {
            "overlay": False,
            "intercept_avoid_bypass": False,
            "playball_not_kick_policy": False,
            "reactive_stub_hardening": False,
            "skill_behavior_write_chain": False,
        },
        "playball_is_kick_policy": False,
        "intercept_write_path": write_path,
        "sbc_needle": SBC_NEEDLE,
        "sbc_needle_present": sbc_ok,
        "apply_to_live": False,
        "reactive_pass_as_live_kick_deploy": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "read-only intercept write-path inventory; TRAINABLE=false; "
            "PlayBall ≠ kickPolicy; overlay PASS ≠ live kick deploy"
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


def assert_reactive_intercept_bypass_hardening_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("reactive intercept overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"reactive intercept checklist drifted: {snap.get('checklist')}")
    if snap.get("apply_to_live") or snap.get("reactive_pass_as_live_kick_deploy"):
        raise AssertionError("reactive intercept leaked apply_to_live / live kick deploy")
    if snap.get("playball_is_kick_policy"):
        raise AssertionError("PlayBall must not be labeled kickPolicy")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("reactive intercept leaked ready_gpu / would_train / GAP-closed")
    try:
        refuse_reactive_pass_as_live_kick_deploy(
            {
                "reactive_pass_as_live_kick_deploy": True,
                "as_live_kick_deploy": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_reactive_pass_as_live_kick_deploy must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("reactive intercept overlay imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_reactive_intercept_bypass_hardening_frozen(repo)
        notes.append("assert_reactive_intercept_bypass_hardening_frozen: TRAINABLE=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        path = snap.get("intercept_write_path") or {}
        notes.append(
            f"intercept {path.get('from')} → {path.get('to')} "
            f"default={path.get('default')} selects={path.get('selects')}"
        )
        notes.append("PlayBall ≠ kickPolicy; overlay PASS ≠ live kick deploy")

    try:
        refuse_reactive_pass_as_live_kick_deploy(
            {"status": "PASS", "live_kick": True, "this_pin": True}
        )
        errors.append("reactive_pass_as_live_kick_deploy must raise")
    except ValueError:
        notes.append("negative: overlay PASS as live kick deploy refused")
    try:
        refuse_playball_as_kick_policy(
            {"playball_as_kick_policy": True, "source": "PlayBall"}
        )
        errors.append("refuse_playball_as_kick_policy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        refuse_intercept_as_kick_default(
            {"intercept_as_kick_default": True, "source": "shouldInterceptBall"}
        )
        errors.append("refuse_intercept_as_kick_default must raise")
    except ValueError:
        notes.append("negative: intercept as kick default refused")
    try:
        refuse_intercept_info_writes_kick_policy(
            {"intercept_info_writes_kick_policy": True, "source": "intercept"}
        )
        errors.append("refuse_intercept_info_writes_kick_policy must raise")
    except ValueError:
        notes.append("negative: intercept info writes kickPolicy refused")
    try:
        refuse_reactive_as_default_walk(
            {"reactive_as_default_walk": True, "source": "K1_Reactive"}
        )
        errors.append("refuse_reactive_as_default_walk must raise")
    except ValueError:
        notes.append("negative: reactive as default walk refused")
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
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during reactive intercept overlay")
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
        "reactive_pass_as_live_kick_deploy": False,
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
        print(f"[reactive-intercept] FAIL {exc}")
        return 1
    print(
        f"[reactive-intercept] {snap.get('status')} "
        f"TRAINABLE=false; PlayBall≠kickPolicy; "
        f"PASS ≠ live kick deploy; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
