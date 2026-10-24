"""Read-only walk↔kick last_action / history-buffer contract.

Sibling of last_action_reset (standup→walk 13-zero) and the apply-site
pins. This pin records *actual* WalkingEngine behaviour:

  resetHistoryData()  WalkingEngine ctor + WalkPhase ctor when lastPhase
                      is not a WalkPhase (not walk/stand continuation)
  updateHistoryData(lastTarget)  every getNextTargetRequest
  walk fill   historyBuffer (10 frames, lastActions) → walkPolicy 344
  kick fill   current sensors + lastTarget → kickPolicy 59

getNextTargetRequest walk↔kick does **not** call resetHistoryData.
That is an honest GAP, not a closed zero. Do not fake-green.

Walk 344 frames are not memcpy'd into kick 59 (or vice versa).
Switching the compiled bypass ≠ hot-swap into K1.yaml / train.py.

Never writes walkingEngine.cfg or K1.yaml. TRAINABLE=false.
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
HISTORY_FRAMES = 10
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/policy-switch-last-action-latest.json"
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
CPP_NEEDLES = (
    "void WalkingEngine::resetHistoryData()",
    "void WalkingEngine::updateHistoryData",
    "historyBuffer.clear()",
    "nextDataPoint.lastActions = JointAngles()",
    "engine.updateHistoryData(lastTarget)",
    "engine.resetHistoryData()",
    "engine.walkPolicy.apply()",
    "policy.apply()",
    "*input++ = data.lastActions.angles[j]",
    "*input++ = lastTarget.angles[j]",
    "*input++ = 0.f; // Dummy Ball x",
)
H_NEEDLES = (
    "void resetHistoryData()",
    "void updateHistoryData(const JointAngles& lastAction, const bool init = false)",
    "JointAngles lastActions",
    "RingBuffer<HistoryData, 10> historyBuffer",
)
# Must NOT appear as a walk↔kick zero inside getNextTargetRequest.
SWITCH_ZERO_NEEDLES = (
    "resetHistoryData();",
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
        f"policy-switch last_action audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"policy-switch last_action audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_switch_keeps_stale_last_action(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("stale-last-action claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("switch_keeps_stale_last_action")
        or claim.get("gap_closed")
        or claim.get("explicit_zero_on_walk_kick")
        or (
            source
            in {
                "walk↔kick",
                "walk_kick_switch",
                "getNextTargetRequest",
                "last_action",
                "lastTarget",
            }
            and (
                claim.get("closed")
                or claim.get("train_graph")
                or claim.get("obs_reuse")
                or claim.get("walk_344_into_kick_59")
            )
        )
    ):
        raise ValueError(
            "walk↔kick has no explicit last_action zero in getNextTargetRequest "
            "(honest GAP); keeping lastTarget must not be sold as a closed reset "
            "or as stuffing walk 344 history into kick 59 / train.py"
        )


def refuse_buffer_cross_dim_reuse(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("buffer-cross-dim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("buffer_cross_dim_reuse")
        or claim.get("walk_344_into_kick_59")
        or claim.get("kick_59_into_walk_344")
        or (
            source
            in {
                "historyBuffer",
                "walk_history",
                "kick_input",
                "lastActions",
            }
            and (
                claim.get("memcpy_344_to_59")
                or claim.get("numInput") in {WALK_OBS, KICK_OBS}
                and claim.get("reuse_other_slot")
            )
        )
    ):
        raise ValueError(
            "walk fills 344 from historyBuffer; kick fills 59 from current "
            "sensors + lastTarget; do not memcpy walk frames into kick or vice versa"
        )


def _assert_slot(flat: dict[str, str], label: str) -> None:
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in SLOT_KEYS.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


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
        "switch_keeps_stale_last_action": False,
        "buffer_cross_dim_reuse": False,
        "last_action_zero_on_walk_kick_switch": {
            "status": "SKIP",
            "explicit": False,
            "fabricated": False,
            "note": "do not invent a last_action zero when source is missing",
        },
        "note": "do not invent walk↔kick buffer behaviour when source is missing",
    }


def _getnext_has_reset(cpp_text: str) -> bool:
    start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    if start < 0:
        return False
    end = cpp_text.find("\nvoid ", start + 1)
    body = cpp_text[start:end] if end > start else cpp_text[start:]
    return any(n in body for n in SWITCH_ZERO_NEEDLES)


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("policy-switch last_action audit leaked TRAINABLE/WRITE flags")
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
        raise AssertionError(f"{cpp_rel} missing last_action needles {missing}")
    if "RingBuffer<HistoryData, 10>" not in cpp_text and "historyBuffer" not in cpp_text:
        raise AssertionError(f"{cpp_rel} missing historyBuffer")

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing history needles {missing_h}")
        h_needles = list(H_NEEDLES)

    explicit_zero = _getnext_has_reset(cpp_text)
    if explicit_zero:
        # Official tree as of this pin has no reset inside getNextTargetRequest.
        # A sudden appearance is a contract change, not a fake-green close.
        raise AssertionError(
            "getNextTargetRequest now calls resetHistoryData; "
            "re-audit before claiming the GAP is closed"
        )

    empty = map_skill_request(None)
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext())
    if not empty.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13":
        raise AssertionError("want_kick must still select kick 59→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "reset_history_when": [
            "WalkingEngine constructor",
            "WalkPhase ctor when lastPhase is not a continuing WalkPhase",
        ],
        "update_history_when": "every WalkPhase::getNextTargetRequest via lastTarget",
        "history_frames": HISTORY_FRAMES,
        "walk_obs_fill": {
            "source": "historyBuffer lastActions + measured + gravity/gyro",
            "contract": "344→13",
            "call": "engine.walkPolicy.apply()",
        },
        "kick_obs_fill": {
            "source": "current sensors + lastTarget (not historyBuffer)",
            "contract": "59→13",
            "call": "policy.apply()",
        },
        "last_action_zero_on_walk_kick_switch": {
            "status": "GAP",
            "explicit": False,
            "fabricated": False,
            "note": (
                "getNextTargetRequest walk↔kick does not call resetHistoryData; "
                "lastTarget continues; do not mark this closed"
            ),
        },
        "cross_dim_obs_reuse": False,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "skill_request": {
            "empty": {"skill": empty.skill, "contract": empty.contract},
            "want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        },
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "switch_keeps_stale_last_action": False,
        "buffer_cross_dim_reuse": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "walk 344 from historyBuffer; kick 59 from current lastTarget; "
            "no explicit last_action zero on walk↔kick (honest GAP); "
            "switch ≠ hot-swap into K1.yaml / train.py"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "kick_contract": "59→13",
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


def assert_policy_switch_last_action_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("policy-switch last_action audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate last_action zero")
        gap = snap.get("last_action_zero_on_walk_kick_switch") or {}
        if gap.get("status") not in {"SKIP", "GAP"} or gap.get("fabricated"):
            raise AssertionError("missing-source last_action zero must stay SKIP/GAP")
        return snap
    if snap.get("switch_keeps_stale_last_action") or snap.get("buffer_cross_dim_reuse"):
        raise AssertionError("stale last_action / cross-dim reuse must stay refused")
    if snap.get("cross_dim_obs_reuse"):
        raise AssertionError("walk 344 must not be marked as reused into kick 59")
    gap = snap.get("last_action_zero_on_walk_kick_switch") or {}
    if gap.get("status") != "GAP" or gap.get("explicit") or gap.get("fabricated"):
        raise AssertionError("walk↔kick last_action zero must stay an honest GAP")
    if snap.get("history_frames") != HISTORY_FRAMES:
        raise AssertionError("historyBuffer must stay 10 frames")
    walk = snap.get("walk_obs_fill") or {}
    kick = snap.get("kick_obs_fill") or {}
    if walk.get("contract") != "344→13" or kick.get("contract") != "59→13":
        raise AssertionError("walk/kick fill contracts drifted")
    if "historyBuffer" not in str(walk.get("source")) or "lastTarget" not in str(kick.get("source")):
        raise AssertionError("walk must use historyBuffer; kick must use lastTarget")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("kick_numInput") != KICK_OBS:
        raise AssertionError("walk 344 / kick 59 slots drifted")
    try:
        refuse_switch_keeps_stale_last_action(
            {
                "switch_keeps_stale_last_action": True,
                "source": "getNextTargetRequest",
                "closed": True,
            }
        )
        raise AssertionError("refuse_switch_keeps_stale_last_action must raise")
    except ValueError:
        pass
    try:
        refuse_buffer_cross_dim_reuse(
            {
                "buffer_cross_dim_reuse": True,
                "source": "historyBuffer",
                "walk_344_into_kick_59": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_buffer_cross_dim_reuse must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("policy-switch last_action audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_policy_switch_last_action_frozen(repo)
        notes.append("assert_policy_switch_last_action_frozen: GAP zero; no 344↔59 reuse")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: last_action switch contract not fabricated")
    elif snap:
        gap = snap.get("last_action_zero_on_walk_kick_switch") or {}
        notes.append(
            f"walk↔kick last_action zero is {gap.get('status')} "
            "(no resetHistoryData in getNextTargetRequest)"
        )
        notes.append("walk 344 from historyBuffer; kick 59 from current lastTarget")
        notes.append("switch ≠ hot-swap into K1.yaml / train.py")

    for fn, claim, label in (
        (
            refuse_switch_keeps_stale_last_action,
            {
                "switch_keeps_stale_last_action": True,
                "source": "getNextTargetRequest",
                "closed": True,
            },
            "switch keeps stale last_action as closed reset",
        ),
        (
            refuse_buffer_cross_dim_reuse,
            {
                "buffer_cross_dim_reuse": True,
                "source": "historyBuffer",
                "walk_344_into_kick_59": True,
            },
            "buffer cross-dim reuse 344↔59",
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
            errors.append("K1.yaml changed during policy-switch last_action audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during last_action audit")
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
        "kick": "59→13",
        "switch_keeps_stale_last_action": False,
        "buffer_cross_dim_reuse": False,
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
        print(f"[switch-last] FAIL {exc}")
        return 1
    gap = snap.get("last_action_zero_on_walk_kick_switch") or {}
    print(
        f"[switch-last] {snap.get('status')} last_action zero={gap.get('status')}; "
        f"no 344↔59 reuse; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
