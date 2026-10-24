"""PR volume health re-scan (docs-only; no history rewrite).

Deepens pr4_index_nav without replacing its frozen 335 / +191k pin:

  * Notes later contract/manifest growth vs that pin
  * Suggests (docs only) what is safe to squash later
  * Forbids history rewrite / force-push / deleting artifacts
  * gap_closed stays false

Does not import reactive_intercept_bypass_hardening or teamcomm_shape_negatives.
Does not write K1.yaml / sibling yaml / cfg.
Does not git rm, squash, or force-push.

Runnable: python3 bhuman/k1-training/scripts/pr_volume_health_rescan.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pr4_index_nav import (  # noqa: E402
    VOLUME_FILES,
    VOLUME_INSERTIONS,
    refuse_pr_index_claims_gap_closed,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/pr-volume-health-rescan-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
INDEX_REL = "bhuman/docs/PR4-INDEX.md"
MANIFESTS_REL = "bhuman/k1-training/manifests"
ARTIFACTS_REL = "bhuman/k1-training/artifacts"

CHECKLIST = (
    "growth_noted",
    "squash_docs_only",
    "no_history_rewrite",
    "no_artifact_delete",
    "gap_closed_false",
)

SAFE_TO_SQUASH_LATER = (
    {
        "kind": "older_contract_gate_stamps",
        "when": "after a matching *-latest.json exists",
        "example": "contract-gate-20261024-*.json older than the current stamp",
        "action": "docs-only suggestion; do not squash now; do not delete",
    },
    {
        "kind": "duplicate_selfcheck_html_markdown",
        "when": "if PR4-SELFCHECK-LATEST.md and an HTML twin are pure copies",
        "example": "duplicate rendered selfcheck pages after latest exists",
        "action": "docs-only suggestion; never delete artifacts/ trees",
    },
)
NEVER_SQUASH = (
    "artifacts/",
    "official yaml/cfg",
    "contract scripts",
)

DOC_NEEDLES = (
    "pr_volume_health_rescan",
    "no_history_rewrite",
    "do_not_delete_artifacts",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "competition_ready=true",
)
SHORTSTAT_RE = re.compile(
    r"(\d+)\s+files? changed(?:,\s+(\d+)\s+insertions?)?(?:,\s+(\d+)\s+deletions?)?"
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
        f"PR volume health re-scan is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"PR volume health re-scan is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_volume_rescan_deletes_artifacts(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("volume-rescan-deletes-artifacts claim must be a mapping")
    if (
        claim.get("volume_rescan_deletes_artifacts")
        or claim.get("delete_artifacts")
        or claim.get("rewrite_history")
        or claim.get("force_push")
        or claim.get("git_rm_artifacts")
        or claim.get("squash_now")
    ):
        raise ValueError(
            "volume re-scan must not delete artifacts, rewrite history, "
            "force-push, git rm artifacts/, or squash now; docs-only later-squash notes"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _git_shortstat(repo: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--shortstat", "origin/main...HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "text": "", "files": None, "insertions": None}
    text = (proc.stdout or "").strip()
    match = SHORTSTAT_RE.search(text)
    if not match:
        return {"available": bool(text), "text": text, "files": None, "insertions": None}
    return {
        "available": True,
        "text": text,
        "files": int(match.group(1)),
        "insertions": int(match.group(2) or 0),
    }


def _inventory_growth(repo: Path) -> dict[str, Any]:
    manifests = repo / MANIFESTS_REL
    latest = sorted(p.name for p in manifests.glob("*-latest.json")) if manifests.is_dir() else []
    gates = (
        sorted(p.name for p in manifests.glob("contract-gate-20261024-*.json"))
        if manifests.is_dir()
        else []
    )
    artifacts = repo / ARTIFACTS_REL
    artifact_dirs = (
        sorted(p.name for p in artifacts.iterdir() if p.is_dir()) if artifacts.is_dir() else []
    )
    shortstat = _git_shortstat(repo)
    current_files = shortstat.get("files")
    current_insertions = shortstat.get("insertions")
    grew = False
    if current_files is not None and current_files > VOLUME_FILES:
        grew = True
    if current_insertions is not None and current_insertions > VOLUME_INSERTIONS:
        grew = True
    if len(latest) > 0 or len(gates) > 1:
        grew = True
    return {
        "pin_files": VOLUME_FILES,
        "pin_insertions": VOLUME_INSERTIONS,
        "current_files": current_files,
        "current_insertions": current_insertions,
        "shortstat": shortstat.get("text") or "",
        "latest_manifests": len(latest),
        "contract_gate_stamps": len(gates),
        "artifact_run_dirs": len(artifact_dirs),
        "growth_noted": grew,
        "note": (
            f"pr4_index_nav pin stays {VOLUME_FILES} files / +{VOLUME_INSERTIONS}; "
            "later *-latest.json and contract-gate stamps grew; "
            "do not rewrite that pin; do not delete artifacts"
        ),
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("volume rescan overlay leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    growth = _inventory_growth(repo)
    if not growth.get("growth_noted"):
        raise AssertionError("volume rescan must note later contract/manifest growth vs pin")

    artifacts = repo / ARTIFACTS_REL
    if artifacts.is_dir() and not any(artifacts.iterdir()):
        raise AssertionError("artifacts/ present but empty; do not treat as license to delete")

    compat = repo / COMPAT_DOC_REL
    art_doc = repo / ARTIFACTS_DOC_REL
    index = repo / INDEX_REL
    if not compat.is_file() or not art_doc.is_file() or not index.is_file():
        raise AssertionError("COMPAT / ARTIFACTS / PR4-INDEX missing")
    for path, label in (
        (compat, COMPAT_DOC_REL),
        (art_doc, ARTIFACTS_DOC_REL),
        (index, INDEX_REL),
    ):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)
    refuse_pr_index_claims_gap_closed(index.read_text(encoding="utf-8"))

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/pr_volume_health_rescan.py",
        "checklist": list(CHECKLIST),
        "growth": growth,
        "safe_to_squash_later": list(SAFE_TO_SQUASH_LATER),
        "never_squash": list(NEVER_SQUASH),
        "no_history_rewrite": True,
        "no_force_push": True,
        "do_not_delete_artifacts": True,
        "squash_now": False,
        "volume_rescan_deletes_artifacts": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "docs-only volume re-scan; pin 335/+191k stays; later stamps noted; "
            "do not rewrite history; do not delete artifacts"
        ),
        "trainable": False,
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
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_pr_volume_health_rescan_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("volume rescan overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"volume rescan checklist drifted: {snap.get('checklist')}")
    if snap.get("squash_now") or snap.get("volume_rescan_deletes_artifacts"):
        raise AssertionError("volume rescan leaked squash_now / artifact delete")
    if not snap.get("no_history_rewrite") or not snap.get("do_not_delete_artifacts"):
        raise AssertionError("volume rescan must keep no_history_rewrite / do_not_delete_artifacts")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("volume rescan leaked ready_gpu / would_train / GAP-closed")
    growth = snap.get("growth") or {}
    if growth.get("pin_files") != VOLUME_FILES or growth.get("pin_insertions") != VOLUME_INSERTIONS:
        raise AssertionError("volume rescan must not rewrite the 335 / +191k pin")
    try:
        refuse_volume_rescan_deletes_artifacts(
            {
                "volume_rescan_deletes_artifacts": True,
                "delete_artifacts": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_volume_rescan_deletes_artifacts must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("volume rescan overlay imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_pr_volume_health_rescan_frozen(repo)
        notes.append("assert_pr_volume_health_rescan_frozen: pin 335/+191k stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        growth = snap.get("growth") or {}
        notes.append(
            f"growth noted vs pin {growth.get('pin_files')}/+{growth.get('pin_insertions')}; "
            f"latest={growth.get('latest_manifests')} stamps={growth.get('contract_gate_stamps')}"
        )
        notes.append("docs-only later-squash notes; no history rewrite; do not delete artifacts")

    try:
        refuse_volume_rescan_deletes_artifacts(
            {"rewrite_history": True, "force_push": True, "git_rm_artifacts": True}
        )
        errors.append("volume_rescan_deletes_artifacts must raise")
    except ValueError:
        notes.append("negative: history rewrite / artifact delete / squash-now refused")
    try:
        refuse_pr_index_claims_gap_closed({"pr_index_claims_gap_closed": True, "gap_closed": True})
        errors.append("refuse_pr_index_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: PR index GAP-closed claim refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during volume rescan overlay")
            else:
                notes.append(f"official {label} untouched")

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
        "walk": "344→13",
        "ready_gpu": False,
        "volume_rescan_deletes_artifacts": False,
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
        print(f"[volume-rescan] FAIL {exc}")
        return 1
    print(
        f"[volume-rescan] {snap.get('status')} "
        f"growth noted; no history rewrite; do not delete artifacts; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
