"""Local RTX 5090 pre-train checklist (inventory overlay; no GPU).

Glues existing operator-machine pins into one assert:

  * bh-gym interpreter declaration (~/.venvs/bh-gym)
  * Softlinked weights / meshes / third_party (operator-local; not scanned)
  * Disk headroom note from reserved-gpu checklist (honest if absent)
  * Dry-run command generator already present (print_train_dry_run)

ready_gpu stays false. Never launches train.py / Isaac.
existence_required_here=false (cloud must not scan $HOME).
TRAINABLE=false. walk↔kick GAP stays open.

Does not import walk_eval_artifact_crosscheck.
Does not re-audit local_bh_gym_dry_run wholesale.

Runnable: python3 bhuman/k1-training/scripts/local_rtx5090_pretrain_checklist.py
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

from local_bh_gym_dry_run import assert_local_dry_run_frozen  # noqa: E402
from print_train_dry_run import (  # noqa: E402
    LOCAL_BH_PY,
    LOCAL_LINKS,
    LOCAL_VENV,
    LOCAL_WORKTREE,
    WILL_RUN_ISAAC_GYM,
    WILL_RUN_TRAIN_PY,
    build_dry_run,
)
from probe_reserved_gpu import CHECKLIST_KEYS, TELL_USER_BEFORE_TRAIN  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
AUTO_TRAIN = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/local-rtx5090-pretrain-checklist-latest.json"
RESERVED_GPU_REL = "bhuman/k1-training/manifests/reserved-gpu-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
WALK_PTH_REL = "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"
MESH_REL = "bhuman/k1-training/src/IsaacGymRL/resources/K1/meshes"

CHECKLIST = (
    "bh_gym_interpreter",
    "softlinked_weights_meshes_third_party",
    "disk_headroom",
    "dry_run_command_generator",
    "ready_gpu_false",
    "never_launch_train",
)
SOFTLINK_DECLARED = LOCAL_LINKS + (WALK_PTH_REL, MESH_REL)

DOC_NEEDLES = (
    "local_rtx5090_pretrain_checklist",
    "~/.venvs/bh-gym",
    "third_party",
    "meshes",
    "TRAINABLE=false",
    "ready_gpu=false",
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
        f"RTX 5090 pre-train checklist is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"RTX 5090 pre-train checklist is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_reserved_gpu(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"RTX 5090 pre-train checklist must not write {path or 'reserved-gpu-latest.json'}"
    )


def refuse_silent_train_launch(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-train-launch claim must be a mapping")
    if (
        claim.get("silent_train_launch")
        or claim.get("will_run_train_py") is True
        or claim.get("exec_train")
        or claim.get("launch_train_without_user")
        or claim.get("auto_train") is True
        or (
            claim.get("this_pin")
            and (
                claim.get("subprocess")
                or claim.get("spawn_train")
                or claim.get("invoke_train_py")
            )
        )
    ):
        raise ValueError(
            "RTX 5090 pre-train checklist is print-only; "
            "must not silently launch train.py / Isaac. "
            f"Tell-user first: {TELL_USER_BEFORE_TRAIN}"
        )


def refuse_flip_ready_gpu_without_user(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("flip-ready-gpu-without-user claim must be a mapping")
    user_start = bool(
        claim.get("user_said_start") or claim.get("user_approved_start")
    )
    if (
        claim.get("flip_ready_gpu_without_user")
        or (
            claim.get("ready_gpu") is True
            and not user_start
        )
        or (
            claim.get("ready") is True
            and claim.get("this_pin")
            and not user_start
        )
    ):
        raise ValueError(
            "ready_gpu stays false until the user says start; "
            "checklist / stub must not flip it"
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


def _disk_note(repo: Path) -> dict[str, Any]:
    path = repo / RESERVED_GPU_REL
    if not path.is_file():
        return {
            "present": False,
            "ok": None,
            "detail": "reserved-gpu-latest.json absent; disk headroom noted as operator-local",
            "existence_required_here": False,
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    disk = (data.get("checklist") or {}).get("disk") or {}
    ready = bool(data.get("ready"))
    if ready:
        raise AssertionError("reserved-gpu ready=true; pre-train checklist must not treat this as start")
    return {
        "present": True,
        "ok": bool(disk.get("ok")),
        "detail": str(disk.get("detail") or "disk checklist present"),
        "ready": False,
        "existence_required_here": False,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or WILL_RUN_TRAIN_PY or WILL_RUN_ISAAC_GYM:
        raise AssertionError("RTX 5090 pre-train checklist leaked TRAINABLE / train flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

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

    dry = build_dry_run(repo)
    if dry.get("will_run_train_py") or dry.get("trainable"):
        raise AssertionError("dry-run generator leaked train / TRAINABLE")
    if dry.get("ready_gpu"):
        raise AssertionError("dry-run generator leaked ready_gpu=true")

    steps = [
        _call_assert("local_bh_gym_dry_run", assert_local_dry_run_frozen, repo),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "RTX 5090 pre-train checklist segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    disk = _disk_note(repo)
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/local_rtx5090_pretrain_checklist.py",
        "checklist": list(CHECKLIST),
        "local": {
            "venv": LOCAL_VENV,
            "bh_py": LOCAL_BH_PY,
            "worktree": LOCAL_WORKTREE,
            "softlinks_declared": list(SOFTLINK_DECLARED),
            "existence_required_here": False,
            "note": "operator-machine declarations; cloud must not scan $HOME",
        },
        "disk_headroom": disk,
        "dry_run": {
            "task": "K1",
            "walk": "344→13",
            "will_run_train_py": False,
            "trainable": False,
            "checklist_keys": list(CHECKLIST_KEYS),
            "tell_user": TELL_USER_BEFORE_TRAIN,
        },
        "steps": steps,
        "ready_gpu": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "will_exec_train_here": False,
        "silent_train_launch": False,
        "flip_ready_gpu_without_user": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "RTX 5090 pre-train checklist: bh-gym / softlinks / disk note / "
            "print-only dry-run; ready_gpu=false; never launch train"
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
        "walkingEngine.cfg",
        "reserved-gpu-latest.json",
    }:
        refuse_write_reserved_gpu(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_local_rtx5090_pretrain_checklist_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN:
        raise AssertionError("RTX 5090 pre-train checklist leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"pre-train checklist drifted: {snap.get('checklist')}")
    if snap.get("ready_gpu") or snap.get("will_run_train_py") or snap.get("will_exec_train_here"):
        raise AssertionError("pre-train checklist leaked ready_gpu / train")
    if (
        snap.get("silent_train_launch")
        or snap.get("flip_ready_gpu_without_user")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("pre-train checklist leaked silent-train / ready-flip / GAP-closed")
    try:
        refuse_silent_train_launch(
            {"silent_train_launch": True, "will_run_train_py": True, "this_pin": True}
        )
        raise AssertionError("refuse_silent_train_launch must raise")
    except ValueError:
        pass
    try:
        refuse_flip_ready_gpu_without_user(
            {"flip_ready_gpu_without_user": True, "ready_gpu": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_flip_ready_gpu_without_user must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("RTX 5090 pre-train checklist imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    reserved = repo / RESERVED_GPU_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest() if reserved.is_file() else ""
    try:
        snap = assert_local_rtx5090_pretrain_checklist_frozen(repo)
        notes.append("assert_local_rtx5090_pretrain_checklist_frozen: ready_gpu=false; no train")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("bh-gym / softlinks / disk note / dry-run glued; existence_required_here=false")
        notes.append("print-only; never launch train.py")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_silent_train_launch(
            {"silent_train_launch": True, "launch_train_without_user": True}
        )
        errors.append("silent_train_launch must raise")
    except ValueError:
        notes.append("negative: silent train launch refused")
    try:
        refuse_flip_ready_gpu_without_user(
            {"ready_gpu": True, "this_pin": True}
        )
        errors.append("flip_ready_gpu_without_user must raise")
    except ValueError:
        notes.append("negative: flip ready_gpu without user refused")
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
            errors.append("K1.yaml changed during RTX 5090 pre-train checklist pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during RTX 5090 pre-train checklist pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if reserved.is_file():
        after_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest()
        if before_gpu != after_gpu:
            errors.append("reserved-gpu-latest.json changed during RTX 5090 pre-train checklist pin")
        else:
            notes.append("reserved-gpu-latest.json untouched (ready stays false)")

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
        "ready_gpu": False,
        "silent_train_launch": False,
        "flip_ready_gpu_without_user": False,
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
        print(f"[rtx5090-checklist] FAIL {exc}")
        return 1
    print(
        f"[rtx5090-checklist] {snap.get('status')} "
        f"ready_gpu=false; print-only; never launch train; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
