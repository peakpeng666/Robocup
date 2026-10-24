"""PR #4 merge-readiness blockers (still NOT ready).

Read-only overlay. merge_ready=false always. Does not flip ready_gpu.
Does not write reserved-gpu-latest.json.

Blockers that stay open this increment:

  * walk↔kick resetHistoryData GAP (gap_closed=false; draft only)
  * ready_gpu=false
  * TRAINABLE=false
  * report-only quality (PASS ≠ 比赛合格)

Never writes yaml / cfg / weights. Never trains. Never merges.
Does not import walk_onnx_export_dry_run or missing_weight_skip_honesty.

Runnable: python3 bhuman/k1-training/scripts/merge_readiness_blockers.py
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
APPLY_TO_LIVE = False
MERGE_READY = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/merge-readiness-blockers-latest.json"
RESERVED_GPU_REL = "bhuman/k1-training/manifests/reserved-gpu-latest.json"
CHECKLIST_DOC_REL = "bhuman/docs/PR4-MERGE-CHECKLIST.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

BLOCKERS = (
    "walk_kick_resetHistoryData_GAP",
    "ready_gpu=false",
    "TRAINABLE=false",
    "report_only_quality",
)

CHECKLIST_NEEDLES = (
    "merge_readiness_blockers",
    "ready_gpu=false",
    "TRAINABLE=false",
    "gap_closed=false",
    "REPORT_ONLY",
)
ARTIFACTS_NEEDLES = (
    "merge_readiness_blockers",
    "merge_ready=false",
    "ready_gpu=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "merge_ready=true",
    "ready_gpu=true",
    "gap_closed=true",
    "GAP 已闭合",
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
        f"merge-readiness blockers are read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"merge-readiness blockers are read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_reserved_gpu(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"merge-readiness blockers must not write {path or 'reserved-gpu-latest.json'}"
    )


def refuse_merge_readiness_claims_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("merge-readiness-claims-ready claim must be a mapping")
    status = str(claim.get("status") or "")
    if (
        claim.get("merge_readiness_claims_ready")
        or claim.get("merge_ready") is True
        or claim.get("已可合并")
        or status in {"merge_ready", "ready", "已可合并"}
    ):
        raise ValueError(
            "PR #4 merge-readiness stays merge_ready=false; "
            "GAP / ready_gpu=false / TRAINABLE=false / REPORT_ONLY still block"
        )


def refuse_merge_flips_ready_flag(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("merge-flips-ready-flag claim must be a mapping")
    if (
        claim.get("merge_flips_ready_flag")
        or claim.get("ready_gpu") is True
        or claim.get("flip_ready_gpu")
        or claim.get("write_reserved_gpu")
        or (
            claim.get("ready") is True
            and claim.get("this_pin")
        )
    ):
        raise ValueError(
            "merge-readiness must not flip ready_gpu / reserved-gpu ready; "
            "ready stays false until the user says start"
        )


def refuse_merge_readiness_pass_as_merge_ok(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("merge-readiness-pass-as-merge-ok claim must be a mapping")
    status = str(claim.get("status") or "")
    if (
        claim.get("merge_readiness_pass_as_merge_ok")
        or claim.get("inventory_pass_as_merge")
        or claim.get("treat_pass_as_merge_ok")
        or (
            status == "PASS"
            and (
                claim.get("as_merge_ok")
                or claim.get("will_merge")
                or claim.get("merge_now")
            )
        )
    ):
        raise ValueError(
            "merge-readiness PASS is inventory-only; "
            "PASS ≠ merge OK; merge_ready stays false"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _read_ready_gpu(repo: Path) -> dict[str, Any]:
    path = repo / RESERVED_GPU_REL
    if not path.is_file():
        return {
            "present": False,
            "ready": False,
            "reason": "reserved-gpu-latest.json absent; treat ready_gpu=false",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    ready = bool(data.get("ready"))
    if ready:
        raise AssertionError(
            "reserved-gpu-latest.json ready=true; merge-readiness must not treat this as start"
        )
    return {
        "present": True,
        "ready": False,
        "skipped": bool(data.get("skipped")),
        "reason": "reserved-gpu ready stays false",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or MERGE_READY:
        raise AssertionError("merge-readiness leaked TRAINABLE / WRITE / merge_ready flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    checklist_doc = repo / CHECKLIST_DOC_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    if not checklist_doc.is_file() or not artifacts_doc.is_file():
        raise AssertionError("PR4-MERGE-CHECKLIST / LOCAL-RUN-ARTIFACTS missing")
    check_text = checklist_doc.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    _require_needles(check_text, CHECKLIST_NEEDLES, CHECKLIST_DOC_REL)
    _require_needles(art_text, ARTIFACTS_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(check_text, DOC_FORBIDDEN, CHECKLIST_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    gpu = _read_ready_gpu(repo)
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/merge_readiness_blockers.py",
        "blockers": list(BLOCKERS),
        "merge_ready": False,
        "ready_gpu": False,
        "reserved_gpu": gpu,
        "will_write_reserved_gpu": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "will_merge": False,
        "merge_readiness_claims_ready": False,
        "merge_flips_ready_flag": False,
        "merge_readiness_pass_as_merge_ok": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "apply_to_live": False,
        "fabricated": False,
        "note": (
            "PR #4 still NOT merge-ready: walk↔kick GAP open, "
            "ready_gpu=false, TRAINABLE=false, quality REPORT_ONLY"
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
    if path.suffix in {".yaml", ".yml", ".cfg", ".onnx", ".pth"} or name in {
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


def assert_merge_readiness_blockers_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or MERGE_READY:
        raise AssertionError("merge-readiness leaked flags")
    if snap.get("merge_ready") or snap.get("ready_gpu") or snap.get("will_merge"):
        raise AssertionError("merge-readiness leaked merge_ready / ready_gpu")
    if snap.get("blockers") != list(BLOCKERS):
        raise AssertionError(f"blocker table drifted: {snap.get('blockers')}")
    if snap.get("will_write_reserved_gpu") or snap.get("will_run_train_py"):
        raise AssertionError("merge-readiness leaked reserved-gpu write / train")
    if (
        snap.get("merge_readiness_claims_ready")
        or snap.get("merge_flips_ready_flag")
        or snap.get("merge_readiness_pass_as_merge_ok")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("merge-readiness leaked ready / flip / GAP-closed")
    try:
        refuse_merge_readiness_claims_ready(
            {"merge_readiness_claims_ready": True, "merge_ready": True}
        )
        raise AssertionError("refuse_merge_readiness_claims_ready must raise")
    except ValueError:
        pass
    try:
        refuse_merge_readiness_pass_as_merge_ok(
            {
                "merge_readiness_pass_as_merge_ok": True,
                "status": "PASS",
                "as_merge_ok": True,
            }
        )
        raise AssertionError("refuse_merge_readiness_pass_as_merge_ok must raise")
    except ValueError:
        pass
    try:
        refuse_merge_flips_ready_flag(
            {"merge_flips_ready_flag": True, "ready_gpu": True, "this_pin": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_merge_flips_ready_flag must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("merge-readiness blockers imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    reserved = repo / RESERVED_GPU_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest() if reserved.is_file() else ""
    try:
        snap = assert_merge_readiness_blockers_frozen(repo)
        notes.append("assert_merge_readiness_blockers_frozen: merge_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("blockers: GAP / ready_gpu=false / TRAINABLE=false / REPORT_ONLY")
        notes.append("did not write reserved-gpu-latest.json; did not flip ready")
        warnings.append("PR #4 still NOT merge-ready")

    try:
        refuse_merge_readiness_claims_ready(
            {"merge_readiness_claims_ready": True, "已可合并": True}
        )
        errors.append("merge_readiness_claims_ready must raise")
    except ValueError:
        notes.append("negative: merge-readiness claims ready refused")
    try:
        refuse_merge_flips_ready_flag(
            {"merge_flips_ready_flag": True, "write_reserved_gpu": True}
        )
        errors.append("merge_flips_ready_flag must raise")
    except ValueError:
        notes.append("negative: merge flips ready_gpu refused")
    try:
        refuse_merge_readiness_pass_as_merge_ok(
            {
                "merge_readiness_pass_as_merge_ok": True,
                "status": "PASS",
                "will_merge": True,
            }
        )
        errors.append("merge_readiness_pass_as_merge_ok must raise")
    except ValueError:
        notes.append("negative: merge-readiness PASS as merge OK refused")
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
    try:
        refuse_write_reserved_gpu(reserved)
        errors.append("refuse_write_reserved_gpu must raise")
    except RuntimeError:
        notes.append("write-back of reserved-gpu-latest.json refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during merge-readiness pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during merge-readiness pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if reserved.is_file():
        after_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest()
        if before_gpu != after_gpu:
            errors.append("reserved-gpu-latest.json changed during merge-readiness pin")
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
        "merge_ready": False,
        "ready_gpu": False,
        "merge_readiness_claims_ready": False,
        "merge_flips_ready_flag": False,
        "merge_readiness_pass_as_merge_ok": False,
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
        print(f"[merge-blockers] FAIL {exc}")
        return 1
    print(
        f"[merge-blockers] {snap.get('status')} "
        f"merge_ready=false; ready_gpu=false; GAP open; TRAINABLE=false; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
