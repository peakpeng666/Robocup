"""Validate draft-only disturbance / push curriculum (not applied to live).

Official live push_* stay on K1.yaml randomization. Draft
C_disturbance_curriculum must be draft_only and must not overwrite live.
Missing draft_only or apply_to_live → FAIL.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DRAFT = Path(__file__).resolve().parent.parent / "configs" / "draft-only"
if str(_DRAFT) not in sys.path:
    sys.path.insert(0, str(_DRAFT))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    require_draft_only_flag,
)

TRAINABLE = False
WRITE_YAML = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
AUDIT_REL = "bhuman/k1-training/manifests/disturbance-curriculum-audit-latest.json"
FACTOR = "C_disturbance_curriculum"
LIVE_PUSH = {
    "push_interval_s": 5.0,
    "push_duration_s": 2.0,
}
LIVE_PUSH_RANGES = {
    "push_force": [0.0, 10.0],
    "push_torque": [0.0, 2.0],
}
LIVE_PUSH_KEYS = frozenset(
    {*LIVE_PUSH, *LIVE_PUSH_RANGES, "domain_rand", "push_robots"}
)
DRAFT_PROPOSED_OK = frozenset({"reference_fall_events", "reference_end_events"})


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
        f"disturbance-curriculum audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_missing_draft_only(data: dict[str, Any]) -> None:
    require_draft_only_flag(data)


def refuse_apply_to_live(data: dict[str, Any]) -> None:
    refuse_as_official_config_patch(data)
    if data.get("apply_to_live") is True:
        raise ValueError("disturbance draft must not set apply_to_live")


def refuse_overwrite_live_push(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("push overwrite claim must be a mapping")
    keys = claim.get("keys") or claim.get("proposed_only") or {}
    if isinstance(keys, dict):
        names = list(keys)
    else:
        names = [str(k) for k in keys]
    target = str(claim.get("target") or "live")
    hits = [name for name in names if any(live in str(name) for live in LIVE_PUSH_KEYS)]
    if target in {"live", "k1.yaml", "official", "domain_rand"} and hits:
        raise ValueError(f"draft must not overwrite live push keys {hits}")


def _section(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(?:#.*)?$", text, re.M)
    if not match:
        return None
    start = match.end()
    nxt = re.search(r"^[A-Za-z_][\w]*:\s*(?:#.*)?$", text[start:], re.M)
    return text[start : start + nxt.start()] if nxt else text[start:]


def _parse_scalar(raw: str) -> Any:
    raw = raw.split("#", 1)[0].strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_parse_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    try:
        return float(raw) if ("." in raw or raw.endswith(".")) else int(raw)
    except ValueError:
        return raw


def parse_live_push(text: str) -> dict[str, Any]:
    block = _section(text, "randomization") or ""
    out: dict[str, Any] = {}
    for key in LIVE_PUSH:
        match = re.search(rf"^\s{{2}}{key}:\s*([^\n]+)$", block, re.M)
        out[key] = _parse_scalar(match.group(1)) if match else None
    for key in LIVE_PUSH_RANGES:
        match = re.search(
            rf"^\s{{2}}{key}:\s*\n\s+range:\s*(\[[^\]]+\])",
            block,
            re.M,
        )
        out[f"{key}.range"] = _parse_scalar(match.group(1)) if match else None
    return out


def _num_eq(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return all(_num_eq(a, b) for a, b in zip(left, right))
    try:
        return abs(float(left) - float(right)) < 1e-12
    except (TypeError, ValueError):
        return left == right


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("disturbance audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    live = parse_live_push(text)
    for key, expect in LIVE_PUSH.items():
        if not _num_eq(live.get(key), expect):
            raise AssertionError(f"live {key} drifted off {expect}: {live.get(key)}")
    for key, expect in LIVE_PUSH_RANGES.items():
        if not _num_eq(live.get(f"{key}.range"), expect):
            raise AssertionError(f"live {key}.range drifted off {expect}")

    draft_path = repo / DRAFT_REL
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    refuse_missing_draft_only(data)
    refuse_apply_to_live(data)
    factor = ((data.get("factors") or {}).get(FACTOR) or {})
    proposed = factor.get("proposed_only") or {}
    if not isinstance(proposed, dict) or not proposed:
        raise AssertionError(f"{FACTOR} proposed_only missing")
    refuse_overwrite_live_push({"target": "live", "proposed_only": proposed})
    extra = set(proposed) - DRAFT_PROPOSED_OK
    if extra:
        raise AssertionError(f"{FACTOR} proposed unexpected live-looking keys {sorted(extra)}")
    if factor.get("rewrites_344") is not False:
        raise AssertionError("disturbance draft must not rewrite 344")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "live_push": live,
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
            "live push_interval_s=5 / duration=2 / force[0,10] / torque[0,2]; "
            "draft C_disturbance_curriculum proposed_only, not applied"
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


def assert_disturbance_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    if data.get("live_overwritten") or (data.get("draft") or {}).get("applied"):
        raise AssertionError("disturbance draft leaked onto live")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    try:
        path = write_audit(_repo(), Path(args.json_out) if args.json_out else None)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[disturb-draft] FAIL {exc}")
        return 1
    print(f"[disturb-draft] PASS live push intact; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
