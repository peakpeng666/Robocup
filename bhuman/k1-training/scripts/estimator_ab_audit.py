"""Validate draft-only estimator A/B as a bypass (not 344 / not train.py).

D_estimator_ab may only declare k1-estimators families. Reuses
draft_validator + env_registry_audit + k1-estimators TRAINABLE=false.
Must not write into 344 or register train.py. Never writes YAML.
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
for extra in (_DRAFT, _EST, _SCRIPTS):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    refuse_dim_rewrite,
    require_draft_only_flag,
)
from env_registry_audit import audit as env_registry_snapshot  # noqa: E402
from interface import REGISTRY_NAMES, TRAINABLE as EST_TRAINABLE, WALK_OBS  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
AUDIT_REL = "bhuman/k1-training/manifests/estimator-ab-audit-latest.json"
FACTOR = "D_estimator_ab"
DRAFT_PROPOSED_OK = frozenset({"estimator", "allowed", "actor_obs"})


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
        f"estimator A/B audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_missing_draft_only(data: dict[str, Any]) -> None:
    require_draft_only_flag(data)


def refuse_apply_to_live(data: dict[str, Any]) -> None:
    refuse_as_official_config_patch(data)
    if data.get("apply_to_live") is True:
        raise ValueError("estimator A/B draft must not set apply_to_live")


def refuse_write_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("344-write claim must be a mapping")
    if claim.get("write_344") is True or claim.get("concat_into_344") is True:
        raise ValueError("estimator A/B draft must not write into 344")
    if claim.get("num_observations") not in (None, 344):
        raise ValueError("estimator A/B must not rewrite num_observations")
    if claim.get("actor_obs") not in (None, 344):
        raise ValueError("estimator A/B actor_obs must stay 344")
    if claim.get("rewrites_344") is True:
        raise ValueError("estimator A/B must not set rewrites_344")


def refuse_register_train_py(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("train.py claim must be a mapping")
    if claim.get("register_train_py") is True or claim.get("registered_in_train_py") is True:
        raise ValueError("estimator A/B draft must not register train.py")
    task = claim.get("task")
    if task in {*REGISTRY_NAMES, "K1_Estimator", "k1-estimators"}:
        raise ValueError("estimator family is not a train.py task")


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or EST_TRAINABLE:
        raise AssertionError("estimator A/B audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    draft_path = repo / DRAFT_REL
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    refuse_missing_draft_only(data)
    refuse_apply_to_live(data)
    refuse_dim_rewrite(data)
    factor = ((data.get("factors") or {}).get(FACTOR) or {})
    proposed = factor.get("proposed_only") or {}
    if not isinstance(proposed, dict) or not proposed:
        raise AssertionError(f"{FACTOR} proposed_only missing")
    extra = set(proposed) - DRAFT_PROPOSED_OK
    if extra:
        raise AssertionError(f"{FACTOR} proposed unexpected keys {sorted(extra)}")
    if proposed.get("estimator") not in REGISTRY_NAMES:
        raise AssertionError("estimator A/B must name a k1-estimators family")
    allowed = proposed.get("allowed")
    if list(allowed or []) != list(REGISTRY_NAMES):
        raise AssertionError(f"estimator allowed must be {list(REGISTRY_NAMES)}")
    if proposed.get("actor_obs") != WALK_OBS:
        raise AssertionError("estimator A/B actor_obs must stay 344")
    refuse_write_344(
        {
            "actor_obs": proposed.get("actor_obs"),
            "rewrites_344": factor.get("rewrites_344"),
        }
    )
    if factor.get("rewrites_344") is not False:
        raise AssertionError("estimator draft must not rewrite 344")

    registry = env_registry_snapshot(repo)
    if registry.get("bypass_registered"):
        raise AssertionError(
            f"k1-estimators leaked into train.py registry: {registry['bypass_registered']}"
        )
    if "k1-estimators" not in (registry.get("bypass_checked") or []):
        raise AssertionError("env registry must still treat k1-estimators as bypass")
    refuse_register_train_py({"register_train_py": False})

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "estimators_trainable": False,
        "allowed": list(REGISTRY_NAMES),
        "draft": {
            "factor": FACTOR,
            "draft_only": True,
            "apply_to_live": False,
            "applied": False,
            "register_train_py": False,
            "write_344": False,
            "proposed_only": dict(proposed),
        },
        "registry": {
            "official_k1_registered": registry.get("official_k1_registered"),
            "bypass_registered": registry.get("bypass_registered") or [],
        },
        "trainable": False,
        "write_yaml": False,
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "note": (
            "D_estimator_ab is a bypass declaration only; "
            "k1-estimators TRAINABLE=false; not registered in train.py; actor stays 344"
        ),
    }


def write_audit(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = audit(repo)
    path = dest or (repo / AUDIT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_estimator_ab_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    draft = data.get("draft") or {}
    if draft.get("applied") or draft.get("write_344") or draft.get("register_train_py"):
        raise AssertionError("estimator A/B draft leaked onto 344 / train.py")
    if data.get("estimators_trainable") is not False:
        raise AssertionError("k1-estimators TRAINABLE leaked")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    try:
        path = write_audit(_repo(), Path(args.json_out) if args.json_out else None)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[estimator-ab] FAIL {exc}")
        return 1
    print(f"[estimator-ab] PASS bypass only; TRAINABLE=false; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
