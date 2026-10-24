"""Read-only WalkToBallAndKickEngine: pose/trajectory only, no CompiledNN.

Fills the engine-side gap next to kick_policy_apply_dims (which already
forbids kickPolicy.apply / CompiledNN / walkPolicy.apply in this file).

Official facts:

  * WalkToBallAndKickEngine::update builds a kickPose and calls
    theWalkToBallGenerator.createPhase — a pose / trajectory generator.
  * It does not apply() any ONNX, does not own kickPolicy, and must
    not grow CompiledNN / T1 tokens.
  * Isolated from the CompiledNN kick slot (chain B). Unexpected
    CompiledNN / T1 / .onnx / policy.apply → FAIL.

Does not re-audit kick_policy_apply_dims / playball_not_kick_policy
wholesale. Never writes K1.yaml or official cfg. TRAINABLE=false.
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
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-to-ball-engine-no-onnx-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"

WTBAK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
)
WTBAK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.h",
)

SIBLINGS = (
    "kick_policy_apply_dims.py",
    "playball_not_kick_policy.py",
    "kick_engine_boundary.py",
    "walk_policy_apply_dims.py",
)

CPP_NEEDLES = (
    "void WalkToBallAndKickEngine::update",
    "walkToBallAndKickGenerator.createPhase",
    "Pose2f kickPose",
    "theWalkToBallGenerator.createPhase",
    "calcInterceptionPosition",
)
H_NEEDLES = (
    "MODULE(WalkToBallAndKickEngine",
    "PROVIDES(WalkToBallAndKickGenerator)",
    "REQUIRES(WalkToBallGenerator)",
)
ENGINE_FORBIDDEN = (
    "CompiledNN",
    "kickPolicy",
    "walkPolicy",
    ".onnx",
    "policy.apply",
    "NeuralNetwork",
    "Isaac",
    "train.py",
    "T1_walk",
    "T1_Ball",
    "K1_kick",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def locate_first(repo: Path, rels: tuple[str, ...]) -> tuple[Path | None, str | None]:
    for rel in rels:
        path = repo / rel
        if path.is_file() and path.stat().st_size > 0:
            return path, rel
    return None, None


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"WalkToBallAndKickEngine pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"WalkToBallAndKickEngine pin is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_walk_to_ball_engine_applies_onnx(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-to-ball-engine-applies-onnx claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("engine") or "")
    if (
        claim.get("walk_to_ball_engine_applies_onnx")
        or claim.get("engine_applies_onnx")
        or claim.get("applies_net")
        or (
            source
            in {
                "WalkToBallAndKickEngine",
                "WalkToBallAndKickEngine.cpp",
                "WalkToBallAndKickEngine.h",
                "createPhase",
                "kickPose",
            }
            and (
                claim.get("applies") in {"onnx", "CompiledNN", "kickPolicy", "walkPolicy"}
                or claim.get("selects") == "kickPolicy"
                or claim.get("contract") in {"59→13", "344→13"}
                and claim.get("applies_onnx")
                or claim.get("family") == "T1"
                or claim.get("compilednn")
            )
        )
    ):
        raise ValueError(
            "WalkToBallAndKickEngine only emits kickPose / trajectory via "
            "WalkToBallGenerator; it must not apply() any ONNX / CompiledNN / T1"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked net/T1 tokens {leaked}")


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
        "walk_to_ball_engine_applies_onnx": False,
        "note": "do not invent WalkToBallAndKickEngine facts when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("WalkToBallAndKickEngine pin leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    cpp, cpp_rel = locate_first(repo, WTBAK_CPP_RELS)
    header, header_rel = locate_first(repo, WTBAK_H_RELS)
    if cpp is None or header is None:
        return _skip_source(
            "WalkToBallAndKickEngine.cpp/.h missing; not fabricating pose-only engine"
        )

    cpp_text = cpp.read_text(encoding="utf-8", errors="replace")
    _require_needles(cpp_text, CPP_NEEDLES, cpp_rel or "WalkToBallAndKickEngine.cpp")
    _forbid_tokens(cpp_text, ENGINE_FORBIDDEN, cpp_rel or "WalkToBallAndKickEngine.cpp")

    h_text = header.read_text(encoding="utf-8", errors="replace")
    _require_needles(h_text, H_NEEDLES, header_rel or "WalkToBallAndKickEngine.h")
    _forbid_tokens(h_text, ENGINE_FORBIDDEN, header_rel or "WalkToBallAndKickEngine.h")

    extra_cpp, extra_cpp_rel = locate_first(repo, WTBAK_CPP_RELS[1:])
    extra_checked = False
    if extra_cpp is not None and extra_cpp != cpp:
        extra_text = extra_cpp.read_text(encoding="utf-8", errors="replace")
        _forbid_tokens(extra_text, ENGINE_FORBIDDEN, extra_cpp_rel or "k1-training WalkToBallAndKickEngine.cpp")
        extra_checked = True

    empty = map_skill_request(None)
    shoot = map_skill_request("shoot")
    if not empty.is_official_walk() or shoot.skips_walk:
        raise AssertionError("empty / shoot-without-want_kick must stay walk 344→13")
    if select_skill(SkillSelectContext()).skill != "walk":
        raise AssertionError("default SkillSelectContext must stay walk")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file() and not (_REACTIVE / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}; do not re-audit by inventing them")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "engine": {
            "kind": "pose_generator",
            "writes": "kickPose / WalkToBallGenerator.createPhase",
            "applies_onnx": False,
            "applies_compilednn": False,
            "owns_kick_policy": False,
            "isolated_from_kick_slot": True,
            "t1": False,
        },
        "sources": {
            "cpp": cpp_rel,
            "header": header_rel,
            "k1_training_copy_checked": extra_checked,
        },
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": list(H_NEEDLES),
        "forbidden_absent": list(ENGINE_FORBIDDEN),
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "walk_to_ball_engine_applies_onnx": False,
        "walk_kick_gap_closed": False,
        "cross": {
            "empty": empty.skill,
            "shoot_without_want_kick": shoot.skill,
        },
        "fabricated": False,
        "note": (
            "WalkToBallAndKickEngine is a pose/trajectory generator; "
            "it does not apply() ONNX / CompiledNN and is not the kick slot"
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


def assert_engine_pose_only(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("WalkToBallAndKickEngine pin leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate engine facts")
        return snap
    engine = snap.get("engine") or {}
    if engine.get("applies_onnx") or engine.get("applies_compilednn") or engine.get("owns_kick_policy"):
        raise AssertionError("WalkToBallAndKickEngine leaked a net apply")
    if engine.get("kind") != "pose_generator" or not engine.get("isolated_from_kick_slot"):
        raise AssertionError("engine must stay a pose generator isolated from kick slot")
    if engine.get("t1"):
        raise AssertionError("WalkToBallAndKickEngine leaked T1")
    if snap.get("walk_to_ball_engine_applies_onnx") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("engine pin leaked ONNX apply or GAP-closed")
    try:
        refuse_walk_to_ball_engine_applies_onnx(
            {
                "walk_to_ball_engine_applies_onnx": True,
                "source": "WalkToBallAndKickEngine",
                "applies": "onnx",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_walk_to_ball_engine_applies_onnx must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("WalkToBallAndKickEngine pin imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_engine_pose_only(repo)
        notes.append("assert_engine_pose_only: kickPose / createPhase; no ONNX / CompiledNN")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        notes.append("honest SKIP: engine facts not fabricated")
    elif snap:
        notes.append("WalkToBallAndKickEngine is pose/trajectory only")
        notes.append("isolated from kickPolicy slot; no CompiledNN / T1 / .onnx")
        notes.append("siblings referenced, not re-audited: kick_apply / playball / kick_engine")

    try:
        refuse_walk_to_ball_engine_applies_onnx(
            {
                "walk_to_ball_engine_applies_onnx": True,
                "source": "WalkToBallAndKickEngine",
                "applies": "onnx",
            }
        )
        errors.append("WalkToBallAndKickEngine applies ONNX must raise")
    except ValueError:
        notes.append("negative: WalkToBallAndKickEngine applies ONNX refused")

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
            errors.append("K1.yaml changed during WalkToBallAndKickEngine pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during WalkToBallAndKickEngine pin")
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
        "walk_to_ball_engine_applies_onnx": False,
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
        print(f"[wtbak-engine] FAIL {exc}")
        return 1
    print(
        f"[wtbak-engine] {snap.get('status')} "
        f"pose-only; no ONNX; default walk {snap.get('walk')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
