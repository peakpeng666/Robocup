"""Local artifact upload + cleanup checklist (inventory/docs only; no GPU).

Deepens `upload_run_artifacts` without replacing it:

  * Post-run products must push to GitHub (`artifacts/<run-id>/`) first
  * Then clear local caches of already-uploaded copies
  * Inventory / docs only — no destructive rm of user Desktop / $HOME
  * Giant binaries via Git LFS or Release, never silent PR #4

TRAINABLE=false. walk↔kick GAP stays open.
existence_required_here=false (cloud must not scan $HOME).

Does not import kick_standup_train_dry_run.
Does not rewrite upload_run_artifacts.py.

Runnable: python3 bhuman/k1-training/scripts/local_artifact_upload_cleanup.py
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

from upload_run_artifacts import (  # noqa: E402
    ARTIFACT_ROOT_REL,
    LARGE_SUFFIXES,
    plan_upload,
    refuse_local_artifacts_kept_without_upload_policy,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
AUTO_TRAIN = False
DESTRUCTIVE_CLEANUP = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/local-artifact-upload-cleanup-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "post_run_push_github",
    "then_clear_local_caches",
    "inventory_docs_only",
    "no_destructive_desktop_rm",
    "leftover_cache_needs_upload_note",
    "giant_binaries_lfs_or_release",
)

DOC_NEEDLES = (
    "local_artifact_upload_cleanup",
    "artifacts/<run-id>",
    "Git LFS",
    "Desktop",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
    "competition_ready=true",
)
# Fragments so the assembled call-forms never appear as contiguous source text.
SOURCE_FORBIDDEN_CALLS = (
    "shutil.rmtree" + "(",
    "os.remove" + "(",
    "os.unlink" + "(",
    "Path.unlink" + "(",
    "rm -" + "rf ",
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
        f"upload+cleanup checklist is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"upload+cleanup checklist is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_leftover_cache_without_upload_note(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("leftover-cache-without-upload-note claim must be a mapping")
    if (
        claim.get("leftover_cache_without_upload_note")
        or claim.get("leave_large_cache")
        or claim.get("skip_upload_note")
        or (
            claim.get("large_cache")
            and not claim.get("upload_note")
        )
    ):
        raise ValueError(
            "large local caches must carry an upload note and push to "
            f"{ARTIFACT_ROOT_REL}/<run-id>/ before cleanup; leftover cache "
            "without upload note is forbidden"
        )


def refuse_destructive_desktop_rm(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("destructive-desktop-rm claim must be a mapping")
    path = str(claim.get("path") or claim.get("target") or "")
    if (
        claim.get("destructive_desktop_rm")
        or claim.get("rm_desktop")
        or claim.get("shutil_rmtree_home")
        or (
            claim.get("this_pin")
            and claim.get("rm")
            and ("Desktop" in path or "$HOME" in path or path.startswith("~"))
        )
    ):
        raise ValueError(
            "upload+cleanup scaffold is inventory/docs only; "
            "must not rm user Desktop / $HOME"
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or DESTRUCTIVE_CLEANUP:
        raise AssertionError("upload+cleanup leaked TRAINABLE / destructive flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    src = Path(__file__).read_text(encoding="utf-8")
    leaked_rm = [tok for tok in SOURCE_FORBIDDEN_CALLS if tok in src]
    if leaked_rm:
        raise AssertionError(f"cleanup scaffold source contains destructive {leaked_rm}")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    plan = plan_upload(repo, "dry-run-example")
    if plan.get("invokes_train_py") or plan.get("trainable") or plan.get("connects_user_home"):
        raise AssertionError("upload plan leaked train / home scan")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/local_artifact_upload_cleanup.py",
        "checklist": list(CHECKLIST),
        "upload_plan": {
            "dest_rel": plan.get("dest_rel"),
            "large_via": (plan.get("large_files") or {}).get("via"),
            "silent_pr": False,
            "invokes_train_py": False,
            "connects_user_home": False,
        },
        "cleanup": {
            "order": ["push_github", "then_clear_uploaded_local_copies"],
            "inventory_docs_only": True,
            "destructive_desktop_rm": False,
            "existence_required_here": False,
            "note": "operator clears already-uploaded caches; cloud must not rm Desktop",
        },
        "large_suffixes": list(LARGE_SUFFIXES),
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "will_rm_desktop": False,
        "leftover_cache_without_upload_note": False,
        "destructive_desktop_rm": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "post-run artifacts must push to GitHub then clear local caches; "
            "inventory/docs only; no Desktop rm"
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
    dest_s = str(path).replace("\\", "/")
    if (
        path.suffix in {".yaml", ".yml", ".cfg"}
        or name in {"K1.yaml", "walkingEngine.cfg"}
        or "Desktop" in dest_s
        or "/home/" in dest_s
        and ARTIFACT_ROOT_REL not in dest_s
    ):
        refuse_destructive_desktop_rm(
            {"destructive_desktop_rm": True, "path": dest_s, "this_pin": True, "rm": True}
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_local_artifact_upload_cleanup_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or DESTRUCTIVE_CLEANUP:
        raise AssertionError("upload+cleanup leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"upload+cleanup checklist drifted: {snap.get('checklist')}")
    if snap.get("will_rm_desktop") or snap.get("destructive_desktop_rm"):
        raise AssertionError("upload+cleanup leaked Desktop rm")
    if (
        snap.get("leftover_cache_without_upload_note")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
        or snap.get("will_run_train_py")
    ):
        raise AssertionError("upload+cleanup leaked leftover-cache / train / GAP-closed")
    try:
        refuse_leftover_cache_without_upload_note(
            {"leftover_cache_without_upload_note": True, "leave_large_cache": True}
        )
        raise AssertionError("refuse_leftover_cache_without_upload_note must raise")
    except ValueError:
        pass
    try:
        refuse_local_artifacts_kept_without_upload_policy(
            {"local_artifacts_kept_without_upload_policy": True, "keep_local_only": True}
        )
        raise AssertionError("refuse_local_artifacts_kept_without_upload_policy must raise")
    except ValueError:
        pass
    try:
        refuse_destructive_desktop_rm(
            {"destructive_desktop_rm": True, "path": "~/Desktop", "rm": True, "this_pin": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_destructive_desktop_rm must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("upload+cleanup imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_local_artifact_upload_cleanup_frozen(repo)
        notes.append("assert_local_artifact_upload_cleanup_frozen: inventory/docs only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("post-run push GitHub then clear uploaded local caches")
        notes.append("no destructive rm of user Desktop / $HOME")

    try:
        refuse_leftover_cache_without_upload_note(
            {"large_cache": True, "skip_upload_note": True}
        )
        errors.append("leftover_cache_without_upload_note must raise")
    except ValueError:
        notes.append("negative: leftover cache without upload note refused")
    try:
        refuse_destructive_desktop_rm(
            {"rm_desktop": True, "path": "$HOME/Desktop"}
        )
        errors.append("destructive_desktop_rm must raise")
    except ValueError:
        notes.append("negative: destructive Desktop rm refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError, ValueError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during upload+cleanup pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during upload+cleanup pin")
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
        "leftover_cache_without_upload_note": False,
        "destructive_desktop_rm": False,
        "will_run_train_py": False,
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
        print(f"[upload-cleanup] FAIL {exc}")
        return 1
    print(
        f"[upload-cleanup] {snap.get('status')} "
        f"push GitHub then clear caches; inventory only; no Desktop rm; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
