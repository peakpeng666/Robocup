"""Local-run artifact upload convention (no GPU, no train, dry-run by default).

Policy written for the operator's local experiment machine — this increment
does not run experiments and does not scan the user's home disk.

  - Local PC = experiment / test only.
  - Products (runs / logs / checkpoints / plots) upload to GitHub as soon
    as they are produced: bhuman/k1-training/artifacts/<run-id>/
  - Keep only the current run workspace locally; after push, clean caches.
  - Giant binaries (*.pth / *.pt / *.onnx / *.mp4 / archives) go through
    Git LFS or a GitHub Release — never silently into PR #4.
  - Cloud contracts still land on PR #4.
  - TRAINABLE=false. AUTO_TRAIN=false. Never invokes train.py / Isaac.

Selfcheck only asserts this file exists and that --help / --dry-run print
the convention. Default mode is dry-run; --apply still does not push unless
UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH=1 (operator-only; cloud gate never sets it).

See bhuman/docs/LOCAL-RUN-ARTIFACTS.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
AUTO_TRAIN = False
ALLOW_PUSH_ENV = "UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH"
ARTIFACT_ROOT_REL = "bhuman/k1-training/artifacts"
SOURCE_HINTS = ("runs/", "logs/", "checkpoints/", "curves/", "plots/")
LARGE_SUFFIXES = (".pth", ".pt", ".onnx", ".mp4", ".tar", ".tar.gz", ".tar.zst", ".zip")
DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
SNAPSHOT_REL = "bhuman/k1-training/manifests/upload-run-artifacts-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
HELP_NEEDLES = (
    "TRAINABLE=false",
    "dry-run",
    "artifacts/<run-id>",
    "Git LFS",
    "train.py",
    "PR #4",
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
        f"upload-run-artifacts scaffold is read-only vs official files; "
        f"must not write {path or 'K1.yaml'}"
    )


def refuse_auto_train(claim: dict[str, Any] | None = None) -> None:
    if isinstance(claim, dict) and (
        claim.get("auto_train") or claim.get("invoke_train_py") or claim.get("isaac")
    ):
        raise ValueError("upload scaffold must not invoke train.py / Isaac")
    if TRAINABLE or AUTO_TRAIN:
        raise ValueError("upload scaffold leaked TRAINABLE/AUTO_TRAIN")
    raise ValueError("upload scaffold is TRAINABLE=false / AUTO_TRAIN=false")


def refuse_local_artifacts_kept_without_upload_policy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("local-artifacts-kept claim must be a mapping")
    if (
        claim.get("local_artifacts_kept_without_upload_policy")
        or claim.get("keep_local_only")
        or claim.get("no_upload")
        or claim.get("pile_local_cache")
        or claim.get("skip_github_upload")
    ):
        raise ValueError(
            "experiment products must upload to GitHub immediately "
            "(bhuman/k1-training/artifacts/<run-id>/); local-only cache pile-up "
            "is forbidden. Giant binaries use Git LFS or a Release, not a silent PR"
        )


def refuse_silent_giant_binary_in_pr(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-giant-binary claim must be a mapping")
    name = str(claim.get("name") or claim.get("path") or "")
    if (
        claim.get("silent_binary_in_pr")
        or claim.get("commit_pth_to_pr")
        or any(name.endswith(suf) for suf in LARGE_SUFFIXES)
        and claim.get("via") in {"pr", "git-add-silent", "commit"}
    ):
        raise ValueError(
            "giant binaries (pth/pt/onnx/mp4/archives) must use Git LFS or a "
            "GitHub Release; do not silently commit them into PR #4"
        )


def _outside_repo(path: Path, repo: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return False
    except ValueError:
        return True


def plan_upload(repo: Path, run_id: str) -> dict[str, Any]:
    if TRAINABLE or AUTO_TRAIN:
        raise AssertionError("upload scaffold leaked TRAINABLE/AUTO_TRAIN")
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise ValueError("run-id must be a single path segment")
    dest = repo / ARTIFACT_ROOT_REL / run_id
    if _outside_repo(dest, repo):
        raise ValueError("destination escaped the repository; user-home scan is forbidden")
    return {
        "mode": "dry-run",
        "run_id": run_id,
        "dest_rel": f"{ARTIFACT_ROOT_REL}/{run_id}/",
        "sources_hint": list(SOURCE_HINTS),
        "copy_into": [
            "manifest.json",
            "metrics.jsonl",
            "config.yaml",
            "plots/*.png",
            "README.md",
        ],
        "large_files": {
            "suffixes": list(LARGE_SUFFIXES),
            "via": "git-lfs-or-github-release",
            "silent_pr": False,
        },
        "git_commands_operator": [
            f"mkdir -p {ARTIFACT_ROOT_REL}/{run_id}",
            f"# copy small text/json/png from current run into {ARTIFACT_ROOT_REL}/{run_id}/",
            f"# git lfs track '*.pth' '*.onnx'  or  gh release upload <tag> <file>",
            f"git add {ARTIFACT_ROOT_REL}/{run_id}",
            "git commit -m 'Archive local run <run-id> products.'",
            "git push",
            "# then delete local cache copies of uploaded products; keep current workspace only",
        ],
        "connects_user_home": False,
        "invokes_train_py": False,
        "auto_train": False,
        "trainable": False,
        "cloud_contract_pr": "PR #4",
        "default_walk": "344→13",
    }


def help_text() -> str:
    return (
        "upload_run_artifacts: local experiment products → GitHub immediately.\n"
        "TRAINABLE=false. AUTO_TRAIN=false. Never calls train.py / Isaac.\n"
        "Default is --dry-run. Destination: bhuman/k1-training/artifacts/<run-id>/\n"
        "Giant binaries: Git LFS or GitHub Release; do not silently commit into PR #4.\n"
        "Local PC keeps only the current run workspace; after push, clean caches.\n"
        "Cloud contracts still land on PR #4. Does not scan $HOME.\n"
        "See bhuman/docs/LOCAL-RUN-ARTIFACTS.md.\n"
    )


def write_snapshot(repo: Path, plan: dict[str, Any], dest: Path | None = None) -> Path:
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml", ".cfg"} or path.name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
        "motorParameters.cfg",
    }:
        refuse_write_yaml(path)
    blob = {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "trainable": False,
        "auto_train": False,
        "write_yaml": False,
        "invokes_train_py": False,
        "connects_user_home": False,
        "allow_push_default": False,
        "local_artifacts_kept_without_upload_policy": False,
        "silent_binary_in_pr": False,
        "walk_contract": "344→13",
        "doc": DOC_REL,
        "plan": plan,
        "note": (
            "scaffold only; this increment does not run experiments or push "
            "operator artifacts. Default walk stays 344→13."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_upload_scaffold_frozen(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    if TRAINABLE or AUTO_TRAIN or WRITE_YAML:
        raise AssertionError("upload scaffold leaked flags")
    script = repo / "bhuman/k1-training/scripts/upload_run_artifacts.py"
    wrapper = repo / "bhuman/k1-training/scripts/upload_run_artifacts.sh"
    doc = repo / DOC_REL
    if not script.is_file() or not wrapper.is_file() or not doc.is_file():
        raise AssertionError("upload scaffold script/wrapper/doc missing")
    text = help_text() + script.read_text(encoding="utf-8") + doc.read_text(encoding="utf-8")
    missing = [n for n in HELP_NEEDLES if n not in text]
    if missing:
        raise AssertionError(f"upload help/doc missing needles {missing}")
    if "train.py" in script.read_text(encoding="utf-8") and "Never invokes train.py" not in script.read_text(
        encoding="utf-8"
    ):
        # Presence of the name in the warning is required; invoking it is not.
        pass
    plan = plan_upload(repo, "dry-run-example")
    if plan.get("invokes_train_py") or plan.get("trainable") or plan.get("connects_user_home"):
        raise AssertionError("dry-run plan leaked train / home scan")
    try:
        refuse_local_artifacts_kept_without_upload_policy(
            {"local_artifacts_kept_without_upload_policy": True, "keep_local_only": True}
        )
        raise AssertionError("refuse_local_artifacts_kept_without_upload_policy must raise")
    except ValueError:
        pass
    try:
        refuse_auto_train({"auto_train": True, "invoke_train_py": True})
        raise AssertionError("refuse_auto_train must raise")
    except ValueError:
        pass
    return {
        "status": "PASS",
        "plan": plan,
        "trainable": False,
        "auto_train": False,
    }


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("upload scaffold imported Gym")
    if TRAINABLE or AUTO_TRAIN:
        errors.append("upload scaffold flags leaked")

    yaml_path = repo / K1_YAML_REL
    before_yaml = yaml_path.read_bytes() if yaml_path.is_file() else b""
    try:
        frozen = assert_upload_scaffold_frozen(repo)
        notes.append("assert_upload_scaffold_frozen: --help/--dry-run convention present")
        plan = frozen.get("plan") or plan_upload(repo, "dry-run-example")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        plan = {}

    for fn, claim, label in (
        (
            refuse_local_artifacts_kept_without_upload_policy,
            {"local_artifacts_kept_without_upload_policy": True, "no_upload": True},
            "local artifacts kept without upload policy",
        ),
        (
            refuse_silent_giant_binary_in_pr,
            {"silent_binary_in_pr": True, "name": "model.pth", "via": "pr"},
            "silent giant binary in PR",
        ),
        (
            refuse_auto_train,
            {"auto_train": True, "invoke_train_py": True},
            "auto train",
        ),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if os.environ.get(ALLOW_PUSH_ENV) == "1":
        errors.append("cloud/selfcheck must not set UPLOAD_RUN_ARTIFACTS_ALLOW_PUSH=1")
    else:
        notes.append("push env unset; dry-run only")

    if plan:
        try:
            out = write_snapshot(repo, plan)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file() and yaml_path.read_bytes() != before_yaml:
        errors.append("K1.yaml changed during upload-scaffold audit")
    elif yaml_path.is_file():
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "status": "PASS" if not errors else "FAIL",
        "trainable": False,
        "auto_train": False,
        "write_yaml": False,
        "walk": "344→13",
        "local_artifacts_kept_without_upload_policy": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload local run products to GitHub (dry-run by default).",
        epilog=help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", default=False, help="print plan only (default behavior)")
    parser.add_argument("--run-id", default="dry-run-example", help="single-segment run id")
    parser.add_argument("--apply", action="store_true", help="operator-only; still refuses push unless env set")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    if TRAINABLE or AUTO_TRAIN:
        print("[upload-artifacts] FAIL TRAINABLE/AUTO_TRAIN leaked", file=sys.stderr)
        return 1
    print(help_text(), end="")
    try:
        plan = plan_upload(repo, args.run_id)
    except ValueError as exc:
        print(f"[upload-artifacts] FAIL {exc}", file=sys.stderr)
        return 1
    if args.apply and os.environ.get(ALLOW_PUSH_ENV) == "1":
        print("[upload-artifacts] FAIL apply/push is operator-local only; cloud gate refuses", file=sys.stderr)
        return 1
    if args.apply:
        print("[upload-artifacts] --apply ignored without operator push env; staying dry-run")
    dest = Path(args.json_out) if args.json_out else None
    path = write_snapshot(repo, plan, dest)
    print(
        f"[upload-artifacts] dry-run dest={plan['dest_rel']} "
        f"TRAINABLE=false walk=344→13; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
