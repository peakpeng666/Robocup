"""Bounded official-kick replay contract (inventory only; does not play).

Pins run_replay.sh K1_Ball as a bounded operator-local entry:

  * Task: K1_Ball (59→13), not walk 344→13
  * Operator suggestion (reserved-gpu): 4 envs / 300 steps
  * Script defaults: 4 envs / 500 steps (shared run_replay.sh)
  * Caps: envs ≤ 256, steps ≤ 1000
  * managed_run: wall timeout 600 s, GPU process memory ≤ 12 GiB
  * Writes only under k1-training/runs/<stamp>_replay_K1_Ball/
  * Then upload immediately to bhuman/k1-training/artifacts/<run-id>/
  * History reset is draft-only (gap_closed=false / apply_to_live=false)

This script never sources env.sh, never execs play.py / train.py,
never starts Isaac. TRAINABLE=false.

Missing GPU weights still PASS this inventory
(existence_required_here=false). Does not re-audit bounded_walk_replay
or bounded_standup_replay wholesale. Never writes K1.yaml, K1_Ball.yaml,
or official cfg. walk↔kick GAP stays open. Kick replay ≠ walk baseline.
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
KICK_OBS = 59
KICK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
KICK_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/bounded-kick-replay-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
REPLAY_SH_REL = "bhuman/k1-training/scripts/run_replay.sh"
MANAGED_REL = "bhuman/k1-training/scripts/managed_run.py"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
UPLOAD_REL = "bhuman/k1-training/scripts/upload_run_artifacts.py"
GAP_DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-kick-reset-history-v0.json"
GAP_DOC_REL = "bhuman/docs/POLICY-SWITCH-HISTORY-GAP.md"
CKPT_REL = "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth"

SIBLINGS = (
    "bounded_walk_replay.py",
    "bounded_standup_replay.py",
    "upload_run_artifacts.py",
    "managed_run.py",
    "run_replay.sh",
)

LIMITS = {
    "task": "K1_Ball",
    "obs": 59,
    "act": 13,
    "operator_envs": 4,
    "operator_steps": 300,
    "envs_default": 4,
    "envs_max": 256,
    "steps_default": 500,
    "steps_max": 1000,
    "timeout_s": 600,
    "vram_mib_max": 12288,
    "ckpt": "src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth",
    "load_mode": "actor",
    "runs_root": "bhuman/k1-training/runs/<stamp>_replay_K1_Ball/",
    "artifacts_root": "bhuman/k1-training/artifacts/<run-id>/",
}

REPLAY_NEEDLES = (
    "K1_Ball)",
    "K1_kick_inner.pth",
    'ENVS="${2:-4}"',
    'STEPS="${3:-500}"',
    "ENVS <= 256",
    "STEPS <= 1000",
    "managed_run.py",
    "replay_$TASK",
    "play.py",
)
MANAGED_NEEDLES = (
    'ROOT / "runs"',
    "--timeout",
    "default=600",
    "peak > 12288",
    "BH_RUN_DIR",
    "--output_dir",
)
DOC_NEEDLES = (
    "K1_Ball",
    "59→13",
    "bounded_kick_replay",
    "runs/",
    "artifacts/<run-id>",
    "TRAINABLE=false",
)
GAP_DRAFT_NEEDLES = (
    '"gap_closed": false',
    '"apply_to_live": false',
    "engine.resetHistoryData()",
)
GAP_DOC_NEEDLES = (
    "resetHistoryData()",
    "apply_to_live:false",
    "gap_closed:false",
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
        f"bounded kick replay pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"bounded kick replay pin is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_kick_replay_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-replay-as-walk-344 claim must be a mapping")
    task = str(claim.get("task") or claim.get("replay_task") or "")
    kickish = task in {"K1_Ball", "kick", "K1_kick_inner"} or bool(
        claim.get("kick_replay")
    )
    as_walk = (
        claim.get("kick_replay_as_walk_344")
        or claim.get("as_walk_344")
        or claim.get("as_walk_baseline")
        or claim.get("treat_as_walk")
        or claim.get("walk_slot")
        or claim.get("num_observations") == WALK_OBS
        or claim.get("obs") == WALK_OBS
        or str(claim.get("net") or "") in {"344→13", "K1_walk.onnx"}
    )
    if claim.get("kick_replay_as_walk_344") or (kickish and as_walk):
        raise ValueError(
            "run_replay.sh K1_Ball is 59→13 / K1_kick_inner.pth; "
            "must not be treated as walk 344→13"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_REPLAY:
        raise AssertionError("bounded kick replay leaked TRAINABLE / auto-replay")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    kick_text = kick_yaml.read_text(encoding="utf-8")
    if "num_observations: 59" not in kick_text or "num_actions: 13" not in kick_text:
        raise AssertionError("official K1_Ball.yaml drifted off 59→13")

    replay = repo / REPLAY_SH_REL
    managed = repo / MANAGED_REL
    doc = repo / ARTIFACTS_DOC_REL
    upload = repo / UPLOAD_REL
    gap_draft = repo / GAP_DRAFT_REL
    gap_doc = repo / GAP_DOC_REL
    if not replay.is_file() or not managed.is_file():
        raise AssertionError("run_replay.sh / managed_run.py missing")
    if not doc.is_file() or not upload.is_file():
        raise AssertionError("LOCAL-RUN-ARTIFACTS / upload_run_artifacts missing")
    if not gap_draft.is_file() or not gap_doc.is_file():
        raise AssertionError("walk-kick history GAP draft / doc missing")

    replay_text = replay.read_text(encoding="utf-8")
    managed_text = managed.read_text(encoding="utf-8")
    doc_text = doc.read_text(encoding="utf-8")
    draft_text = gap_draft.read_text(encoding="utf-8")
    gap_doc_text = gap_doc.read_text(encoding="utf-8")
    _require_needles(replay_text, REPLAY_NEEDLES, REPLAY_SH_REL)
    _require_needles(managed_text, MANAGED_NEEDLES, MANAGED_REL)
    _require_needles(doc_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(draft_text, GAP_DRAFT_NEEDLES, GAP_DRAFT_REL)
    _require_needles(gap_doc_text, GAP_DOC_NEEDLES, GAP_DOC_REL)
    if "train.py" in replay_text:
        raise AssertionError("run_replay.sh must not invoke train.py")
    ball_branch = replay_text.split("K1_Ball", 1)[1][:240]
    if "K1_walk.pth" in ball_branch:
        raise AssertionError("K1_Ball branch must not load K1_walk.pth")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (repo / "bhuman/k1-training/scripts" / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    ckpt = repo / CKPT_REL
    missing_weights = not ckpt.is_file()
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "bash bhuman/k1-training/scripts/run_replay.sh K1_Ball 4 300",
        "limits": dict(LIMITS),
        "writes": {
            "runs": LIMITS["runs_root"],
            "upload": LIMITS["artifacts_root"],
            "outside_runs": False,
            "home_scan": False,
        },
        "history_reset": {
            "draft": GAP_DRAFT_REL,
            "doc": GAP_DOC_REL,
            "call": "engine.resetHistoryData()",
            "apply_to_live": False,
            "gap_closed": False,
            "draft_only": True,
        },
        "missing_weights": missing_weights,
        "existence_required_here": False,
        "will_exec_replay_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "kick_replay_as_walk_344": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "bounded K1_Ball replay: 59→13; operator 4/300; script 4/500; "
            "cap 256/1000 · 600s / 12 GiB; runs/<id>/ then artifacts/<run-id>/; "
            "history reset draft-only; missing weights still PASS inventory; "
            "not walk 344→13; this pin does not play"
        ),
        "trainable": False,
        "auto_replay": False,
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
        "kick_yaml_sha256": hashlib.sha256(kick_yaml.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Ball.yaml",
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


def assert_kick_replay_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_REPLAY or snap.get("will_exec_replay_here"):
        raise AssertionError("bounded kick replay leaked auto-exec")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_Ball"
        or limits.get("obs") != 59
        or limits.get("act") != 13
        or limits.get("envs_max") != 256
        or limits.get("steps_max") != 1000
        or limits.get("timeout_s") != 600
        or limits.get("vram_mib_max") != 12288
    ):
        raise AssertionError(f"kick replay limits drifted: {limits}")
    hist = snap.get("history_reset") or {}
    if hist.get("gap_closed") or hist.get("apply_to_live") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("kick replay leaked GAP-closed / live history reset")
    if snap.get("existence_required_here"):
        raise AssertionError("kick replay must not require GPU weights here")
    if snap.get("kick_replay_as_walk_344"):
        raise AssertionError("kick replay leaked walk-344 claim")
    try:
        refuse_kick_replay_as_walk_344(
            {"kick_replay_as_walk_344": True, "task": "K1_Ball", "obs": 344}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_replay_as_walk_344 must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("bounded kick replay imported Gym")

    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest() if kick_yaml.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_kick_replay_frozen(repo)
        notes.append("assert_kick_replay_frozen: K1_Ball 59→13 · 4/300 · 256/1000")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("writes only k1-training/runs/<id>/ then artifacts/<run-id>/")
        notes.append("this pin does not exec run_replay.sh / play.py / train.py")
        if snap.get("missing_weights"):
            notes.append("weights missing here; existence_required_here=false still PASS")
        notes.append("history reset draft-only; gap_closed=false")

    try:
        refuse_kick_replay_as_walk_344(
            {"task": "K1_Ball", "obs": 344, "as_walk_baseline": True}
        )
        errors.append("kick_replay_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick replay as walk 344 refused")
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
            errors.append("K1.yaml changed during bounded kick replay pin")
        else:
            notes.append("official K1.yaml untouched")
    if kick_yaml.is_file():
        after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
        if before_kick != after_kick:
            errors.append("K1_Ball.yaml changed during bounded kick replay pin")
        else:
            notes.append("official K1_Ball.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during bounded kick replay pin")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "kick_replay_as_walk_344": False,
        "gap_closed": False,
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
        print(f"[kick-replay] FAIL {exc}")
        return 1
    print(
        f"[kick-replay] {snap.get('status')} "
        f"K1_Ball 59→13 · 4/300 cap 256/1000; GAP draft-only; "
        f"no exec; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
