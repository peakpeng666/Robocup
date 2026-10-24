"""Validate draft-only settle / jitter new keys (not applied to live).

B_settle_jitter may only propose new draft_* keys. Official K1.yaml has no
matching keys and action_rate stays -1. Reuses draft_validator.
Missing draft_only or apply_to_live → FAIL. Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DRAFT = Path(__file__).resolve().parent.parent / "configs" / "draft-only"
if str(_DRAFT) not in sys.path:
    sys.path.insert(0, str(_DRAFT))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    refuse_overwrite_live_rewards,
    require_draft_only_flag,
)

TRAINABLE = False
WRITE_YAML = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STABILITY_RELS = (
    "bhuman/k1-training/configs/walk-reference-stability-v1.json",
    "bhuman/k1-training/configs/walk-critic-stability-v1.json",
)
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
AUDIT_REL = "bhuman/k1-training/manifests/settle-jitter-audit-latest.json"
FACTOR = "B_settle_jitter"
DRAFT_PROPOSED_OK = frozenset(
    {"draft_settle_jitter_scale", "draft_zero_cmd_root_acc_scale"}
)
LIVE_OVERWRITE_KEYS = frozenset({"action_rate", "settle_jitter"})


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
        f"settle-jitter audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_missing_draft_only(data: dict[str, Any]) -> None:
    require_draft_only_flag(data)


def refuse_apply_to_live(data: dict[str, Any]) -> None:
    refuse_as_official_config_patch(data)
    if data.get("apply_to_live") is True:
        raise ValueError("settle/jitter draft must not set apply_to_live")


def refuse_overwrite_live_settle(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("settle overwrite claim must be a mapping")
    refuse_overwrite_live_rewards(claim)
    keys = claim.get("keys") or claim.get("proposed_only") or {}
    names = list(keys) if isinstance(keys, dict) else [str(k) for k in keys]
    target = str(claim.get("target") or "live")
    hits = [
        name
        for name in names
        if str(name).rsplit(".", 1)[-1] in LIVE_OVERWRITE_KEYS
    ]
    if target in {"live", "k1.yaml", "official", "config_patch"} and hits:
        raise ValueError(f"draft must not overwrite live settle/action_rate keys {hits}")
    if target in {"live", "k1.yaml", "official", "config_patch"} and claim.get(
        "apply_draft_keys_to_live"
    ):
        raise ValueError("draft settle keys must not be written onto live K1.yaml")


def _live_has_draft_keys(text: str) -> list[str]:
    return [key for key in DRAFT_PROPOSED_OK if key in text]


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("settle-jitter audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    if "action_rate: -1." not in text:
        raise AssertionError("live action_rate drifted off -1.")
    leaked = _live_has_draft_keys(text)
    if leaked:
        raise AssertionError(f"official K1.yaml leaked draft settle keys {leaked}")
    live_absent = sorted(DRAFT_PROPOSED_OK)
    for rel in STABILITY_RELS:
        leaked = _live_has_draft_keys((repo / rel).read_text(encoding="utf-8"))
        if leaked:
            raise AssertionError(f"{rel} leaked draft settle keys {leaked}")

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
        raise AssertionError(f"{FACTOR} proposed unexpected live-looking keys {sorted(extra)}")
    if "action_rate" in proposed:
        raise AssertionError("settle draft must not retune live action_rate")
    refuse_overwrite_live_settle({"target": "live", "proposed_only": proposed})
    if factor.get("rewrites_344") is not False:
        raise AssertionError("settle draft must not rewrite 344")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "live_absent_keys": live_absent,
        "live_action_rate": -1.0,
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
        "note": (
            "official live has no draft_settle_* keys; action_rate=-1. intact; "
            "B_settle_jitter proposed_only, not applied"
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


def assert_settle_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    if data.get("live_overwritten") or (data.get("draft") or {}).get("applied"):
        raise AssertionError("settle/jitter draft leaked onto live")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    try:
        path = write_audit(_repo(), Path(args.json_out) if args.json_out else None)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[settle-jitter] FAIL {exc}")
        return 1
    print(f"[settle-jitter] PASS live has no draft settle keys; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
