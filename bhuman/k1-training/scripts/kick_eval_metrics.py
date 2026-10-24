"""Read-only kick-eval metrics gate (inventory overlay; does not evaluate).

Pins a report-only overlay for any future / operator-local K1_Ball eval:

  * Task: K1_Ball (59→13), not walk 344→13
  * Walk eval stays task K1 only (evaluate_walk.py / run_walk_eval.sh)
  * Dedicated evaluate_kick.py is NOT required here
    (existence_required_eval_script=false)
  * quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED
  * PASS / PASS_FOR_DECLARED_PROFILE must not be written as
    比赛合格 / competition-ready
  * Kick eval PASS must not be treated as walk 344
  * Kick eval PASS must not be treated as live kickPolicy deploy

This script never imports isaacgym, never execs walk_eval / play / train,
never writes a live kick eval script. TRAINABLE=false.
walk↔kick GAP stays open.

Does not re-audit bounded_kick_replay / walk_eval_metrics wholesale.
Never writes K1.yaml, K1_Ball.yaml, or official cfg.
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
AUTO_EVAL = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
KICK_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-eval-metrics-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
EVAL_SH_REL = "bhuman/k1-training/scripts/run_walk_eval.sh"
EVAL_PY_REL = "bhuman/k1-training/scripts/evaluate_walk.py"
REPLAY_SH_REL = "bhuman/k1-training/scripts/run_replay.sh"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

SIBLINGS = (
    "run_walk_eval.sh",
    "evaluate_walk.py",
    "bounded_kick_replay.py",
    "walk_eval_metrics.py",
    "standup_eval_metrics.py",
)

LIMITS = {
    "task": "K1_Ball",
    "obs": 59,
    "act": 13,
    "seed_default": 2028,
    "timeout_s": 900,
    "vram_mib_max": 12288,
    "runs_root": "bhuman/k1-training/runs/<stamp>_kick_eval_s<seed>/",
    "artifacts_root": "bhuman/k1-training/artifacts/<run-id>/",
    "existence_required_eval_script": False,
}

QUALITY_VERDICT = "REPORT_ONLY_QUALITY_NOT_CERTIFIED"
QUALITY_ALLOW = ("quality_verdict",)

WALK_EVAL_SH_NEEDLES = (
    "walk_eval_s",
    "walk_eval_entry.py",
    "--timeout 900",
)
WALK_EVAL_PY_NEEDLES = (
    '"task": "K1"',
    "REPORT_ONLY_QUALITY_NOT_CERTIFIED",
    "tracking_rmse_settled_vx_vy_wz",
)
REPLAY_NEEDLES = (
    "K1_Ball)",
    "K1_kick_inner.pth",
)
DOC_NEEDLES = (
    "kick_eval_metrics",
    "REPORT_ONLY",
    "59→13",
    "kick eval PASS ≠ 比赛合格",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
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
        f"kick-eval metrics pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick-eval metrics pin is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_kick_eval_pass_as_competition_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-eval-pass-as-competition-ready claim must be a mapping")
    verdict = str(claim.get("quality_verdict") or claim.get("verdict") or "")
    status = str(claim.get("status") or claim.get("execution_status") or "")
    if (
        claim.get("kick_eval_pass_as_competition_ready")
        or claim.get("competition_ready")
        or claim.get("match_ready")
        or claim.get("比赛合格")
        or verdict in {"PASS", "COMPETITION_READY", "MATCH_READY", "比赛合格"}
        or (
            status in {"PASS", "PASS_FOR_DECLARED_PROFILE"}
            and (
                claim.get("as_competition")
                or claim.get("competition_ready")
                or claim.get("比赛合格")
                or claim.get("kick_eval_pass_as_competition_ready")
            )
        )
    ):
        raise ValueError(
            "kick eval PASS / PASS_FOR_DECLARED_PROFILE is report-only; "
            "must not be written as 比赛合格 / competition-ready"
        )


def refuse_kick_eval_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-eval-as-walk-344 claim must be a mapping")
    task = str(claim.get("task") or claim.get("eval_task") or "")
    kickish = task in {"K1_Ball", "kick", "kick_eval"} or bool(claim.get("kick_eval"))
    as_walk = (
        claim.get("kick_eval_as_walk_344")
        or claim.get("as_walk_344")
        or claim.get("as_walk_baseline")
        or claim.get("reuse_walk_eval")
        or claim.get("obs") == WALK_OBS
        or claim.get("num_observations") == WALK_OBS
        or str(claim.get("net") or "") in {"344→13", "K1_walk.onnx"}
        or claim.get("walk_rmse_as_kick")
    )
    if claim.get("kick_eval_as_walk_344") or (kickish and as_walk):
        raise ValueError(
            "kick eval overlay is K1_Ball 59→13 report-only; "
            "must not be treated as walk 344→13 / walk_eval"
        )


def refuse_kick_eval_as_live_deploy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-eval-as-live-deploy claim must be a mapping")
    if (
        claim.get("kick_eval_as_live_deploy")
        or claim.get("apply_to_live") is True
        or claim.get("live_kick_deploy")
        or claim.get("kick_eval_flips_kick_policy")
        or claim.get("deploy_from_eval_pass")
        or str(claim.get("slot") or "") == "kickPolicy"
        and claim.get("eval_pass_means_live")
    ):
        raise ValueError(
            "kick eval PASS is report-only inventory; "
            "must not be treated as live kickPolicy deploy"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_EVAL:
        raise AssertionError("kick-eval metrics leaked TRAINABLE / auto-eval")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    kick_text = kick_yaml.read_text(encoding="utf-8")
    if "num_observations: 59" not in kick_text or "num_actions: 13" not in kick_text:
        raise AssertionError("official K1_Ball.yaml drifted off 59→13")

    eval_sh = repo / EVAL_SH_REL
    eval_py = repo / EVAL_PY_REL
    replay = repo / REPLAY_SH_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    for path, label in (
        (eval_sh, EVAL_SH_REL),
        (eval_py, EVAL_PY_REL),
        (replay, REPLAY_SH_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (compat_doc, COMPAT_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")

    sh_text = eval_sh.read_text(encoding="utf-8")
    py_text = eval_py.read_text(encoding="utf-8")
    replay_text = replay.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(sh_text, WALK_EVAL_SH_NEEDLES, EVAL_SH_REL)
    _require_needles(py_text, WALK_EVAL_PY_NEEDLES, EVAL_PY_REL)
    _require_needles(replay_text, REPLAY_NEEDLES, REPLAY_SH_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    if "gap_closed=false" not in compat_text:
        raise AssertionError("LOCAL-BH-GYM-COMPAT must keep gap_closed=false")
    if '"task": "K1_Ball"' in py_text:
        raise AssertionError("evaluate_walk.py must stay task K1 (not K1_Ball)")
    if "kick_eval_" in sh_text:
        raise AssertionError("run_walk_eval.sh must not grow a live kick_eval name")
    if "train.py" in sh_text:
        raise AssertionError("run_walk_eval.sh must stay wrapper-only (no train.py)")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (repo / "bhuman/k1-training/scripts" / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    dedicated = _SCRIPTS / "evaluate_kick.py"
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": (
            "inventory overlay only; no live run_kick_eval.sh. "
            "Sibling replay: bash bhuman/k1-training/scripts/run_replay.sh K1_Ball 4 300"
        ),
        "limits": dict(LIMITS),
        "quality_allow": list(QUALITY_ALLOW),
        "quality_verdict": QUALITY_VERDICT,
        "competition_ready": False,
        "existence_required_eval_script": False,
        "dedicated_evaluate_kick_present": dedicated.is_file(),
        "writes": {
            "runs": LIMITS["runs_root"],
            "upload": LIMITS["artifacts_root"],
            "outside_runs": False,
            "home_scan": False,
        },
        "will_exec_eval_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "kick_eval_pass_as_competition_ready": False,
        "kick_eval_as_walk_344": False,
        "kick_eval_as_live_deploy": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "kick eval report-only overlay: K1_Ball 59→13; walk_eval stays task K1; "
            "no dedicated evaluate_kick.py required; "
            "PASS ≠ 比赛合格 ≠ walk 344 ≠ live kick deploy; GAP open"
        ),
        "trainable": False,
        "auto_eval": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
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


def assert_kick_eval_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_EVAL or snap.get("will_exec_eval_here"):
        raise AssertionError("kick-eval metrics leaked auto-exec")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_Ball"
        or limits.get("obs") != 59
        or limits.get("act") != 13
        or limits.get("existence_required_eval_script")
    ):
        raise AssertionError(f"kick-eval limits drifted: {limits}")
    if snap.get("quality_verdict") != QUALITY_VERDICT:
        raise AssertionError(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    if (
        snap.get("kick_eval_pass_as_competition_ready")
        or snap.get("kick_eval_as_walk_344")
        or snap.get("kick_eval_as_live_deploy")
        or snap.get("walk_kick_gap_closed")
        or snap.get("competition_ready")
    ):
        raise AssertionError("kick-eval leaked competition-ready / walk-344 / live-deploy / GAP-closed")
    try:
        refuse_kick_eval_pass_as_competition_ready(
            {
                "kick_eval_pass_as_competition_ready": True,
                "status": "PASS_FOR_DECLARED_PROFILE",
                "quality_verdict": "PASS",
            }
        )
        raise AssertionError("refuse_kick_eval_pass_as_competition_ready must raise")
    except ValueError:
        pass
    try:
        refuse_kick_eval_as_walk_344(
            {"kick_eval_as_walk_344": True, "task": "K1_Ball", "obs": 344}
        )
        raise AssertionError("refuse_kick_eval_as_walk_344 must raise")
    except ValueError:
        pass
    try:
        refuse_kick_eval_as_live_deploy(
            {"kick_eval_as_live_deploy": True, "apply_to_live": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_eval_as_live_deploy must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick-eval metrics imported Gym")

    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest() if kick_yaml.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_kick_eval_frozen(repo)
        notes.append("assert_kick_eval_frozen: K1_Ball 59→13 · REPORT_ONLY overlay")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("walk_eval stays task K1; dedicated evaluate_kick.py not required")
        notes.append("this pin does not exec walk_eval / play.py / train.py")

    try:
        refuse_kick_eval_pass_as_competition_ready(
            {"status": "PASS_FOR_DECLARED_PROFILE", "as_competition": True, "比赛合格": True}
        )
        errors.append("kick_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: kick-eval PASS as 比赛合格 refused")
    try:
        refuse_kick_eval_as_walk_344(
            {"task": "K1_Ball", "obs": 344, "as_walk_baseline": True}
        )
        errors.append("kick_eval_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick-eval as walk 344 refused")
    try:
        refuse_kick_eval_as_live_deploy(
            {"kick_eval_as_live_deploy": True, "live_kick_deploy": True}
        )
        errors.append("kick_eval_as_live_deploy must raise")
    except ValueError:
        notes.append("negative: kick-eval as live kick deploy refused")
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
            errors.append("K1.yaml changed during kick-eval metrics pin")
        else:
            notes.append("official K1.yaml untouched")
    if kick_yaml.is_file():
        after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
        if before_kick != after_kick:
            errors.append("K1_Ball.yaml changed during kick-eval metrics pin")
        else:
            notes.append("official K1_Ball.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during kick-eval metrics pin")
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
        "kick_eval_pass_as_competition_ready": False,
        "kick_eval_as_walk_344": False,
        "kick_eval_as_live_deploy": False,
        "quality_verdict": QUALITY_VERDICT,
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
        print(f"[kick-eval] FAIL {exc}")
        return 1
    print(
        f"[kick-eval] {snap.get('status')} "
        f"K1_Ball 59→13 REPORT_ONLY; PASS ≠ 比赛合格 ≠ walk 344 ≠ live deploy; "
        f"no exec; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
