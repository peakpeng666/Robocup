"""Local RTX 5090 / bh-gym pre-train dry-run path pin (print-only).

Pins the operator-machine contract next to print_train_dry_run:

  * Interpreter: ~/.venvs/bh-gym (CPython 3.8 + RTX 5090)
  * Worktree: ~/Desktop/Robocup-pr4
  * Shared links: third_party / downloads / cache (not in git)
  * Dry-run commands must name those local paths
  * ready_gpu stays false unless probe checklist is all true
  * stubs must not flip ready_gpu
  * TRAINABLE=false; dry-run must not auto-start train.py / Isaac

Does not re-audit print_train_dry_run / probe_reserved_gpu /
reactive_stub_hardening / upload_run_artifacts wholesale.
Never writes K1.yaml or official cfg. Does not scan $HOME.
walk↔kick GAP stays open (draft only).
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
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from print_train_dry_run import (  # noqa: E402
    BANNER,
    LOCAL_BH_PY,
    LOCAL_LINKS,
    LOCAL_TRAIN_PY_DRAFT,
    LOCAL_VENV,
    LOCAL_WORKTREE,
    LOCAL_WRAPPER_DRAFT,
    TRAINABLE as DRY_TRAINABLE,
    WILL_RUN_ISAAC_GYM,
    WILL_RUN_TRAIN_PY,
    WRITE_YAML as DRY_WRITE_YAML,
    build_dry_run,
    refuse_exec_flag,
)
from probe_reserved_gpu import CHECKLIST_KEYS, WILL_RUN_TRAIN_PY as PROBE_WILL_TRAIN  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
AUTO_TRAIN = False
WILL_RUN_TRAIN = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/local-bh-gym-dry-run-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

SIBLINGS = (
    "print_train_dry_run.py",
    "probe_reserved_gpu.py",
    "reactive_stub_hardening.py",
    "upload_run_artifacts.py",
    "bounded_walk_replay.py",
)

DOC_NEEDLES = (
    "~/.venvs/bh-gym",
    "~/Desktop/Robocup-pr4",
    "third_party",
    "downloads",
    "cache",
    "ready_gpu",
    "TRAINABLE=false",
    "344→13",
    "gap_closed=false",
    "local_bh_gym_dry_run.py",
    "bounded_walk_replay.py",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
    "自动开训",
    "ready_gpu=true 因 stub",
)
ARTIFACT_NEEDLES = (
    "TRAINABLE=false",
    "不自动开训",
    "artifacts/<run-id>",
    "runs/",
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
        f"local bh-gym dry-run pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"local bh-gym dry-run pin is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_dry_run_auto_starts_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("dry-run-auto-starts-train claim must be a mapping")
    if (
        claim.get("dry_run_auto_starts_train")
        or claim.get("auto_train")
        or claim.get("will_run_train_py")
        or claim.get("invoke_train_py")
        or claim.get("spawn_isaac")
        or claim.get("trainable") is True
        or (
            str(claim.get("source") or claim.get("script") or "")
            in {
                "print_train_dry_run",
                "print_train_dry_run.py",
                "local_bh_gym_dry_run",
                "local_bh_gym_dry_run.py",
            }
            and (
                claim.get("exec")
                or claim.get("run")
                or claim.get("train")
                or claim.get("subprocess")
            )
        )
    ):
        raise ValueError(
            "pre-train dry-run is print-only; it must not auto-start train.py / Isaac. "
            "TRAINABLE=false until the operator explicitly says 开训"
        )


def refuse_ready_gpu_true_without_checklist(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("ready-gpu-true-without-checklist claim must be a mapping")
    missing = list(claim.get("missing") or [])
    checklist = claim.get("checklist") or {}
    incomplete = missing or any(
        not (checklist.get(key) or {}).get("ok") for key in CHECKLIST_KEYS if checklist
    )
    if (
        claim.get("ready_gpu_true_without_checklist")
        or (
            claim.get("ready_gpu") is True
            and (incomplete or claim.get("stub") or claim.get("source") == "stub")
        )
        or (claim.get("ready") is True and (incomplete or claim.get("from_stub")))
    ):
        raise ValueError(
            "ready_gpu may be true only when cuda / isaacgym_or_alt / disk / "
            "official_k1_task / checkpoint are all true; stubs must not flip ready"
        )


def refuse_local_compat_doc_claims_gap_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("local-compat-doc-claims-gap-closed claim must be a mapping")
    source = str(claim.get("source") or claim.get("doc") or "")
    if (
        claim.get("local_compat_doc_claims_gap_closed")
        or claim.get("gap_closed") is True
        or claim.get("walk_kick_gap_closed")
        or (
            source
            in {
                "LOCAL-BH-GYM-COMPAT",
                "LOCAL-BH-GYM-COMPAT.md",
                "local_bh_gym_dry_run",
            }
            and (
                claim.get("status") == "CLOSED"
                or claim.get("gap") == "closed"
                or claim.get("closed") is True
            )
        )
    ):
        raise ValueError(
            "LOCAL-BH-GYM-COMPAT must keep walk↔kick resetHistoryData as GAP "
            "(gap_closed=false); draft-only, not live"
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG or AUTO_TRAIN or WILL_RUN_TRAIN:
        raise AssertionError("local bh-gym dry-run leaked TRAINABLE / auto-train flags")
    if DRY_TRAINABLE or DRY_WRITE_YAML or WILL_RUN_TRAIN_PY or WILL_RUN_ISAAC_GYM:
        raise AssertionError("print_train_dry_run leaked TRAINABLE / will_run flags")
    if PROBE_WILL_TRAIN:
        raise AssertionError("probe_reserved_gpu leaked will_run_train_py")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file():
        raise AssertionError(f"missing {COMPAT_DOC_REL}")
    if not artifacts.is_file():
        raise AssertionError(f"missing {ARTIFACTS_DOC_REL}")
    compat_text = compat.read_text(encoding="utf-8")
    artifacts_text = artifacts.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _require_needles(artifacts_text, ARTIFACT_NEEDLES, ARTIFACTS_DOC_REL)

    dry = build_dry_run(repo)
    local_drafts = (
        str(dry.get("local_train_py_draft") or ""),
        str(dry.get("local_wrapper_draft") or ""),
        LOCAL_TRAIN_PY_DRAFT,
        LOCAL_WRAPPER_DRAFT,
    )
    for draft in local_drafts:
        if LOCAL_VENV.split("/")[-1] not in draft and "~/.venvs/bh-gym" not in draft and "$HOME/.venvs/bh-gym" not in draft:
            raise AssertionError(f"dry-run draft must name local bh-gym path: {draft!r}")
        if "Robocup-pr4" not in draft:
            raise AssertionError(f"dry-run draft must name ~/Desktop/Robocup-pr4: {draft!r}")
        if "--task K1" not in draft and "run_walk_stability.sh" not in draft:
            raise AssertionError(f"local draft must stay official K1 / walk wrapper: {draft!r}")
        if "K1_Reactive" in draft or "train.py --exec" in draft:
            raise AssertionError("local draft leaked reactive task or exec flag")
    if dry.get("will_run_train_py") or dry.get("trainable") or dry.get("dry_run_success_means_trainable"):
        raise AssertionError("dry-run must stay print-only / TRAINABLE=false")
    if dry.get("ready_gpu") and dry.get("missing"):
        raise AssertionError("ready_gpu=true is illegal while checklist missing items")

    missing_sib = [name for name in SIBLINGS if not (_SCRIPTS / name).is_file()]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "local": {
            "venv": LOCAL_VENV,
            "bh_py": LOCAL_BH_PY,
            "worktree": LOCAL_WORKTREE,
            "links": list(LOCAL_LINKS),
            "existence_required_here": False,
            "note": "paths are operator-machine declarations; cloud must not scan $HOME",
        },
        "dry_run": {
            "banner": BANNER,
            "task": "K1",
            "walk": "344→13",
            "trainable": False,
            "will_run_train_py": False,
            "will_run_isaac_gym": False,
            "ready_gpu": bool(dry.get("ready_gpu")),
            "missing": list(dry.get("missing") or []),
            "checklist_keys": list(CHECKLIST_KEYS),
            "local_wrapper_draft": LOCAL_WRAPPER_DRAFT,
            "local_train_py_draft": LOCAL_TRAIN_PY_DRAFT,
        },
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "dry_run_auto_starts_train": False,
        "ready_gpu_true_without_checklist": False,
        "local_compat_doc_claims_gap_closed": False,
        "fabricated": False,
        "note": (
            "operator dry-run commands point at ~/.venvs/bh-gym and "
            "~/Desktop/Robocup-pr4; ready_gpu stays false unless checklist is all true; "
            "TRAINABLE=false; walk↔kick GAP still open"
        ),
        "trainable": False,
        "auto_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else "",
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


def assert_local_dry_run_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or AUTO_TRAIN or WILL_RUN_TRAIN:
        raise AssertionError("local dry-run leaked auto-train")
    if snap.get("dry_run_auto_starts_train") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("dry-run leaked auto-train or GAP-closed")
    dry = snap.get("dry_run") or {}
    if dry.get("will_run_train_py") or dry.get("trainable"):
        raise AssertionError("dry-run leaked will_run_train_py")
    if dry.get("ready_gpu") and dry.get("missing"):
        raise AssertionError("ready_gpu=true with missing checklist")
    try:
        refuse_exec_flag(["--exec"])
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_exec_flag(--exec) must raise")
    try:
        refuse_dry_run_auto_starts_train(
            {"dry_run_auto_starts_train": True, "will_run_train_py": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_dry_run_auto_starts_train must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("local bh-gym dry-run imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_local_dry_run_frozen(repo)
        notes.append("assert_local_dry_run_frozen: local paths + print-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("dry-run commands name ~/.venvs/bh-gym and ~/Desktop/Robocup-pr4")
        notes.append("ready_gpu stays false unless checklist all true; stub ≠ ready")
        notes.append("walk↔kick GAP stays open; TRAINABLE=false")

    try:
        refuse_dry_run_auto_starts_train(
            {"dry_run_auto_starts_train": True, "source": "print_train_dry_run"}
        )
        errors.append("dry_run_auto_starts_train must raise")
    except ValueError:
        notes.append("negative: dry-run auto-starts train refused")
    try:
        refuse_ready_gpu_true_without_checklist(
            {
                "ready_gpu_true_without_checklist": True,
                "ready_gpu": True,
                "missing": ["cuda"],
            }
        )
        errors.append("ready_gpu_true_without_checklist must raise")
    except ValueError:
        notes.append("negative: ready_gpu true without checklist refused")
    try:
        refuse_local_compat_doc_claims_gap_closed(
            {
                "local_compat_doc_claims_gap_closed": True,
                "source": "LOCAL-BH-GYM-COMPAT.md",
                "gap_closed": True,
            }
        )
        errors.append("local_compat_doc_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: local compat doc claims GAP closed refused")
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
            errors.append("K1.yaml changed during local bh-gym dry-run pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during local bh-gym dry-run pin")
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
        "ready_gpu": bool((snap.get("dry_run") or {}).get("ready_gpu")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        refuse_exec_flag(sys.argv[1:])
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[local-dry] FAIL {exc}")
        return 1
    print(
        f"[local-dry] {snap.get('status')} "
        f"bh-gym + Robocup-pr4 print-only; ready_gpu="
        f"{(snap.get('dry_run') or {}).get('ready_gpu')}; "
        f"GAP open; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
