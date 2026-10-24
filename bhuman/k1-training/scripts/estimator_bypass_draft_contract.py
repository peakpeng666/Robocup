"""Estimator-bypass draft contract (read-only; no GPU).

Deepens estimator_ab_audit + k1-estimators without replacing them:

  * Draft D_estimator_ab keys stay draft_only / proposed_only
  * Stub paths already present are inventoried (hooks unwired)
  * Latent stays off official walk 344
  * apply_to_live=false
  * Overlay PASS is not a live estimator swap

TRAINABLE=false. walk↔kick GAP stays open.
Does not import torque_effort_timeseries_contract.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/estimator_bypass_draft_contract.py
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
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
_EST = _SCRIPTS.parent / "k1-estimators"
for extra in (_SCRIPTS, _DRAFT, _EST):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    require_draft_only_flag,
)
from estimator_ab_audit import (  # noqa: E402
    DRAFT_PROPOSED_OK,
    FACTOR,
    refuse_apply_to_live,
    refuse_register_train_py,
    refuse_write_344,
)
from hooks import assert_hooks_unwired  # noqa: E402
from interface import REGISTRY_NAMES, TRAINABLE as EST_TRAINABLE, WALK_OBS  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS_DIM = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
SNAPSHOT_REL = "bhuman/k1-training/manifests/estimator-bypass-draft-contract-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "draft_only_estimator_keys",
    "stub_paths_inventory",
    "hooks_unwired",
    "apply_to_live_false",
    "pass_not_live_estimator_swap",
)

STUB_PATHS = (
    "bhuman/k1-training/k1-estimators/interface.py",
    "bhuman/k1-training/k1-estimators/hooks.py",
    "bhuman/k1-training/k1-estimators/passthrough.py",
    "bhuman/k1-training/k1-estimators/rma_stub.py",
    "bhuman/k1-training/k1-estimators/dreamwaq_stub.py",
    "bhuman/k1-training/k1-estimators/check_estimators.py",
    "bhuman/k1-training/k1-estimators/test_estimators.py",
    "bhuman/k1-training/k1-estimators/test_estimator_bypass.py",
    "bhuman/k1-training/k1-estimators/README.md",
    "bhuman/k1-training/scripts/estimator_ab_audit.py",
)

DOC_NEEDLES = (
    "estimator_bypass_draft_contract",
    "apply_to_live=false",
    "D_estimator_ab",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
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
        f"estimator-bypass draft contract is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"estimator-bypass draft contract is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_estimator_pass_as_live_swap(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("estimator-pass-as-live-swap claim must be a mapping")
    if (
        claim.get("estimator_pass_as_live_swap")
        or claim.get("as_live_estimator_swap")
        or claim.get("live_estimator_swap")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and claim.get("live")
        )
    ):
        raise ValueError(
            "estimator-bypass draft PASS is not a live estimator swap; "
            "apply_to_live=false; hooks stay unwired; latent stays off 344"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _load_draft(repo: Path) -> dict[str, Any]:
    path = repo / DRAFT_REL
    if not path.is_file():
        raise AssertionError(f"missing {DRAFT_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("walk-p1-factors draft must be a mapping")
    return data


def _inventory_stub_paths(repo: Path) -> list[str]:
    found: list[str] = []
    missing: list[str] = []
    for rel in STUB_PATHS:
        if (repo / rel).is_file():
            found.append(rel)
        else:
            missing.append(rel)
    if missing:
        raise AssertionError(f"estimator stub paths missing {missing}")
    return found


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or EST_TRAINABLE:
        raise AssertionError("estimator-bypass overlay leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    draft = _load_draft(repo)
    require_draft_only_flag(draft)
    refuse_apply_to_live(draft)
    refuse_as_official_config_patch(draft)
    factors = draft.get("factors") or {}
    estimator = factors.get(FACTOR) or {}
    proposed = estimator.get("proposed_only") or {}
    if not isinstance(proposed, dict) or not proposed:
        raise AssertionError(f"{FACTOR} proposed_only missing")
    extra = set(proposed) - DRAFT_PROPOSED_OK
    if extra:
        raise AssertionError(f"{FACTOR} proposed unexpected keys {sorted(extra)}")
    if proposed.get("estimator") not in REGISTRY_NAMES:
        raise AssertionError("estimator A/B must name a k1-estimators family")
    if list(proposed.get("allowed") or []) != list(REGISTRY_NAMES):
        raise AssertionError(f"estimator allowed must be {list(REGISTRY_NAMES)}")
    if proposed.get("actor_obs") != WALK_OBS:
        raise AssertionError("estimator A/B actor_obs must stay 344")
    if estimator.get("rewrites_344"):
        raise AssertionError("D_estimator_ab must not rewrite 344")
    refuse_write_344(
        {
            "actor_obs": proposed.get("actor_obs"),
            "rewrites_344": estimator.get("rewrites_344"),
        }
    )
    refuse_register_train_py({"register_train_py": False})

    stub_paths = _inventory_stub_paths(repo)
    assert_hooks_unwired()

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

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/estimator_bypass_draft_contract.py",
        "checklist": list(CHECKLIST),
        "draft_rel": DRAFT_REL,
        "draft_only": True,
        "apply_to_live": False,
        "factor": FACTOR,
        "draft_estimator_keys": sorted(proposed),
        "proposed_only": dict(proposed),
        "allowed": list(REGISTRY_NAMES),
        "stub_paths": stub_paths,
        "hooks_unwired": True,
        "write_344": False,
        "register_train_py": False,
        "estimator_pass_as_live_swap": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "read-only estimator draft/stub inventory; apply_to_live=false; "
            "overlay PASS ≠ live estimator swap"
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


def assert_estimator_bypass_draft_contract_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("estimator-bypass overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"estimator-bypass checklist drifted: {snap.get('checklist')}")
    if snap.get("apply_to_live") or snap.get("estimator_pass_as_live_swap"):
        raise AssertionError("estimator-bypass leaked apply_to_live / live swap")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("estimator-bypass leaked ready_gpu / would_train / GAP-closed")
    if snap.get("write_344") or snap.get("register_train_py"):
        raise AssertionError("estimator-bypass leaked 344 write / train.py register")
    try:
        refuse_estimator_pass_as_live_swap(
            {
                "estimator_pass_as_live_swap": True,
                "as_live_estimator_swap": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_estimator_pass_as_live_swap must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("estimator-bypass draft contract imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_estimator_bypass_draft_contract_frozen(repo)
        notes.append("assert_estimator_bypass_draft_contract_frozen: apply_to_live=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append(
            f"draft keys={snap.get('draft_estimator_keys')}; "
            f"stubs={len(snap.get('stub_paths') or [])}; hooks unwired"
        )
        notes.append("overlay PASS ≠ live estimator swap")

    try:
        refuse_estimator_pass_as_live_swap(
            {"status": "PASS", "live": True, "this_pin": True}
        )
        errors.append("estimator_pass_as_live_swap must raise")
    except ValueError:
        notes.append("negative: overlay PASS as live estimator swap refused")
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
                errors.append(f"{label} changed during estimator-bypass overlay")
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
        "estimator_pass_as_live_swap": False,
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
        print(f"[estimator-bypass] FAIL {exc}")
        return 1
    print(
        f"[estimator-bypass] {snap.get('status')} "
        f"draft/stub inventory; apply_to_live=false; "
        f"PASS ≠ live estimator swap; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
