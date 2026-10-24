"""Read-only official command / velocity-command extract vs draft schedule.

Parses K1.yaml commands: keys. Missing curriculum/schedule keys are recorded
honestly. Draft-only A_command_schedule proposed values must not look applied.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
    "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
)
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
AUDIT_REL = "bhuman/k1-training/manifests/command-schedule-audit-latest.json"

COMMAND_KEYS = (
    "num_commands",
    "still_proportion",
    "slow_proportion",
    "proportion_correction",
    "lin_vel_x",
    "lin_vel_y",
    "ang_vel_yaw",
    "slow_walk_range",
    "resampling_time_s",
    "gait_frequency",
)
ABSENT_KEYS = ("curriculum", "schedule", "command_curriculum", "heading_command")
OFFICIAL_BASELINE = {
    "num_commands": 3,
    "still_proportion": 0.1,
    "slow_proportion": 0.1,
    "lin_vel_x": [-1.0, 2.0],
    "lin_vel_y": [-1.0, 1.0],
    "ang_vel_yaw": [-1.5, 1.5],
}


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
        f"command-schedule audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_draft_as_applied(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("applied-claim must be a mapping")
    if claim.get("applied") or claim.get("apply_to_live") or claim.get("is_official"):
        raise ValueError("draft command schedule must not be treated as applied")
    if claim.get("still_proportion") == 0.25 and claim.get("source") in {
        "official",
        "k1.yaml",
        "live",
    }:
        raise ValueError("official still_proportion leaked draft 0.25")


def _section(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(?:#.*)?$", text, re.M)
    if not match:
        return None
    start = match.end()
    nxt = re.search(r"^[A-Za-z_][\w]*:\s*(?:#.*)?$", text[start:], re.M)
    return text[start : start + nxt.start()] if nxt else text[start:]


def _parse_value(raw: str) -> Any:
    raw = raw.split("#", 1)[0].strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(part.strip()) for part in inner.split(",")]
    if raw in {"true", "false"}:
        return raw == "true"
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw.strip("\"'")


def parse_commands_block(text: str) -> dict[str, Any]:
    block = _section(text, "commands")
    if block is None:
        return {}
    out: dict[str, Any] = {}
    for line in block.splitlines():
        match = re.match(r"^\s{2}([A-Za-z_][\w]*):\s*(.+)$", line)
        if not match:
            continue
        out[match.group(1)] = _parse_value(match.group(2))
    return out


def _num_eq(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return all(_num_eq(a, b) for a, b in zip(left, right))
    try:
        return abs(float(left) - float(right)) < 1e-12
    except (TypeError, ValueError):
        return left == right


def _load_draft_schedule(repo: Path) -> dict[str, Any]:
    path = repo / DRAFT_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("draft_only") is not True:
        raise AssertionError("command-schedule draft missing draft_only:true")
    factor = ((data.get("factors") or {}).get("A_command_schedule") or {})
    proposed = factor.get("proposed_only") or {}
    if not isinstance(proposed, dict):
        raise ValueError("A_command_schedule.proposed_only must be a mapping")
    return {
        "draft_only": True,
        "applied": False,
        "proposed_only": dict(proposed),
        "factor": "A_command_schedule",
    }


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("command-schedule audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    yamls: list[dict[str, Any]] = []
    missing_keys: list[str] = []
    for rel in K1_YAML_RELS:
        path = repo / rel
        if "draft-only" in rel:
            raise AssertionError("must not read draft-only as official K1.yaml")
        text = path.read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError(f"{rel} drifted off 344→13")
        commands = parse_commands_block(text)
        present = {key: commands.get(key) for key in COMMAND_KEYS}
        absent = [key for key in ABSENT_KEYS if key not in commands]
        for key, expect in OFFICIAL_BASELINE.items():
            if key not in commands:
                raise AssertionError(f"{rel} commands missing {key}")
            if not _num_eq(commands[key], expect):
                raise AssertionError(f"{rel} commands.{key} drifted off {expect}")
        if commands.get("still_proportion") == 0.25:
            raise AssertionError("official still_proportion leaked draft 0.25")
        if "schedule" in commands:
            raise AssertionError("official commands.schedule must stay absent (draft-only)")
        missing_keys = absent
        yamls.append(
            {
                "rel": rel,
                "commands": present,
                "absent": absent,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    draft = _load_draft_schedule(repo)
    official_still = yamls[0]["commands"].get("still_proportion")
    proposed_still = (draft["proposed_only"] or {}).get("commands.still_proportion")
    if proposed_still is not None and _num_eq(official_still, proposed_still):
        raise AssertionError("draft still_proportion looks applied on official K1.yaml")
    refuse_draft_as_applied(
        {"applied": False, "source": "draft-only", "still_proportion": proposed_still}
    )

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "official": yamls,
        "missing_on_official": missing_keys,
        "draft": draft,
        "draft_applied": False,
        "trainable": False,
        "write_yaml": False,
        "note": (
            "official commands: still_proportion 0.1 + vel ranges; "
            "curriculum/schedule absent; draft A_command_schedule not applied"
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


def assert_schedule_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    if data.get("draft_applied"):
        raise AssertionError("draft command schedule must not be marked applied")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    try:
        path = write_audit(_repo(), Path(args.json_out) if args.json_out else None)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[command-sched] FAIL {exc}")
        return 1
    print(f"[command-sched] PASS official commands ≠ draft schedule; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
