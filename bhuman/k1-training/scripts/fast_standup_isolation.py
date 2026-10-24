"""Read-only fast standup isolation (72→22 ≠ regular 73→22).

Sibling of standup_policy_apply_dims. This pin records the *fast* slot:

  compile()  policyFast 72 in / 22 out (K1_fast_standup.onnx)
  apply()    engine.policyFast.apply() when tryCounter == 0

Regular standup is 73→22 / K1.onnx (policy.apply). Fast has no phase
term. Simulated forces fastActive=false in GetUpEngine ctor — no
separate Simulated getUpEngine.cfg (do not fabricate).

Fast 72→22 is deploy-only: not Isaac, not walk 344, not kick 59, not
T1/Huoshen/HiFAR. standup→walk 13-zero is already closed elsewhere.

Never writes getUpEngine.cfg, walkingEngine.cfg, or K1.yaml.
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
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
WALK_ONNX = "K1_walk.onnx"
KICK_ONNX = "K1_kick_inner.onnx"
T1_GETUP_ONNX = "T1.onnx"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/fast-standup-isolation-latest.json"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
)
ENV_INIT_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py",
    "bhuman/MachineLearning/IsaacGymRL/envs/__init__.py",
)
ABSENT_GETUP_CFG = (
    "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/getUpEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/getUpEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/getUpEngine.cfg",
)
FAST_ONNX_ALLOW = (FAST_ONNX,)
CPP_NEEDLES = (
    "policyFast.compile(Model(modelPath + policyNameFast))",
    "policyFast.input(0).dims(0) == numInputFast",
    "policyFast.output(0).dims(0) == numOutputFast",
    "engine.policyFast.apply()",
    "if(SystemCall::getMode() == SystemCall::simulatedRobot)",
    "fastActive = false",
    "engine.policyFast.input(0).data()",
)
CPP_FORBIDDEN = (
    "walkPolicy.apply",
    "K1_walk.onnx",
    "K1_kick_inner",
    "T1.onnx",
    "HiFAR",
    "huoshen",
)
FAST_FILL_HAS_NO_PHASE = "executedTime / maxStandUpTime"


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
        f"fast-standup isolation is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"fast-standup isolation is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_fast_as_regular_standup(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("fast-as-regular-standup claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("fast_as_regular_standup")
        or claim.get("fast_is_73")
        or claim.get("same_as_regular")
        or (
            source
            in {
                "policyFast",
                "K1_fast_standup.onnx",
                "fast_standup",
                "72→22",
            }
            and (
                claim.get("numInput") == STANDUP_OBS
                or claim.get("contract") == "73→22"
                or claim.get("policyName") == GETUP_ONNX
                or claim.get("as_regular")
            )
        )
    ):
        raise ValueError(
            "fast standup is 72→22 / K1_fast_standup.onnx; "
            "it is not regular standup 73→22 / K1.onnx"
        )


def _fast_body_has_phase(cpp_text: str) -> bool:
    start = cpp_text.find("engine.policyFast.input(0).data()")
    if start < 0:
        return False
    end = cpp_text.find("engine.policyFast.apply()", start)
    body = cpp_text[start:end] if end > start else cpp_text[start : start + 800]
    return FAST_FILL_HAS_NO_PHASE in body


def _isaac_registers_fast(repo: Path) -> bool:
    for rel in ENV_INIT_RELS:
        path = repo / rel
        if path.is_file() and "K1_fast_standup" in path.read_text(encoding="utf-8"):
            return True
    return False


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
        "fast_standup": "72→22",
        "note": "do not invent fast-standup isolation when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("fast-standup isolation leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    cfg_path = repo / GETUP_CFG_REL
    cpp_rel = next((rel for rel in GETUP_CPP_RELS if (repo / rel).is_file()), None)
    if not cfg_path.is_file() or not cpp_rel:
        return _skip_source("Default getUpEngine.cfg or GetUpEngine.cpp missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    fields = parse_getup_fields(cfg_path.read_text(encoding="utf-8"))
    if fields.get("policyNameFast") != FAST_ONNX:
        raise AssertionError(
            f"policyNameFast={fields.get('policyNameFast')} ≠ {FAST_ONNX}"
        )
    if fields.get("numInputFast") != str(FAST_OBS) or fields.get("numOutputFast") != str(
        FAST_ACT
    ):
        raise AssertionError("fast getUp slot drifted off 72→22")
    if fields.get("policyName") != GETUP_ONNX:
        raise AssertionError("regular slot must stay K1.onnx while isolating fast")
    if fields.get("numInput") != str(STANDUP_OBS):
        raise AssertionError("regular slot must stay 73 while isolating fast")
    if fields.get("policyNameFast") in {GETUP_ONNX, WALK_ONNX, KICK_ONNX, T1_GETUP_ONNX}:
        raise AssertionError("fast ONNX collided with regular/walk/kick/T1")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing fast-isolation needles {missing}")
    leaked = [n for n in CPP_FORBIDDEN if n in cpp_text]
    if leaked:
        raise AssertionError(f"{cpp_rel} leaked walk/kick/T1/HiFAR tokens {leaked}")
    if _fast_body_has_phase(cpp_text):
        raise AssertionError("fast fill must not include the regular phase term")
    if "engine.policy.apply()" not in cpp_text:
        raise AssertionError("regular apply site missing (must stay isolated)")
    if _isaac_registers_fast(repo):
        raise AssertionError("K1_fast_standup must not be registered in Isaac envs")

    absent = {rel: (repo / rel).is_file() for rel in ABSENT_GETUP_CFG}
    if any(absent.values()):
        raise AssertionError(
            "unexpected Simulated/Competition getUpEngine.cfg; do not silently adopt it"
        )

    handoff = cross_assert_return_to_walk()
    empty = map_skill_request(None)
    if not empty.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {"cfg": GETUP_CFG_REL, "cpp": cpp_rel},
        "fast": {
            "slot": "policyFast",
            "call": "engine.policyFast.apply()",
            "when": "tryCounter == 0",
            "contract": "72→22",
            "onnx_allow": list(FAST_ONNX_ALLOW),
            "fill": "gyro3 + gravity3 + 22*(measured+vel+lastAction); no phase",
            "deploy_only": True,
            "isaac_registered": False,
            "not_regular_73": True,
            "not_walk": True,
            "not_kick": True,
            "not_t1": True,
        },
        "regular": {
            "slot": "policy",
            "contract": "73→22",
            "onnx": GETUP_ONNX,
        },
        "simulated": {
            "cfg_present": False,
            "forces_fastActive_false": True,
            "note": "GetUpEngine ctor: simulatedRobot → fastActive=false",
        },
        "competition": {
            "cfg_present": False,
            "fabricated": False,
        },
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
        "fast_as_regular_standup": False,
        "standup_as_walk_344": False,
        "getup_as_hot_swap_train": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "fast apply is 72→22 / K1_fast_standup.onnx; isolated from regular 73, "
            "walk 344, kick 59; Simulated forces fastActive=false; no Competition cfg"
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


def assert_fast_standup_isolated(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("fast-standup isolation leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate fast isolation")
        return snap
    fast = snap.get("fast") or {}
    if fast.get("contract") != "72→22" or fast.get("onnx_allow") != list(FAST_ONNX_ALLOW):
        raise AssertionError("fast apply must stay 72→22 / K1_fast_standup.onnx")
    if not fast.get("not_regular_73") or fast.get("isaac_registered"):
        raise AssertionError("fast must stay isolated from regular / Isaac")
    if snap.get("fast_as_regular_standup") or snap.get("standup_as_walk_344"):
        raise AssertionError("fast isolation flags leaked")
    if (snap.get("regular") or {}).get("contract") != "73→22":
        raise AssertionError("regular slot must remain 73→22 beside fast")
    if (snap.get("simulated") or {}).get("cfg_present"):
        raise AssertionError("must not invent a Simulated getUpEngine.cfg")
    try:
        refuse_fast_as_regular_standup(
            {
                "fast_as_regular_standup": True,
                "source": "K1_fast_standup.onnx",
                "numInput": STANDUP_OBS,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_fast_as_regular_standup must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("fast-standup isolation imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_fast_standup_isolated(repo)
        notes.append("assert_fast_standup_isolated: 72→22 ≠ regular 73")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "GetUpEngine.cpp missing"))
        notes.append("honest SKIP: fast isolation not fabricated")
    elif snap:
        notes.append("fast apply 72→22 / K1_fast_standup.onnx; no phase term")
        notes.append("Simulated forces fastActive=false; no Competition getUp cfg")
        notes.append("13-zero handoff referenced; not re-closed here")

    try:
        refuse_fast_as_regular_standup(
            {
                "fast_as_regular_standup": True,
                "source": "K1_fast_standup.onnx",
                "numInput": STANDUP_OBS,
            }
        )
        errors.append("fast as regular standup must raise")
    except ValueError:
        notes.append("negative: fast as regular standup refused")

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
            errors.append("K1.yaml changed during fast-standup isolation")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during fast-standup isolation")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during fast-standup isolation")
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
        "fast_standup": "72→22",
        "fast_as_regular_standup": False,
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
        print(f"[fast-iso] FAIL {exc}")
        return 1
    fast = snap.get("fast") or {}
    print(
        f"[fast-iso] {snap.get('status')} "
        f"fast={fast.get('contract')} / {fast.get('onnx_allow')}; "
        f"≠ regular 73; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
