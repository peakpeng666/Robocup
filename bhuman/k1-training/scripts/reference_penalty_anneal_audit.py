"""Validate draft-only reference-penalty anneal vs live 1.0.

E_reference_penalty_anneal may propose start/end/iters only.
Live walk-reference-stability-v1.json stays reference_mean_penalty: 1.0.
Reuses draft_validator + p1_draft_diff. Never writes YAML. TRAINABLE=false.
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
for extra in (_DRAFT, _SCRIPTS):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    official_live_rewards_untouched,
    refuse_as_official_config_patch,
    refuse_overwrite_live_rewards,
    require_draft_only_flag,
)
from p1_draft_diff import LIVE_REWARDS, official_algorithm_keys  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
REF_REL = "bhuman/k1-training/configs/walk-reference-stability-v1.json"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
AUDIT_REL = "bhuman/k1-training/manifests/reference-penalty-anneal-audit-latest.json"
FACTOR = "E_reference_penalty_anneal"
DRAFT_PROPOSED_OK = frozenset(
    {
        "reference_mean_penalty_start",
        "reference_mean_penalty_end",
        "anneal_iters",
    }
)
LIVE_PENALTY = 1.0


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
        f"reference-penalty anneal audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_missing_draft_only(data: dict[str, Any]) -> None:
    require_draft_only_flag(data)


def refuse_apply_to_live(data: dict[str, Any]) -> None:
    refuse_as_official_config_patch(data)
    if data.get("apply_to_live") is True:
        raise ValueError("anneal draft must not set apply_to_live")


def refuse_overwrite_live_penalty(claim: dict[str, Any]) -> None:
    refuse_overwrite_live_rewards(claim)
    proposed = claim.get("proposed_only") or {}
    if isinstance(proposed, dict) and "reference_mean_penalty" in proposed:
        raise ValueError("anneal draft must not propose the live reference_mean_penalty key")
    if claim.get("live_updated") is True:
        raise ValueError("anneal draft must not mark live reference_mean_penalty updated")


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("anneal audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    official_live_rewards_untouched(repo)

    official = official_algorithm_keys(repo)
    live = official["walk-reference-stability-v1.json"].get("reference_mean_penalty")
    if live != LIVE_PENALTY or live != LIVE_REWARDS["reference_mean_penalty"]:
        raise AssertionError(f"live reference_mean_penalty drifted off {LIVE_PENALTY}: {live}")

    draft_path = repo / DRAFT_REL
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    refuse_missing_draft_only(data)
    refuse_apply_to_live(data)
    factor = ((data.get("factors") or {}).get(FACTOR) or {})
    proposed = factor.get("proposed_only") or {}
    if not isinstance(proposed, dict) or not proposed:
        raise AssertionError(f"{FACTOR} proposed_only missing")
    extra = set(proposed) - DRAFT_PROPOSED_OK
    if extra:
        raise AssertionError(f"{FACTOR} proposed unexpected live keys {sorted(extra)}")
    refuse_overwrite_live_penalty({"target": "live", "proposed_only": proposed, "live_updated": False})
    if factor.get("rewrites_344") is not False:
        raise AssertionError("anneal draft must not rewrite 344")
    if proposed.get("reference_mean_penalty_start") != LIVE_PENALTY:
        raise AssertionError("anneal start must keep official 1.0 as the start snapshot")

    diff = {
        "key": "algorithm.reference_mean_penalty",
        "official": LIVE_PENALTY,
        "official_file": REF_REL,
        "proposed_only": dict(proposed),
        "live_updated": False,
    }

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "live_reference_mean_penalty": LIVE_PENALTY,
        "diff": diff,
        "draft": {
            "factor": FACTOR,
            "draft_only": True,
            "apply_to_live": False,
            "applied": False,
            "proposed_only": dict(proposed),
        },
        "live_overwritten": False,
        "trainable": False,
        "write_yaml": False,
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "ref_sha256": hashlib.sha256((repo / REF_REL).read_bytes()).hexdigest(),
        "note": (
            "live reference_mean_penalty stays 1.0 on walk-reference-stability-v1.json; "
            "E_reference_penalty_anneal proposed_only, not applied"
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


def assert_anneal_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    if data.get("live_overwritten") or (data.get("diff") or {}).get("live_updated"):
        raise AssertionError("anneal draft leaked onto live reference_mean_penalty")
    if data.get("live_reference_mean_penalty") != LIVE_PENALTY:
        raise AssertionError("live reference_mean_penalty drifted")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    try:
        path = write_audit(_repo(), Path(args.json_out) if args.json_out else None)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[anneal-draft] FAIL {exc}")
        return 1
    print(f"[anneal-draft] PASS live reference_mean_penalty=1.0; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
