"""Bounded fast-standup replay contract (inventory only; does not play).

Pins deploy-only fast standup 72→22 / K1_fast_standup.onnx as isolated
from walk 344→13 and from regular standup 73→22 / K1_Stand_Up:

  * Fast is deploy-only: getUpEngine.cfg policyNameFast / 72→22
  * NOT an Isaac registered task (no K1_fast_standup.yaml)
  * run_replay.sh stays K1 / K1_Ball / K1_Stand_Up only
  * Missing ONNX is OK (existence_required_onnx=false)
  * This pin never execs play / train / run_replay

walk↔kick resetHistoryData GAP is a different contract and stays open.
standup→walk 13-zero is already closed elsewhere; fast replay does not
close the walk↔kick GAP.

Never writes K1.yaml, K1_Stand_Up.yaml, or official cfg.
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
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
AUTO_REPLAY = False
WALK_OBS = 344
WALK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STANDUP_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
ABSENT_FAST_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_fast_standup.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/bounded-fast-standup-replay-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
REPLAY_SH_REL = "bhuman/k1-training/scripts/run_replay.sh"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ENV_INIT_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py",
    "bhuman/MachineLearning/IsaacGymRL/envs/__init__.py",
)

SIBLINGS = (
    "bounded_standup_replay.py",
    "fast_standup_isolation.py",
    "run_replay.sh",
    "getup_engine_cfg_audit.py",
)

LIMITS = {
    "task": "K1_fast_standup",
    "obs": 72,
    "act": 22,
    "isaac_registered": False,
    "run_replay_accepts": False,
    "yaml_present": False,
    "deploy_only": True,
    "onnx": "K1_fast_standup.onnx",
    "existence_required_onnx": False,
    "existence_required_replay_script": False,
}

GETUP_NEEDLES = (
    "numInputFast = 72",
    "numOutputFast = 22",
    "policyNameFast = K1_fast_standup.onnx",
)
REPLAY_NEEDLES = (
    "Supported tasks: K1 K1_Ball K1_Stand_Up",
)
DOC_NEEDLES = (
    "bounded_fast_standup_replay",
    "72→22",
    "K1_fast_standup",
    "deploy-only",
    "TRAINABLE=false",
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
        f"bounded fast-standup replay pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"bounded fast-standup replay pin is read-only; "
        f"must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_fast_standup_replay_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("fast-standup-replay-as-walk-344 claim must be a mapping")
    task = str(claim.get("task") or claim.get("replay_task") or "")
    fastish = task in {"K1_fast_standup", "fast_standup", "fast"} or bool(
        claim.get("fast_standup_replay")
    )
    as_walk = (
        claim.get("fast_standup_replay_as_walk_344")
        or claim.get("as_walk_344")
        or claim.get("as_walk_baseline")
        or claim.get("treat_as_walk")
        or claim.get("obs") == WALK_OBS
        or claim.get("num_observations") == WALK_OBS
        or claim.get("act") == WALK_ACT
        or str(claim.get("net") or "") in {"344→13", "K1_walk.onnx"}
    )
    if claim.get("fast_standup_replay_as_walk_344") or (fastish and as_walk):
        raise ValueError(
            "fast standup replay is deploy-only 72→22 / K1_fast_standup.onnx; "
            "must not be treated as walk 344→13"
        )


def refuse_fast_standup_replay_as_regular_73(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("fast-standup-replay-as-regular-73 claim must be a mapping")
    task = str(claim.get("task") or claim.get("replay_task") or "")
    fastish = task in {"K1_fast_standup", "fast_standup", "fast"} or bool(
        claim.get("fast_standup_replay")
    )
    as_regular = (
        claim.get("fast_standup_replay_as_regular_73")
        or claim.get("as_regular_73")
        or claim.get("same_as_regular")
        or claim.get("obs") == STANDUP_OBS
        or claim.get("num_observations") == STANDUP_OBS
        or claim.get("contract") == "73→22"
        or str(claim.get("net") or "") in {"73→22", "K1.onnx", "K1_stand_up.pt"}
        or claim.get("isaac_task") == "K1_Stand_Up"
    )
    if claim.get("fast_standup_replay_as_regular_73") or (fastish and as_regular):
        raise ValueError(
            "fast standup replay is deploy-only 72→22; "
            "must not be treated as regular standup 73→22 / K1_Stand_Up"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _isaac_registers_fast(repo: Path) -> bool:
    for rel in ENV_INIT_RELS:
        path = repo / rel
        if path.is_file() and "K1_fast_standup" in path.read_text(encoding="utf-8"):
            return True
    return False


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_REPLAY:
        raise AssertionError("bounded fast-standup replay leaked TRAINABLE / auto-replay")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    standup_yaml = repo / STANDUP_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    standup_text = standup_yaml.read_text(encoding="utf-8")
    if (
        "num_observations: 73" not in standup_text
        or "num_actions: 22" not in standup_text
    ):
        raise AssertionError("official K1_Stand_Up.yaml drifted off 73→22")
    if (repo / ABSENT_FAST_YAML_REL).is_file():
        raise AssertionError("K1_fast_standup.yaml must not exist (not an Isaac task)")

    getup = repo / GETUP_CFG_REL
    replay = repo / REPLAY_SH_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    for path, label in (
        (getup, GETUP_CFG_REL),
        (replay, REPLAY_SH_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (compat_doc, COMPAT_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")

    getup_text = getup.read_text(encoding="utf-8")
    replay_text = replay.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(getup_text, GETUP_NEEDLES, GETUP_CFG_REL)
    _require_needles(replay_text, REPLAY_NEEDLES, REPLAY_SH_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    if "gap_closed=false" not in compat_text:
        raise AssertionError("LOCAL-BH-GYM-COMPAT must keep gap_closed=false")
    if "K1_fast_standup)" in replay_text:
        raise AssertionError("run_replay.sh must not grow a K1_fast_standup case")
    if "train.py" in replay_text:
        raise AssertionError("run_replay.sh must not invoke train.py")
    if _isaac_registers_fast(repo):
        raise AssertionError("Isaac env registry must not list K1_fast_standup")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (repo / "bhuman/k1-training/scripts" / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": (
            "inventory only; deploy-only 72→22 / K1_fast_standup.onnx. "
            "run_replay.sh does not accept K1_fast_standup (correct)."
        ),
        "limits": dict(LIMITS),
        "isaac_registered": False,
        "writes": {
            "runs": None,
            "upload": None,
            "outside_runs": False,
            "home_scan": False,
        },
        "will_exec_replay_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "fast_standup_replay_as_walk_344": False,
        "fast_standup_replay_as_regular_73": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "fast standup replay is deploy-only 72→22 / K1_fast_standup.onnx; "
            "not Isaac; not run_replay.sh; not walk 344; not regular 73→22; "
            "missing ONNX OK; walk↔kick GAP stays open (different contract); "
            "standup→walk 13-zero is already closed elsewhere"
        ),
        "trainable": False,
        "auto_replay": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "getup_cfg_sha256": hashlib.sha256(getup.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "standup_yaml_sha256": hashlib.sha256(standup_yaml.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Stand_Up.yaml",
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


def assert_fast_standup_replay_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_REPLAY or snap.get("will_exec_replay_here"):
        raise AssertionError("bounded fast-standup replay leaked auto-exec")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_fast_standup"
        or limits.get("obs") != 72
        or limits.get("act") != 22
        or limits.get("isaac_registered")
        or limits.get("run_replay_accepts")
        or limits.get("yaml_present")
        or not limits.get("deploy_only")
        or limits.get("existence_required_onnx")
    ):
        raise AssertionError(f"fast standup replay limits drifted: {limits}")
    if snap.get("isaac_registered") or snap.get("will_run_isaac_gym"):
        raise AssertionError("fast standup must stay unregistered / no Isaac")
    if (
        snap.get("fast_standup_replay_as_walk_344")
        or snap.get("fast_standup_replay_as_regular_73")
        or snap.get("walk_kick_gap_closed")
    ):
        raise AssertionError("fast standup replay leaked walk-344 / regular-73 / GAP-closed")
    try:
        refuse_fast_standup_replay_as_walk_344(
            {"fast_standup_replay_as_walk_344": True, "task": "K1_fast_standup", "obs": 344}
        )
        raise AssertionError("refuse_fast_standup_replay_as_walk_344 must raise")
    except ValueError:
        pass
    try:
        refuse_fast_standup_replay_as_regular_73(
            {
                "fast_standup_replay_as_regular_73": True,
                "task": "K1_fast_standup",
                "obs": 73,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_fast_standup_replay_as_regular_73 must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("bounded fast-standup replay imported Gym")

    yaml_path = repo / K1_YAML_REL
    standup_yaml = repo / STANDUP_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_standup = (
        hashlib.sha256(standup_yaml.read_bytes()).hexdigest() if standup_yaml.is_file() else ""
    )
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_fast_standup_replay_frozen(repo)
        notes.append("assert_fast_standup_replay_frozen: deploy-only 72→22 · not Isaac")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("run_replay.sh stays K1 / K1_Ball / K1_Stand_Up; no K1_fast_standup case")
        notes.append("this pin does not exec run_replay.sh / play.py / train.py")

    try:
        refuse_fast_standup_replay_as_walk_344(
            {"task": "K1_fast_standup", "obs": 344, "as_walk_baseline": True}
        )
        errors.append("fast_standup_replay_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: fast standup replay as walk 344 refused")
    try:
        refuse_fast_standup_replay_as_regular_73(
            {"task": "K1_fast_standup", "obs": 73, "as_regular_73": True}
        )
        errors.append("fast_standup_replay_as_regular_73 must raise")
    except ValueError:
        notes.append("negative: fast standup replay as regular 73 refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(getup_cfg)
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
            errors.append("K1.yaml changed during bounded fast-standup replay pin")
        else:
            notes.append("official K1.yaml untouched")
    if standup_yaml.is_file():
        after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
        if before_standup != after_standup:
            errors.append("K1_Stand_Up.yaml changed during bounded fast-standup replay pin")
        else:
            notes.append("official K1_Stand_Up.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during bounded fast-standup replay pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during bounded fast-standup replay pin")
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
        "standup": "73→22",
        "fast": "72→22",
        "fast_standup_replay_as_walk_344": False,
        "fast_standup_replay_as_regular_73": False,
        "isaac_registered": False,
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
        print(f"[fast-standup-replay] FAIL {exc}")
        return 1
    print(
        f"[fast-standup-replay] {snap.get('status')} "
        f"deploy-only 72→22; ≠ walk 344; ≠ regular 73; not Isaac; "
        f"no exec; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
