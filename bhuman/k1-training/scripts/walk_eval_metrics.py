"""Read-only walk-eval metrics gate (inventory; does not evaluate).

Pins run_walk_eval.sh / evaluate_walk.py as a report-only operator entry:

  * Default: seed 2027 / 100 seg-steps / 8 envs
  * Caps: seg 10..1000, envs 1..64, timeout 900 s, VRAM 12 GiB
  * Writes only under k1-training/runs/<stamp>_walk_eval_s<seed>/
  * Then upload immediately to artifacts/<run-id>/
  * RMSE allowlist is tracking_rmse_settled_vx_vy_wz /
    tracking_rmse_full_vx_vy_wz (plus baseline settled_rmse_vx columns)
  * quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED
  * A single replay PASS must not be written as 比赛合格 / competition-ready

This script never imports isaacgym, never execs walk_eval / play / train.
TRAINABLE=false. walk↔kick GAP stays open.

Does not re-audit bounded_walk_replay / local_bh_gym_dry_run wholesale.
Never writes K1.yaml or official cfg.
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
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-eval-metrics-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
EVAL_SH_REL = "bhuman/k1-training/scripts/run_walk_eval.sh"
EVAL_PY_REL = "bhuman/k1-training/scripts/evaluate_walk.py"
ENTRY_REL = "bhuman/k1-training/scripts/walk_eval_entry.py"
MANAGED_REL = "bhuman/k1-training/scripts/managed_run.py"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

SIBLINGS = (
    "run_walk_eval.sh",
    "walk_eval_entry.py",
    "evaluate_walk.py",
    "upload_run_artifacts.py",
    "bounded_walk_replay.py",
    "local_bh_gym_dry_run.py",
)

LIMITS = {
    "task": "K1",
    "seed_default": 2027,
    "seg_default": 100,
    "seg_min": 10,
    "seg_max": 1000,
    "envs_default": 8,
    "envs_min": 1,
    "envs_max": 64,
    "timeout_s": 900,
    "vram_mib_max": 12288,
    "runs_root": "bhuman/k1-training/runs/<stamp>_walk_eval_s<seed>/",
    "artifacts_root": "bhuman/k1-training/artifacts/<run-id>/",
}

RMSE_ALLOW = (
    "tracking_rmse_settled_vx_vy_wz",
    "tracking_rmse_full_vx_vy_wz",
    "settled_rmse_vx",
)
QUALITY_VERDICT = "REPORT_ONLY_QUALITY_NOT_CERTIFIED"

EVAL_SH_NEEDLES = (
    "seed=${2:-2027}",
    "seg=${3:-100}",
    "envs=${4:-8}",
    "--timeout 900",
    "walk_eval_s",
    "walk_eval_entry.py",
    "seg >= 10 && seg <= 1000",
    "envs >= 1 && envs <= 64",
)
EVAL_PY_NEEDLES = (
    "tracking_rmse_settled_vx_vy_wz",
    "tracking_rmse_full_vx_vy_wz",
    "REPORT_ONLY_QUALITY_NOT_CERTIFIED",
    "no automatic quality pass",
    '"task": "K1"',
    "SCHEDULE",
)
DOC_NEEDLES = (
    "run_walk_eval",
    "walk_eval_metrics",
    "tracking_rmse",
    "单次回放 PASS ≠ 比赛合格",
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
        f"walk-eval metrics pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk-eval metrics pin is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_walk_eval_pass_as_competition_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-eval-pass-as-competition-ready claim must be a mapping")
    verdict = str(claim.get("quality_verdict") or claim.get("verdict") or "")
    if (
        claim.get("walk_eval_pass_as_competition_ready")
        or claim.get("competition_ready")
        or claim.get("match_ready")
        or claim.get("比赛合格")
        or claim.get("replay_pass_as_match")
        or verdict in {"PASS", "COMPETITION_READY", "MATCH_READY", "比赛合格"}
        or (
            claim.get("execution_status") == "PASS"
            and claim.get("as_competition")
        )
    ):
        raise ValueError(
            "run_walk_eval / single replay PASS is report-only; "
            "must not be written as 比赛合格 / competition-ready"
        )


def refuse_eval_writes_outside_runs(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("eval-writes-outside-runs claim must be a mapping")
    dest = str(claim.get("dest") or claim.get("path") or claim.get("run_dir") or "")
    escaped = any(
        token in dest
        for token in (
            "/tmp/",
            "$HOME/",
            "/home/",
            "Desktop/",
            "/var/",
            "C:\\",
        )
    ) and "k1-training/runs" not in dest.replace("\\", "/")
    if (
        claim.get("eval_writes_outside_runs")
        or claim.get("write_home")
        or claim.get("write_tmp")
        or claim.get("outside_runs")
        or escaped
        or (
            dest
            and "runs/" not in dest.replace("\\", "/")
            and claim.get("kind") in {"eval", "walk_eval", "managed_run", None}
            and claim.get("eval_writes_outside_runs") is not False
            and (claim.get("dest") or claim.get("outside"))
        )
    ):
        raise ValueError(
            "run_walk_eval.sh must write only under k1-training/runs/<id>/; "
            "then upload to artifacts/<run-id>/. Writing $HOME / /tmp / Desktop is forbidden"
        )


def refuse_dry_run_doc_claims_gap_closed(claim: dict[str, Any] | None = None) -> None:
    blob = claim if isinstance(claim, dict) else {}
    text = str(blob.get("text") or blob.get("doc") or "")
    if (
        blob.get("dry_run_doc_claims_gap_closed")
        or blob.get("gap_closed") is True
        or "GAP 已闭合" in text
        or "gap_closed=true" in text
    ):
        raise ValueError(
            "LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS must keep "
            "walk↔kick resetHistoryData as GAP (gap_closed=false)"
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
        raise AssertionError("walk-eval metrics leaked TRAINABLE / auto-eval")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    eval_sh = repo / EVAL_SH_REL
    eval_py = repo / EVAL_PY_REL
    entry = repo / ENTRY_REL
    managed = repo / MANAGED_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    for path, label in (
        (eval_sh, EVAL_SH_REL),
        (eval_py, EVAL_PY_REL),
        (entry, ENTRY_REL),
        (managed, MANAGED_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (compat_doc, COMPAT_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")

    sh_text = eval_sh.read_text(encoding="utf-8")
    py_text = eval_py.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(sh_text, EVAL_SH_NEEDLES, EVAL_SH_REL)
    _require_needles(py_text, EVAL_PY_NEEDLES, EVAL_PY_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    if "gap_closed=false" not in compat_text:
        raise AssertionError("LOCAL-BH-GYM-COMPAT must keep gap_closed=false")
    if "isaacgym" in sh_text or "train.py" in sh_text:
        raise AssertionError("run_walk_eval.sh must stay wrapper-only (no train.py)")
    extra_rmse = [
        name
        for name in (
            "competition_rmse",
            "match_rmse",
            "competition_score",
        )
        if name in py_text
    ]
    if extra_rmse:
        raise AssertionError(f"evaluate_walk.py grew non-allowlist RMSE {extra_rmse}")

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
            "bash bhuman/k1-training/scripts/run_walk_eval.sh "
            "<operator-local K1_walk.pth> 2027 100 8"
        ),
        "limits": dict(LIMITS),
        "rmse_allow": list(RMSE_ALLOW),
        "quality_verdict": QUALITY_VERDICT,
        "competition_ready": False,
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
        "walk_eval_pass_as_competition_ready": False,
        "eval_writes_outside_runs": False,
        "dry_run_doc_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "walk eval report-only: seed 2027 / 100 / 8, cap 1000 / 64, 900s / 12 GiB; "
            "RMSE allow settled+full vx/vy/wz; replay PASS ≠ 比赛合格; GAP open"
        ),
        "trainable": False,
        "auto_eval": False,
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


def assert_walk_eval_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_EVAL or snap.get("will_exec_eval_here"):
        raise AssertionError("walk-eval metrics leaked auto-exec")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1"
        or limits.get("seed_default") != 2027
        or limits.get("envs_max") != 64
        or limits.get("seg_max") != 1000
        or limits.get("timeout_s") != 900
    ):
        raise AssertionError(f"walk-eval limits drifted: {limits}")
    if snap.get("rmse_allow") != list(RMSE_ALLOW):
        raise AssertionError(f"RMSE allowlist drifted: {snap.get('rmse_allow')}")
    if (
        snap.get("walk_eval_pass_as_competition_ready")
        or snap.get("eval_writes_outside_runs")
        or snap.get("dry_run_doc_claims_gap_closed")
        or snap.get("walk_kick_gap_closed")
    ):
        raise AssertionError("walk-eval leaked competition-ready / outside-runs / GAP-closed")
    try:
        refuse_walk_eval_pass_as_competition_ready(
            {"walk_eval_pass_as_competition_ready": True, "quality_verdict": "PASS"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_walk_eval_pass_as_competition_ready must raise")
    try:
        refuse_eval_writes_outside_runs(
            {"eval_writes_outside_runs": True, "dest": "/tmp/walk_eval"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_eval_writes_outside_runs must raise")
    try:
        refuse_dry_run_doc_claims_gap_closed(
            {"dry_run_doc_claims_gap_closed": True, "gap_closed": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_dry_run_doc_claims_gap_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk-eval metrics imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_walk_eval_frozen(repo)
        notes.append("assert_walk_eval_frozen: 2027/100/8 · RMSE allowlist · report-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("writes only k1-training/runs/<id>/ then artifacts/<run-id>/")
        notes.append("this pin does not exec run_walk_eval.sh / evaluate_walk.py / train.py")

    try:
        refuse_walk_eval_pass_as_competition_ready(
            {"execution_status": "PASS", "as_competition": True, "比赛合格": True}
        )
        errors.append("walk_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: walk-eval PASS as 比赛合格 refused")
    try:
        refuse_eval_writes_outside_runs(
            {"eval_writes_outside_runs": True, "dest": "$HOME/Desktop/eval"}
        )
        errors.append("eval_writes_outside_runs must raise")
    except ValueError:
        notes.append("negative: eval writes outside runs/ refused")
    try:
        refuse_dry_run_doc_claims_gap_closed(
            {"dry_run_doc_claims_gap_closed": True, "text": "GAP 已闭合"}
        )
        errors.append("dry_run_doc_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: dry-run doc claims GAP closed refused")
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
            errors.append("K1.yaml changed during walk-eval metrics pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during walk-eval metrics pin")
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
        "walk_eval_pass_as_competition_ready": False,
        "eval_writes_outside_runs": False,
        "dry_run_doc_claims_gap_closed": False,
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
        print(f"[walk-eval] FAIL {exc}")
        return 1
    print(
        f"[walk-eval] {snap.get('status')} "
        f"K1 2027/100/8 report-only RMSE; replay PASS ≠ 比赛合格; "
        f"no exec; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
