"""Standup-eval artifact cross-check (inventory; does not evaluate).

Mirrors walk_eval_artifact_crosscheck for standup:

  * Any existing artifacts/*standup_eval* stay REPORT_ONLY
  * last_standup_eval_published_s2026.json execution PASS ≠ quality upgrade
  * Checklist / inventory PASS cannot upgrade quality_verdict
  * Missing artifact tree is honest SKIP (not fabricated, not fail-closed)

Never rewrites the artifact tree or the last_standup_eval pointer.
Never imports isaacgym / evaluate_standup / getup_force_walk_handoff.
TRAINABLE=false. walk↔kick GAP stays open.

Runnable: python3 bhuman/k1-training/scripts/standup_eval_artifact_crosscheck.py
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
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from standup_eval_metrics import (  # noqa: E402
    QUALITY_VERDICT,
    assert_standup_eval_frozen,
    refuse_standup_eval_pass_as_competition_ready,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_ARTIFACT = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/standup-eval-artifact-crosscheck-latest.json"
ARTIFACT_ROOT_REL = "bhuman/k1-training/artifacts"
POINTER_REL = "bhuman/k1-training/manifests/last_standup_eval_published_s2026.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "report_only_quality",
    "existing_artifacts_unrewritten",
    "pointer_pass_not_quality",
    "checklist_cannot_upgrade",
    "missing_artifact_skip_honest",
)

DOC_NEEDLES = (
    "standup_eval_artifact_crosscheck",
    "REPORT_ONLY",
    "TRAINABLE=false",
    "gap_closed=false",
    "quality_verdict",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "competition_ready=true",
    "field_ready=true",
)
FORBIDDEN_VERDICTS = {
    "PASS",
    "COMPETITION_READY",
    "MATCH_READY",
    "比赛合格",
    "competition_ready",
    "field_ready",
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
        f"standup-eval artifact cross-check is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"standup-eval artifact cross-check is read-only; "
        f"must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_write_artifact(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"standup-eval artifact cross-check must not rewrite "
        f"{path or ARTIFACT_ROOT_REL}"
    )


def refuse_standup_eval_artifact_upgrades_quality(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-eval-artifact-upgrades-quality claim must be a mapping")
    verdict = str(claim.get("quality_verdict") or claim.get("verdict") or "")
    if (
        claim.get("standup_eval_artifact_upgrades_quality")
        or claim.get("checklist_upgrades_quality")
        or claim.get("upgrade_quality")
        or claim.get("competition_ready") is True
        or claim.get("field_ready") is True
        or claim.get("比赛合格")
        or verdict in FORBIDDEN_VERDICTS
        or (
            claim.get("execution_status") == "PASS"
            and claim.get("as_competition_ready")
        )
        or (
            claim.get("pointer_status") == "PASS"
            and claim.get("as_quality_pass")
        )
        or (
            claim.get("checklist_alone")
            and verdict != QUALITY_VERDICT
            and claim.get("upgrade_quality") is not False
        )
    ):
        raise ValueError(
            "standup-eval artifacts stay REPORT_ONLY_QUALITY_NOT_CERTIFIED; "
            "checklist / last_standup_eval execution PASS cannot upgrade quality_verdict"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _discover_artifacts(repo: Path) -> list[str]:
    root = repo / ARTIFACT_ROOT_REL
    if not root.is_dir():
        return []
    found: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and "standup_eval" in child.name:
            found.append(str(child.relative_to(repo)))
    return found


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name} must be a JSON object")
    return data


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ARTIFACT or APPLY_TO_LIVE:
        raise AssertionError("standup-eval artifact cross-check leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    stand = repo / STAND_YAML_REL
    if stand.is_file():
        stand_text = stand.read_text(encoding="utf-8")
        if "num_observations: 73" not in stand_text or "num_actions: 22" not in stand_text:
            raise AssertionError("official K1_Stand_Up.yaml drifted off 73→22")

    metrics = assert_standup_eval_frozen(repo)
    if metrics.get("quality_verdict") != QUALITY_VERDICT:
        raise AssertionError("standup-eval metrics overlay drifted off REPORT_ONLY")

    compat = repo / COMPAT_DOC_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts_doc.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts_doc, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    found = _discover_artifacts(repo)
    inspected: list[dict[str, Any]] = []
    for rel in found:
        status_path = repo / rel / "evaluation-status.json"
        if not status_path.is_file():
            inspected.append(
                {"rel": rel, "status": "SKIP", "reason": "no evaluation-status.json", "fabricated": False}
            )
            continue
        status = _load_json(status_path)
        verdict = str(status.get("quality_verdict") or "")
        if verdict != QUALITY_VERDICT:
            raise AssertionError(
                f"{rel} quality_verdict drifted: {verdict!r} ≠ {QUALITY_VERDICT}"
            )
        if verdict in FORBIDDEN_VERDICTS:
            raise AssertionError(f"{rel} quality_verdict leaked competition-ready")
        inspected.append(
            {
                "rel": rel,
                "status": "PASS",
                "quality_verdict": QUALITY_VERDICT,
                "execution_status": status.get("execution_status"),
                "fabricated": False,
            }
        )

    pointer = repo / POINTER_REL
    pointer_blob: dict[str, Any] | None = None
    if pointer.is_file():
        pointer_blob = _load_json(pointer)
        if pointer_blob.get("quality_verdict") in FORBIDDEN_VERDICTS:
            raise AssertionError("last_standup_eval pointer leaked competition quality")

    artifact_status = "PASS" if found else "SKIP"
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/standup_eval_artifact_crosscheck.py",
        "checklist": list(CHECKLIST),
        "quality_verdict": QUALITY_VERDICT,
        "artifact_status": artifact_status,
        "artifacts": inspected,
        "pointer_rel": POINTER_REL if pointer.is_file() else None,
        "pointer_execution_status": (pointer_blob or {}).get("status"),
        "pointer_run_dir": (pointer_blob or {}).get("run_dir"),
        "will_exec_eval_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "write_artifact": False,
        "standup_eval_artifact_upgrades_quality": False,
        "checklist_upgrades_quality": False,
        "apply_to_live": False,
        "would_train": False,
        "ready_gpu": False,
        "field_ready": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "standup-eval artifacts stay REPORT_ONLY_QUALITY_NOT_CERTIFIED; "
            "missing tree is honest SKIP; checklist / pointer PASS ≠ quality upgrade"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
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
    dest_s = str(path).replace("\\", "/")
    if (
        path.suffix in {".yaml", ".yml", ".cfg"}
        or name
        in {
            "K1.yaml",
            "K1_Stand_Up.yaml",
            "walkingEngine.cfg",
            "getUpEngine.cfg",
            "evaluation-status.json",
            "last_standup_eval_published_s2026.json",
        }
        or "/artifacts/" in dest_s
    ):
        refuse_write_artifact(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_standup_eval_artifact_crosscheck_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    repo = _repo(repo)
    pointer = repo / POINTER_REL
    before = hashlib.sha256(pointer.read_bytes()).hexdigest() if pointer.is_file() else ""
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ARTIFACT or APPLY_TO_LIVE:
        raise AssertionError("standup-eval artifact cross-check leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"standup-eval artifact checklist drifted: {snap.get('checklist')}")
    if snap.get("quality_verdict") != QUALITY_VERDICT:
        raise AssertionError("quality_verdict drifted off REPORT_ONLY")
    if snap.get("will_exec_eval_here") or snap.get("write_artifact"):
        raise AssertionError("standup-eval artifact cross-check leaked eval / rewrite")
    if (
        snap.get("standup_eval_artifact_upgrades_quality")
        or snap.get("checklist_upgrades_quality")
        or snap.get("field_ready")
        or snap.get("gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("standup-eval artifact leaked quality upgrade / GAP-closed")
    if snap.get("ready_gpu") or snap.get("would_train"):
        raise AssertionError("standup-eval artifact leaked ready_gpu / would_train")
    if not snap.get("artifacts") and snap.get("artifact_status") != "SKIP":
        raise AssertionError("missing standup_eval tree must stay honest SKIP")
    if pointer.is_file():
        after = hashlib.sha256(pointer.read_bytes()).hexdigest()
        if before != after:
            raise AssertionError("last_standup_eval pointer rewritten")
    try:
        refuse_standup_eval_artifact_upgrades_quality(
            {
                "standup_eval_artifact_upgrades_quality": True,
                "checklist_upgrades_quality": True,
                "quality_verdict": "PASS",
            }
        )
        raise AssertionError("refuse_standup_eval_artifact_upgrades_quality must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("standup-eval artifact cross-check imported Gym")

    yaml_path = repo / K1_YAML_REL
    stand = repo / STAND_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    pointer = repo / POINTER_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    before_ptr = hashlib.sha256(pointer.read_bytes()).hexdigest() if pointer.is_file() else ""
    try:
        snap = assert_standup_eval_artifact_crosscheck_frozen(repo)
        notes.append("assert_standup_eval_artifact_crosscheck_frozen: REPORT_ONLY stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append(
            f"artifact_status={snap.get('artifact_status')}; "
            f"quality={snap.get('quality_verdict')}"
        )
        if snap.get("artifact_status") == "SKIP":
            warnings.append("no standup_eval artifact tree in this checkout; not fabricated")
        notes.append("checklist / pointer PASS cannot upgrade quality_verdict")

    try:
        refuse_standup_eval_artifact_upgrades_quality(
            {
                "checklist_alone": True,
                "upgrade_quality": True,
                "quality_verdict": "比赛合格",
            }
        )
        errors.append("standup_eval_artifact_upgrades_quality must raise")
    except ValueError:
        notes.append("negative: checklist upgrade of standup-eval quality refused")
    try:
        refuse_standup_eval_artifact_upgrades_quality(
            {"pointer_status": "PASS", "as_quality_pass": True}
        )
        errors.append("pointer PASS as quality must raise")
    except ValueError:
        notes.append("negative: last_standup_eval execution PASS as quality refused")
    try:
        refuse_standup_eval_pass_as_competition_ready(
            {"standup_eval_pass_as_competition_ready": True, "quality_verdict": "PASS"}
        )
        errors.append("refuse_standup_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: standup-eval PASS as competition-ready refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_artifact(pointer if pointer.is_file() else POINTER_REL)
        errors.append("refuse_write_artifact must raise")
    except RuntimeError:
        notes.append("rewrite of standup-eval artifacts / pointer refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (stand, before_stand, "K1_Stand_Up.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
        (getup_cfg, before_getup, "getUpEngine.cfg"),
        (pointer, before_ptr, "last_standup_eval pointer"),
    ):
        if path.is_file() and before:
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during standup-eval artifact cross-check")
            else:
                notes.append(f"official {label} untouched" if "yaml" in label or label.endswith(".cfg") else f"{label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_artifact": False,
        "walk": "344→13",
        "ready_gpu": False,
        "standup_eval_artifact_upgrades_quality": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[standup-eval-artifact] FAIL {exc}")
        return 1
    print(
        f"[standup-eval-artifact] {snap.get('status')} "
        f"REPORT_ONLY; artifact={snap.get('artifact_status')}; "
        f"checklist ≠ quality upgrade; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
