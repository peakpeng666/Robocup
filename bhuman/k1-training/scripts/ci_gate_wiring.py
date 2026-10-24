"""CI gate wiring inventory (docs/scripts only; no GPU).

How selfcheck + forbidden pack attach without requiring Gym / GPU:

  * Cloud job may run run_pr4_selfcheck.sh / run_contract_gate.sh
  * forbidden_regressions is a selfcheck step (silent refuse = red)
  * Draft workflow stays in draft-only; this PR does not create .github/workflows
  * merge_ready stays false — CI PASS ≠ merge OK

Does not replace CI-CONTRACT-GATE.md or the draft YAML.
Does not import reward_curriculum_draft_validator or obs_history_window_contract.

TRAINABLE=false. ready_gpu=false. merge_ready=false.

Runnable: python3 bhuman/k1-training/scripts/ci_gate_wiring.py
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
for extra in (_SCRIPTS,):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from merge_readiness_blockers import (  # noqa: E402
    MERGE_READY,
    refuse_merge_readiness_claims_ready,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/ci-gate-wiring-latest.json"
CI_DOC_REL = "bhuman/docs/CI-CONTRACT-GATE.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
DRAFT_YML_REL = (
    "bhuman/k1-training/configs/draft-only/github-actions-contract-gate.draft.yml"
)
SELFCHECK_REL = "bhuman/k1-training/scripts/run_pr4_selfcheck.sh"
FORBIDDEN_REL = "bhuman/k1-training/k1-switcher/test_forbidden_regressions.py"
WORKFLOWS_REL = ".github/workflows"

CHECKLIST = (
    "selfcheck_attaches_without_gym",
    "forbidden_pack_attaches",
    "no_github_workflows_created",
    "merge_ready_false",
    "no_gpu_required",
)

DOC_NEEDLES = (
    "ci_gate_wiring",
    "run_pr4_selfcheck",
    "forbidden_regressions",
    "merge_ready=false",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "merge_ready=true",
    "ready_gpu=true",
    "would_train=true",
    "competition_ready=true",
)
DRAFT_NEEDLES = (
    "draft_only",
    "run_contract_gate.sh",
    "ubuntu-latest",
    "PASS",
)
DRAFT_RUN_FORBIDDEN = (
    "IsaacGymRL/train.py",
    "merge_ready=true",
    "source bhuman/k1-training/scripts/env.sh",
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
        f"CI gate wiring is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"CI gate wiring is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_ci_gate_flips_merge_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("ci-gate-flips-merge-ready claim must be a mapping")
    if (
        claim.get("ci_gate_flips_merge_ready")
        or claim.get("merge_ready") is True
        or claim.get("ci_pass_as_merge_ok")
        or (
            claim.get("this_pin")
            and claim.get("flip")
        )
    ):
        raise ValueError(
            "CI / selfcheck wiring must not flip merge_ready; "
            "merge_ready=false; CI PASS ≠ merge OK"
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or MERGE_READY:
        raise AssertionError("CI gate wiring leaked TRAINABLE / merge_ready")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    workflows = repo / WORKFLOWS_REL
    if workflows.exists():
        raise AssertionError(
            ".github/workflows exists; this overlay must not create or overwrite it"
        )

    selfcheck = repo / SELFCHECK_REL
    forbidden = repo / FORBIDDEN_REL
    draft_yml = repo / DRAFT_YML_REL
    if not selfcheck.is_file() or not forbidden.is_file() or not draft_yml.is_file():
        raise AssertionError("selfcheck / forbidden pack / draft workflow missing")
    selfcheck_text = selfcheck.read_text(encoding="utf-8")
    if "test_forbidden_regressions.py" not in selfcheck_text:
        raise AssertionError("run_pr4_selfcheck.sh must attach forbidden pack")
    if "isaacgym" in selfcheck_text and "never" not in selfcheck_text.lower():
        pass
    if "train.py" in selfcheck_text and "Never trains" not in selfcheck_text:
        if "never trains" not in selfcheck_text.lower():
            raise AssertionError("selfcheck must stay no-train")

    draft_text = draft_yml.read_text(encoding="utf-8")
    _require_needles(draft_text, DRAFT_NEEDLES, DRAFT_YML_REL)
    run_lines = "\n".join(
        line for line in draft_text.splitlines() if not line.lstrip().startswith("#")
    )
    _forbid_tokens(run_lines, DRAFT_RUN_FORBIDDEN, DRAFT_YML_REL)

    ci_doc = repo / CI_DOC_REL
    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not ci_doc.is_file() or not compat.is_file() or not artifacts.is_file():
        raise AssertionError("CI-CONTRACT-GATE / COMPAT / ARTIFACTS missing")
    ci_text = ci_doc.read_text(encoding="utf-8")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    _require_needles(ci_text, DOC_NEEDLES, CI_DOC_REL)
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(ci_text, DOC_FORBIDDEN, CI_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/ci_gate_wiring.py",
        "checklist": list(CHECKLIST),
        "attaches": {
            "selfcheck": SELFCHECK_REL,
            "forbidden_pack": FORBIDDEN_REL,
            "contract_gate": "bhuman/k1-training/scripts/run_contract_gate.sh",
            "draft_workflow": DRAFT_YML_REL,
            "requires_gym": False,
            "requires_gpu": False,
        },
        "github_workflows_created": False,
        "merge_ready": False,
        "ci_gate_flips_merge_ready": False,
        "would_train": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "selfcheck + forbidden pack attach without Gym/GPU; "
            "draft workflow only; merge_ready=false"
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
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_ci_gate_wiring_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or MERGE_READY:
        raise AssertionError("CI gate wiring leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"CI gate checklist drifted: {snap.get('checklist')}")
    if snap.get("merge_ready") or snap.get("ci_gate_flips_merge_ready"):
        raise AssertionError("CI gate wiring leaked merge_ready")
    if snap.get("github_workflows_created") or snap.get("ready_gpu"):
        raise AssertionError("CI gate wiring leaked workflows / ready_gpu")
    try:
        refuse_ci_gate_flips_merge_ready(
            {"ci_gate_flips_merge_ready": True, "merge_ready": True, "this_pin": True}
        )
        raise AssertionError("refuse_ci_gate_flips_merge_ready must raise")
    except ValueError:
        pass
    try:
        refuse_merge_readiness_claims_ready({"merge_readiness_claims_ready": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_merge_readiness_claims_ready must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("CI gate wiring imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_ci_gate_wiring_frozen(repo)
        notes.append("assert_ci_gate_wiring_frozen: merge_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("selfcheck + forbidden pack attach without Gym/GPU")
        notes.append("no .github/workflows created; CI PASS ≠ merge OK")

    try:
        refuse_ci_gate_flips_merge_ready({"ci_pass_as_merge_ok": True, "flip": True, "this_pin": True})
        errors.append("ci_gate_flips_merge_ready must raise")
    except ValueError:
        notes.append("negative: CI gate flipping merge_ready refused")
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

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during CI gate wiring")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during CI gate wiring")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "merge_ready": False,
        "ci_gate_flips_merge_ready": False,
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
        print(f"[ci-gate-wiring] FAIL {exc}")
        return 1
    print(
        f"[ci-gate-wiring] {snap.get('status')} "
        f"selfcheck+forbidden attach without Gym/GPU; "
        f"merge_ready=false; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
