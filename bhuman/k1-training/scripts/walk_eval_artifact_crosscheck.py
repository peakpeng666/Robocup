"""Walk-eval artifact cross-check (inventory; does not evaluate).

Pins existing operator-local walk_eval_s2027 artifacts as REPORT_ONLY:

  * artifacts/20261024_200640_281778_walk_eval_s2027/
  * execution_status may be PASS
  * quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED
  * Checklist / inventory PASS cannot upgrade quality to competition-ready

Never rewrites the artifact tree. Never imports isaacgym / evaluate_walk.
TRAINABLE=false. walk↔kick GAP stays open.

Does not import local_rtx5090_pretrain_checklist.

Runnable: python3 bhuman/k1-training/scripts/walk_eval_artifact_crosscheck.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from walk_eval_metrics import (  # noqa: E402
    QUALITY_VERDICT,
    assert_walk_eval_frozen,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_ARTIFACT = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-eval-artifact-crosscheck-latest.json"
ARTIFACT_REL = (
    "bhuman/k1-training/artifacts/20261024_200640_281778_walk_eval_s2027"
)
STATUS_REL = f"{ARTIFACT_REL}/evaluation-status.json"
RESULTS_REL = f"{ARTIFACT_REL}/results.json"
EXEC_REL = f"{ARTIFACT_REL}/execution.json"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

DOC_NEEDLES = (
    "walk_eval_artifact_crosscheck",
    "20261024_200640_281778_walk_eval_s2027",
    "REPORT_ONLY",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
    "competition_ready=true",
)
FORBIDDEN_VERDICTS = {
    "PASS",
    "COMPETITION_READY",
    "MATCH_READY",
    "比赛合格",
    "competition_ready",
}


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
        f"walk-eval artifact cross-check is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk-eval artifact cross-check is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_artifact(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk-eval artifact cross-check must not rewrite "
        f"{path or ARTIFACT_REL}"
    )


def refuse_walk_eval_artifact_as_competition_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-eval-artifact-as-competition-ready claim must be a mapping")
    verdict = str(claim.get("quality_verdict") or claim.get("verdict") or "")
    if (
        claim.get("walk_eval_artifact_as_competition_ready")
        or claim.get("checklist_upgrades_quality")
        or claim.get("competition_ready") is True
        or claim.get("比赛合格")
        or verdict in FORBIDDEN_VERDICTS
        or (
            claim.get("execution_status") == "PASS"
            and claim.get("as_competition_ready")
        )
        or (
            claim.get("checklist_alone")
            and verdict != QUALITY_VERDICT
            and claim.get("upgrade_quality")
        )
    ):
        raise ValueError(
            "walk_eval_s2027 artifact stays REPORT_ONLY_QUALITY_NOT_CERTIFIED; "
            "execution PASS / checklist alone cannot upgrade to competition-ready"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _call_assert(
    label: str,
    fn: Callable[..., Any] | None,
    repo: Path,
) -> dict[str, Any]:
    if fn is None:
        return {
            "id": label,
            "status": "SKIP",
            "reason": f"{label} sibling missing; not fabricated",
            "fabricated": False,
        }
    try:
        result = fn(repo)
    except FileNotFoundError as exc:
        return {
            "id": label,
            "status": "SKIP",
            "reason": str(exc),
            "fabricated": False,
        }
    except (AssertionError, ValueError) as exc:
        return {"id": label, "status": "FAIL", "reason": str(exc), "fabricated": False}
    if isinstance(result, dict) and str(result.get("status") or "PASS") == "SKIP":
        return {
            "id": label,
            "status": "SKIP",
            "reason": str(result.get("reason") or f"{label} SKIP"),
            "fabricated": False,
        }
    return {"id": label, "status": "PASS", "reason": None, "fabricated": False}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name} must be a JSON object")
    return data


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ARTIFACT:
        raise AssertionError("walk-eval artifact cross-check leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    if not artifacts_doc.is_file() or not compat_doc.is_file():
        raise AssertionError("LOCAL-RUN-ARTIFACTS / LOCAL-BH-GYM-COMPAT missing")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)

    status_path = repo / STATUS_REL
    results_path = repo / RESULTS_REL
    exec_path = repo / EXEC_REL
    for path, label in (
        (status_path, STATUS_REL),
        (results_path, RESULTS_REL),
        (exec_path, EXEC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"walk-eval artifact missing {label}")

    status = _load_json(status_path)
    results = _load_json(results_path)
    execution = _load_json(exec_path)
    verdict = str(status.get("quality_verdict") or "")
    if verdict != QUALITY_VERDICT:
        raise AssertionError(
            f"walk_eval_s2027 quality_verdict drifted: {verdict!r} ≠ {QUALITY_VERDICT}"
        )
    if verdict in FORBIDDEN_VERDICTS:
        raise AssertionError("walk_eval_s2027 quality_verdict leaked competition-ready")
    if results.get("seed") != 2027 or results.get("num_envs") != 8 or results.get("seg_steps") != 100:
        raise AssertionError(
            f"walk_eval_s2027 profile drifted: seed={results.get('seed')} "
            f"envs={results.get('num_envs')} seg={results.get('seg_steps')}"
        )

    steps = [_call_assert("walk_eval_metrics", assert_walk_eval_frozen, repo)]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "walk-eval artifact segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/walk_eval_artifact_crosscheck.py",
        "artifact_rel": ARTIFACT_REL,
        "execution_status": status.get("execution_status") or execution.get("status"),
        "quality_verdict": QUALITY_VERDICT,
        "seed": 2027,
        "num_envs": 8,
        "seg_steps": 100,
        "steps": steps,
        "will_exec_eval_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "write_artifact": False,
        "walk_eval_artifact_as_competition_ready": False,
        "checklist_upgrades_quality": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "walk_eval_s2027 stays REPORT_ONLY_QUALITY_NOT_CERTIFIED; "
            "execution PASS / checklist alone ≠ competition-ready"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "status_sha256": hashlib.sha256(status_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    dest_s = str(path).replace("\\", "/")
    if (
        path.suffix in {".yaml", ".yml", ".cfg"}
        or name in {"K1.yaml", "walkingEngine.cfg", "evaluation-status.json", "results.json"}
        or ARTIFACT_REL in dest_s
    ):
        refuse_write_artifact(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_walk_eval_artifact_crosscheck_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    repo = _repo(repo)
    status_path = repo / STATUS_REL
    before = hashlib.sha256(status_path.read_bytes()).hexdigest()
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ARTIFACT:
        raise AssertionError("walk-eval artifact cross-check leaked flags")
    if snap.get("quality_verdict") != QUALITY_VERDICT:
        raise AssertionError("quality_verdict drifted off REPORT_ONLY")
    if snap.get("will_exec_eval_here") or snap.get("write_artifact"):
        raise AssertionError("walk-eval artifact cross-check leaked eval / rewrite")
    if (
        snap.get("walk_eval_artifact_as_competition_ready")
        or snap.get("checklist_upgrades_quality")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("walk-eval artifact leaked competition-ready / GAP-closed")
    after = hashlib.sha256(status_path.read_bytes()).hexdigest()
    if before != after:
        raise AssertionError("walk_eval_s2027 evaluation-status.json rewritten")
    try:
        refuse_walk_eval_artifact_as_competition_ready(
            {
                "walk_eval_artifact_as_competition_ready": True,
                "execution_status": "PASS",
                "as_competition_ready": True,
                "quality_verdict": "PASS",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_walk_eval_artifact_as_competition_ready must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk-eval artifact cross-check imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    status_path = repo / STATUS_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_art = hashlib.sha256(status_path.read_bytes()).hexdigest() if status_path.is_file() else ""
    try:
        snap = assert_walk_eval_artifact_crosscheck_frozen(repo)
        notes.append("assert_walk_eval_artifact_crosscheck_frozen: REPORT_ONLY stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append(
            f"{ARTIFACT_REL} execution={snap.get('execution_status')} "
            f"quality={snap.get('quality_verdict')}"
        )
        notes.append("checklist / inventory PASS cannot upgrade quality_verdict")

    try:
        refuse_walk_eval_artifact_as_competition_ready(
            {
                "checklist_upgrades_quality": True,
                "checklist_alone": True,
                "upgrade_quality": True,
                "quality_verdict": "比赛合格",
            }
        )
        errors.append("walk_eval_artifact_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: walk-eval artifact as competition-ready refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_artifact(status_path)
        errors.append("refuse_write_artifact must raise")
    except RuntimeError:
        notes.append("rewrite of walk_eval_s2027 artifact refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during walk-eval artifact cross-check")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during walk-eval artifact cross-check")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if status_path.is_file():
        after_art = hashlib.sha256(status_path.read_bytes()).hexdigest()
        if before_art != after_art:
            errors.append("walk_eval_s2027 evaluation-status.json changed")
        else:
            notes.append("walk_eval_s2027 artifact untouched")

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
        "quality_verdict": QUALITY_VERDICT,
        "walk_eval_artifact_as_competition_ready": False,
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
        print(f"[walk-eval-artifact] FAIL {exc}")
        return 1
    print(
        f"[walk-eval-artifact] {snap.get('status')} "
        f"s2027 REPORT_ONLY; execution PASS ≠ competition-ready; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
