"""Read-only standup-eval metrics gate (inventory; does not evaluate).

Pins run_standup_eval.sh / evaluate_standup.py as a report-only overlay:

  * Default: profile published / seed 2026 / 3000 steps / 28 envs
  * Caps: steps 1..10000, envs 14..112 and % 14 == 0, timeout 1200 s, VRAM 12 GiB
  * Writes only under k1-training/runs/<stamp>_standup_eval_<profile>_s<seed>/
  * Then upload immediately to artifacts/<run-id>/
  * Quality allowlist is reference_completion_rate / stable_finish_rate /
    worst_stratum_reference_rate / post_getup_upright_fraction
  * Contract overlay: quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED
    even if status is PASS_FOR_DECLARED_PROFILE
  * PASS_FOR_DECLARED_PROFILE must not be written as 比赛合格 / competition-ready

This script never imports evaluate_standup.py / isaacgym, never execs
standup_eval / play / train. TRAINABLE=false. walk↔kick GAP stays open.

Does not re-audit bounded_standup_replay / walk_eval_metrics wholesale.
Never writes K1.yaml, K1_Stand_Up.yaml, or official cfg.
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
STANDUP_OBS = 73
STANDUP_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STANDUP_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/standup-eval-metrics-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
EVAL_SH_REL = "bhuman/k1-training/scripts/run_standup_eval.sh"
EVAL_PY_REL = "bhuman/k1-training/scripts/evaluate_standup.py"
ENTRY_REL = "bhuman/k1-training/scripts/standup_eval_entry.py"
MANAGED_REL = "bhuman/k1-training/scripts/managed_run.py"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

SIBLINGS = (
    "run_standup_eval.sh",
    "standup_eval_entry.py",
    "evaluate_standup.py",
    "upload_run_artifacts.py",
    "bounded_standup_replay.py",
    "walk_eval_metrics.py",
)

LIMITS = {
    "task": "K1_Stand_Up",
    "profile_default": "published",
    "seed_default": 2026,
    "steps_default": 3000,
    "steps_max": 10000,
    "envs_default": 28,
    "envs_min": 14,
    "envs_max": 112,
    "envs_multiple_of": 14,
    "timeout_s": 1200,
    "vram_mib_max": 12288,
    "runs_root": "bhuman/k1-training/runs/<stamp>_standup_eval_<profile>_s<seed>/",
    "artifacts_root": "bhuman/k1-training/artifacts/<run-id>/",
}

QUALITY_ALLOW = (
    "reference_completion_rate",
    "stable_finish_rate",
    "worst_stratum_reference_rate",
    "post_getup_upright_fraction",
)
QUALITY_VERDICT = "REPORT_ONLY_QUALITY_NOT_CERTIFIED"

EVAL_SH_NEEDLES = (
    "profile=${2:-published}",
    "seed=${3:-2026}",
    "steps=${4:-3000}",
    "envs=${5:-28}",
    "--timeout 1200",
    "standup_eval_",
    "standup_eval_entry.py",
    "steps <= 10000",
    "envs % 14",
)
EVAL_PY_NEEDLES = (
    "73 inputs, 22 actions",
    "never implies robot or getup-to-walk handoff acceptance",
    "PASS_FOR_DECLARED_PROFILE",
    "K1_Stand_Up.yaml",
    "reference_completion_rate",
)
DOC_NEEDLES = (
    "run_standup_eval",
    "standup_eval_metrics",
    "REPORT_ONLY",
    "PASS_FOR_DECLARED_PROFILE ≠ 比赛合格",
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
        f"standup-eval metrics pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"standup-eval metrics pin is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_standup_eval_pass_as_competition_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-eval-pass-as-competition-ready claim must be a mapping")
    verdict = str(claim.get("quality_verdict") or claim.get("verdict") or "")
    status = str(claim.get("status") or claim.get("execution_status") or "")
    if (
        claim.get("standup_eval_pass_as_competition_ready")
        or claim.get("competition_ready")
        or claim.get("match_ready")
        or claim.get("比赛合格")
        or claim.get("eval_pass_as_match")
        or verdict in {"PASS", "COMPETITION_READY", "MATCH_READY", "比赛合格"}
        or (
            status == "PASS_FOR_DECLARED_PROFILE"
            and (
                claim.get("as_competition")
                or claim.get("competition_ready")
                or claim.get("比赛合格")
                or claim.get("standup_eval_pass_as_competition_ready")
            )
        )
    ):
        raise ValueError(
            "run_standup_eval PASS_FOR_DECLARED_PROFILE is report-only; "
            "must not be written as 比赛合格 / competition-ready"
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
        raise AssertionError("standup-eval metrics leaked TRAINABLE / auto-eval")
    if "evaluate_standup" in sys.modules or "isaacgym" in sys.modules:
        raise AssertionError("standup-eval metrics must not import evaluate_standup / isaacgym")
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
    if "train.py" in sh_text:
        raise AssertionError("run_standup_eval.sh must stay wrapper-only (no train.py)")
    extra_quality = [
        name
        for name in ("competition_score", "match_ready_rate", "competition_ready")
        if name in py_text
    ]
    if extra_quality:
        raise AssertionError(f"evaluate_standup.py grew non-allowlist quality {extra_quality}")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (repo / "bhuman/k1-training/scripts" / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": (
            "bash bhuman/k1-training/scripts/run_standup_eval.sh "
            "<operator-local K1_stand_up.pt> published 2026 3000 28"
        ),
        "limits": dict(LIMITS),
        "quality_allow": list(QUALITY_ALLOW),
        "quality_verdict": QUALITY_VERDICT,
        "competition_ready": False,
        "writes": {
            "runs": LIMITS["runs_root"],
            "upload": LIMITS["artifacts_root"],
            "outside_runs": False,
            "home_scan": False,
        },
        "will_exec_eval_here": False,
        "will_import_evaluate_standup": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "standup_eval_pass_as_competition_ready": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "standup eval report-only overlay: published / 2026 / 3000 / 28, "
            "cap 10000 / 14–112 %14, 1200s / 12 GiB; "
            "PASS_FOR_DECLARED_PROFILE ≠ 比赛合格; GAP open; no isaacgym import"
        ),
        "trainable": False,
        "auto_eval": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "getup_cfg_sha256": hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if getup_cfg.is_file()
        else "",
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


def assert_standup_eval_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_EVAL or snap.get("will_exec_eval_here"):
        raise AssertionError("standup-eval metrics leaked auto-exec")
    if snap.get("will_import_evaluate_standup") or snap.get("will_run_isaac_gym"):
        raise AssertionError("standup-eval metrics leaked isaacgym import")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_Stand_Up"
        or limits.get("profile_default") != "published"
        or limits.get("seed_default") != 2026
        or limits.get("steps_default") != 3000
        or limits.get("steps_max") != 10000
        or limits.get("envs_default") != 28
        or limits.get("timeout_s") != 1200
    ):
        raise AssertionError(f"standup-eval limits drifted: {limits}")
    if snap.get("quality_allow") != list(QUALITY_ALLOW):
        raise AssertionError(f"quality allowlist drifted: {snap.get('quality_allow')}")
    if snap.get("quality_verdict") != QUALITY_VERDICT:
        raise AssertionError(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    if (
        snap.get("standup_eval_pass_as_competition_ready")
        or snap.get("walk_kick_gap_closed")
        or snap.get("competition_ready")
    ):
        raise AssertionError("standup-eval leaked competition-ready / GAP-closed")
    try:
        refuse_standup_eval_pass_as_competition_ready(
            {
                "standup_eval_pass_as_competition_ready": True,
                "status": "PASS_FOR_DECLARED_PROFILE",
                "quality_verdict": "PASS",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_standup_eval_pass_as_competition_ready must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("standup-eval metrics imported Gym")
    if "evaluate_standup" in sys.modules:
        errors.append("standup-eval metrics imported evaluate_standup")

    yaml_path = repo / K1_YAML_REL
    standup_yaml = repo / STANDUP_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_standup = (
        hashlib.sha256(standup_yaml.read_bytes()).hexdigest() if standup_yaml.is_file() else ""
    )
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_standup_eval_frozen(repo)
        notes.append(
            "assert_standup_eval_frozen: published/2026/3000/28 · REPORT_ONLY overlay"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("writes only k1-training/runs/<id>/ then artifacts/<run-id>/")
        notes.append("this pin does not exec run_standup_eval.sh / evaluate_standup.py")

    try:
        refuse_standup_eval_pass_as_competition_ready(
            {
                "status": "PASS_FOR_DECLARED_PROFILE",
                "as_competition": True,
                "比赛合格": True,
            }
        )
        errors.append("standup_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: standup-eval PASS_FOR_DECLARED_PROFILE as 比赛合格 refused")
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
            errors.append("K1.yaml changed during standup-eval metrics pin")
        else:
            notes.append("official K1.yaml untouched")
    if standup_yaml.is_file():
        after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
        if before_standup != after_standup:
            errors.append("K1_Stand_Up.yaml changed during standup-eval metrics pin")
        else:
            notes.append("official K1_Stand_Up.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during standup-eval metrics pin")
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
        "standup": "73→22",
        "standup_eval_pass_as_competition_ready": False,
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
        print(f"[standup-eval] FAIL {exc}")
        return 1
    print(
        f"[standup-eval] {snap.get('status')} "
        f"published/2026/3000/28 REPORT_ONLY; "
        f"PASS_FOR_DECLARED_PROFILE ≠ 比赛合格; no exec; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
