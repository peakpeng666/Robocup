"""Read-only GetUp / standup apply-site dimensions (73→22).

Sibling of kick_policy_apply_dims / getup_engine_cfg_audit. This pin
records the *call site*, not a second cfg parse:

  compile()  policy 73 in / 22 out (K1.onnx)
  apply()    engine.policy.apply() when tryCounter > 0 (regular)

Fast 72→22 is a different slot (policyFast); see fast_standup_isolation.
standup→walk 13-zero last_action is already closed in last_action_reset /
force_walk_afterwards — referenced, not re-implemented.

Entry allowlist (MotionEngine): fallen + (fall|playDead) + not playDead
request → GetUpGenerator.createPhase. Unexpected walk-net / T1 / Huoshen
entry is FAIL.

Never writes getUpEngine.cfg, walkingEngine.cfg, or K1.yaml.
TRAINABLE=false. walk↔kick resetHistoryData GAP stays open (draft only).
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

from getup_engine_cfg_audit import (  # noqa: E402
    FAST_ONNX,
    GETUP_ONNX,
    parse_getup_fields,
)
from last_action_reset import cross_assert_return_to_walk  # noqa: E402
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
WALK_ONNX = "K1_walk.onnx"
KICK_ONNX = "K1_kick_inner.onnx"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STANDUP_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/standup-policy-apply-dims-latest.json"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
)
GETUP_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
)
MOTION_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
)
ABSENT_GETUP_CFG = (
    "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/getUpEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/getUpEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/getUpEngine.cfg",
)
STANDUP_ONNX_ALLOW = (GETUP_ONNX,)
CPP_NEEDLES = (
    "void GetUpEngine::compile",
    "policy.compile(Model(modelPath + policyName))",
    "policy.input(0).dims(0) == numInput",
    "policy.output(0).dims(0) == numOutput",
    "void GetUpPhase::executePolicy",
    "engine.policy.apply()",
    "executedTime / maxStandUpTime",
    "Force walk afterwards",
)
H_NEEDLES = (
    "CompiledNN policy",
    "CompiledNN policyFast",
    "NeuralNets/GetUpEngine/",
)
MOTION_NEEDLES = (
    "theFallDownState.state == FallDownState::fallen",
    "theGetUpGenerator.createPhase",
    "MotionPhase::fall",
    "MotionPhase::playDead",
)
CPP_FORBIDDEN = (
    "walkPolicy.apply",
    "kickPolicy.apply",
    "K1_walk.onnx",
    "K1_kick_inner",
    "T1.onnx",
    "HiFAR",
    "huoshen",
)
ENTRY_ALLOW = (
    "FallDownState::fallen",
    "MotionPhase::fall | MotionPhase::playDead",
    "motionRequest.motion != playDead",
    "GetUpGenerator.createPhase",
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
        f"standup apply-dims audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"standup apply-dims audit is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_standup_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-as-walk-344 claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("standup_as_walk_344")
        or claim.get("getup_obs_is_344")
        or claim.get("policy_numInput") == WALK_OBS
        or (
            source
            in {
                "policy",
                "GetUpEngine",
                "standup",
                "K1.onnx",
                "executePolicy",
            }
            and (
                claim.get("walk_obs") == WALK_OBS
                or claim.get("numInput") == WALK_OBS
                or claim.get("contract") == "344→13"
                or claim.get("modelName") == WALK_ONNX
            )
        )
    ):
        raise ValueError(
            "standup apply-site is 73→22 / K1.onnx; it is not walk 344→13 "
            "and must not occupy K1_walk.onnx"
        )


def refuse_getup_as_hot_swap_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("getup-as-hot-swap-train claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("getup_as_hot_swap_train")
        or claim.get("train_graph")
        or claim.get("hot_swap_train")
        or claim.get("writes_k1_yaml")
        or (
            source
            in {
                "GetUpEngine",
                "executePolicy",
                "policy.apply",
                "K1.onnx",
            }
            and (
                claim.get("train_py")
                or claim.get("isaac")
                or claim.get("config_patch")
            )
        )
    ):
        raise ValueError(
            "GetUpEngine apply is a deploy CompiledNN bypass; "
            "it is not a hot-swap into K1.yaml / train.py / Isaac"
        )


def refuse_standup_onnx_as_kick_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-onnx-as-kick-slot claim must be a mapping")
    name = str(claim.get("source") or claim.get("name") or claim.get("policyName") or "")
    dest = str(claim.get("dest") or claim.get("slot") or "")
    if (
        claim.get("standup_onnx_as_kick_slot")
        or claim.get("kick_slot")
        or name in {GETUP_ONNX, FAST_ONNX}
        and (
            claim.get("kick_slot") is True
            or "kick" in dest.lower()
            or claim.get("numInput") == KICK_OBS
            or claim.get("contract") == "59→13"
        )
    ):
        raise ValueError(
            "K1.onnx / K1_fast_standup.onnx must not occupy the kick 59→13 slot"
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
        "standup": "73→22",
        "note": "do not invent standup apply dims when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("standup apply-dims leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    cfg_path = repo / GETUP_CFG_REL
    cpp_rel = next((rel for rel in GETUP_CPP_RELS if (repo / rel).is_file()), None)
    motion_rel = next((rel for rel in MOTION_CPP_RELS if (repo / rel).is_file()), None)
    if not cfg_path.is_file() or not cpp_rel:
        return _skip_source("Default getUpEngine.cfg or GetUpEngine.cpp missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    standup_yaml = repo / STANDUP_YAML_REL
    if standup_yaml.is_file():
        su = standup_yaml.read_text(encoding="utf-8")
        if "num_observations: 73" not in su or "num_actions: 22" not in su:
            raise AssertionError("K1_Stand_Up.yaml drifted off 73→22")

    fields = parse_getup_fields(cfg_path.read_text(encoding="utf-8"))
    if fields.get("policyName") != GETUP_ONNX:
        raise AssertionError(f"regular policyName={fields.get('policyName')} ≠ K1.onnx")
    if fields.get("numInput") != str(STANDUP_OBS) or fields.get("numOutput") != str(STANDUP_ACT):
        raise AssertionError("regular getUp slot drifted off 73→22")
    if fields.get("policyName") in {WALK_ONNX, KICK_ONNX, FAST_ONNX}:
        raise AssertionError("regular getUp ONNX collided with walk/kick/fast")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing standup apply needles {missing}")
    leaked = [n for n in CPP_FORBIDDEN if n in cpp_text]
    if leaked:
        raise AssertionError(f"{cpp_rel} leaked walk/kick/T1/HiFAR tokens {leaked}")
    if "engine.policyFast.apply()" not in cpp_text:
        raise AssertionError("fast apply site missing (isolation sibling still required)")

    h_rel = next((rel for rel in GETUP_H_RELS if (repo / rel).is_file()), None)
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing CompiledNN needles {missing_h}")

    if not motion_rel:
        return _skip_source("MotionEngine.cpp missing; entry allowlist not fabricated")
    motion_text = (repo / motion_rel).read_text(encoding="utf-8", errors="replace")
    missing_m = [n for n in MOTION_NEEDLES if n not in motion_text]
    if missing_m:
        raise AssertionError(f"{motion_rel} missing GetUp entry needles {missing_m}")

    role_diff: dict[str, Any] = {
        "Default": {
            "cfg": GETUP_CFG_REL,
            "present": True,
            "contract": "73→22",
            "onnx": GETUP_ONNX,
        },
        "Simulated": {
            "cfg": ABSENT_GETUP_CFG[0],
            "present": (repo / ABSENT_GETUP_CFG[0]).is_file(),
            "note": "no Simulated getUpEngine.cfg; cpp forces fastActive=false",
        },
        "Competition": {
            "cfg": ABSENT_GETUP_CFG[1],
            "present": (repo / ABSENT_GETUP_CFG[1]).is_file(),
            "note": "no Competition getUpEngine.cfg; not fabricating",
        },
    }
    if role_diff["Simulated"]["present"] or role_diff["Competition"]["present"]:
        raise AssertionError("unexpected Simulated/Competition getUpEngine.cfg appeared")

    handoff = cross_assert_return_to_walk()
    empty = map_skill_request(None)
    if not empty.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "cfg": GETUP_CFG_REL,
            "cpp": cpp_rel,
            "header": h_rel,
            "motion": motion_rel,
        },
        "apply_sites": {
            "regular": {
                "slot": "policy",
                "call": "engine.policy.apply()",
                "when": "tryCounter > 0",
                "contract": "73→22",
                "onnx_allow": list(STANDUP_ONNX_ALLOW),
                "fill": "gravity3 + gyro3 + phase1 + 22*(measured+vel+lastRequest)",
                "not_walk": True,
                "not_kick": True,
                "not_fast": True,
            },
            "fast": {
                "slot": "policyFast",
                "call": "engine.policyFast.apply()",
                "when": "tryCounter == 0",
                "contract": "72→22",
                "isolated_here": True,
                "see": "fast_standup_isolation.py",
            },
        },
        "entry_allow": list(ENTRY_ALLOW),
        "role_diff": role_diff,
        "handoff_13_zero": {
            "closed_elsewhere": True,
            "source": "last_action_reset.py / force_walk_afterwards.py",
            "ok": bool(handoff),
        },
        "walk_slot": {
            "modelName": WALK_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
        },
        "standup_as_walk_344": False,
        "getup_as_hot_swap_train": False,
        "standup_onnx_as_kick_slot": False,
        "walk_kick_gap_closed": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "regular GetUp apply is 73→22 / K1.onnx; ≠ walk 344 / kick 59 / "
            "fast 72; entry = fallen+(fall|playDead); 13-zero handoff already closed"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "standup_contract": "73→22",
        "fast_contract": "72→22",
        "cfg_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
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


def assert_standup_apply_dims_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("standup apply-dims leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate standup apply dims")
        return snap
    regular = (snap.get("apply_sites") or {}).get("regular") or {}
    if regular.get("contract") != "73→22" or regular.get("onnx_allow") != list(STANDUP_ONNX_ALLOW):
        raise AssertionError("regular standup apply must stay 73→22 / K1.onnx")
    if snap.get("standup_as_walk_344") or snap.get("getup_as_hot_swap_train"):
        raise AssertionError("standup apply flags leaked walk/train")
    if snap.get("standup_onnx_as_kick_slot") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("standup-as-kick or walk↔kick GAP-closed leaked")
    if not (snap.get("handoff_13_zero") or {}).get("closed_elsewhere"):
        raise AssertionError("must reference existing 13-zero handoff, not re-close it")
    try:
        refuse_standup_as_walk_344(
            {"standup_as_walk_344": True, "source": "policy", "numInput": WALK_OBS}
        )
        raise AssertionError("refuse_standup_as_walk_344 must raise")
    except ValueError:
        pass
    try:
        refuse_getup_as_hot_swap_train(
            {"getup_as_hot_swap_train": True, "source": "GetUpEngine", "train_graph": True}
        )
        raise AssertionError("refuse_getup_as_hot_swap_train must raise")
    except ValueError:
        pass
    try:
        refuse_standup_onnx_as_kick_slot(
            {
                "standup_onnx_as_kick_slot": True,
                "source": GETUP_ONNX,
                "kick_slot": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_standup_onnx_as_kick_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("standup apply-dims imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_standup_apply_dims_frozen(repo)
        notes.append("assert_standup_apply_dims_frozen: regular apply 73→22")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "GetUpEngine.cpp missing"))
        notes.append("honest SKIP: standup apply dims not fabricated")
    elif snap:
        notes.append("regular GetUp apply 73→22 / K1.onnx; ≠ walk 344 / kick 59")
        notes.append("entry = fallen + (fall|playDead); 13-zero handoff referenced")
        notes.append("no Simulated/Competition getUpEngine.cfg (not fabricated)")

    for fn, claim, label in (
        (
            refuse_standup_as_walk_344,
            {"standup_as_walk_344": True, "source": "policy", "numInput": WALK_OBS},
            "standup as walk 344",
        ),
        (
            refuse_getup_as_hot_swap_train,
            {"getup_as_hot_swap_train": True, "source": "GetUpEngine", "train_graph": True},
            "GetUp as hot-swap train",
        ),
        (
            refuse_standup_onnx_as_kick_slot,
            {"standup_onnx_as_kick_slot": True, "source": GETUP_ONNX, "kick_slot": True},
            "standup ONNX as kick slot",
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
        refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of getUpEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during standup apply-dims audit")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during standup apply-dims audit")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during standup apply-dims audit")
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
        "standup": "73→22",
        "standup_as_walk_344": False,
        "getup_as_hot_swap_train": False,
        "standup_onnx_as_kick_slot": False,
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
        print(f"[standup-apply] FAIL {exc}")
        return 1
    regular = (snap.get("apply_sites") or {}).get("regular") or {}
    print(
        f"[standup-apply] {snap.get('status')} "
        f"regular={regular.get('contract')} / {regular.get('onnx_allow')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
