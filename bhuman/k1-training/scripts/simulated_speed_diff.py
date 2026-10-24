"""Read-only Simulated vs Default walkingEngine speed-diff allowlist.

Extracts speed-related key diffs (intentional set). Net-slot / dimension
diffs → FAIL. Simulated speed diffs do not close the PD domain gap.
Never writes walkingEngine.cfg or K1.yaml. TRAINABLE=false.
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

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from motor_parameters_audit import refuse_simulated_speed_as_pd_closed  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
WALK_DEFAULT_ONNX = "K1_walk.onnx"
KICK_ONNX = "K1_kick_inner.onnx"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/simulated-speed-diff-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SIM_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"

# Frozen intentional Simulated vs Default speed / plant diffs (not net slot).
ALLOWED_SPEED_DIFFS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("configuredParameters.fastWalkSpeed.maxSpeed.translation.x", "1000", "2000"),
        ("configuredParameters.fastWalkSpeed.maxSpeed.translation.y", "500", "1500"),
        ("configuredParameters.fastWalkSpeed.maxSpeedBackwards", "500", "1000"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.rotation", "120deg", "90deg"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.translation.x", "1000", "1250"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.translation.y", "500", "750"),
        ("configuredParameters.slowWalkSpeed.maxSpeed.translation.x", "1000", "750"),
        ("configuredParameters.maxPossibleSpeed.maxSpeed.translation.y", "1000", "1500"),
        ("configuredParameters.maxForwardAtMaxSide", "600", "1000"),
        ("commonSpeedParameters.maxAcceleration.x", "20", "60"),
        ("commonSpeedParameters.xTargetScaling.walkSpeed.min", "1000", "400"),
        ("commonSpeedParameters.yTargetScaling.walkSpeed.min", "1000", "300"),
        ("commonSpeedParameters.rotationTargetScaling.walkSpeed.min", "2", "1.5"),
        ("commonSpeedParameters.rotationTargetScaling.walkSpeed.max", "3", "2"),
    }
)
ALLOWED_PLANT_DIFFS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("standAnkleStiffness.min", "60", "100"),
        ("standAnkleStiffness.max", "80", "100"),
    }
)
NET_SLOT_KEYS = frozenset(
    {
        "walkNeuronalNetworkParameters.modelName",
        "walkNeuronalNetworkParameters.numInput",
        "walkNeuronalNetworkParameters.numOutput",
        "ballNetworkParameters.kickModel",
        "ballNetworkParameters.numInput",
        "oldBallNetworkParameters.kickModel",
        "oldBallNetworkParameters.numInput",
    }
)
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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
        f"Simulated speed-diff audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"Simulated speed-diff audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_speed_diff_net_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("speed-diff net-slot claim must be a mapping")
    if (
        claim.get("net_slot_diff")
        or claim.get("walk_obs") not in (None, WALK_OBS)
        or claim.get("walk_act") not in (None, WALK_ACT)
        or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
        or claim.get("numInput") in {365, 59, 73, 72}
    ):
        raise ValueError("Simulated speed diffs must not include walk net-slot / dim drift")


def _skip_ws(text: str, index: int) -> int:
    n = len(text)
    while index < n:
        if text[index] in " \t\n\r":
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = n if newline < 0 else newline + 1
            continue
        break
    return index


def _parse_value(text: str, index: int) -> tuple[Any, int]:
    index = _skip_ws(text, index)
    if index < len(text) and text[index] == "{":
        return _parse_map(text, index)
    start = index
    while index < len(text) and text[index] not in ";,}":
        index += 1
    return text[start:index].strip(), index


def _parse_map(text: str, index: int) -> tuple[dict[str, Any], int]:
    index = _skip_ws(text, index)
    if index >= len(text) or text[index] != "{":
        raise ValueError("expected '{'")
    index += 1
    out: dict[str, Any] = {}
    while True:
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] == "}":
            return out, index + 1
        match = NAME_RE.match(text, index)
        if not match:
            raise ValueError(f"bad cfg token at {index}")
        name = match.group(0)
        index = _skip_ws(text, match.end())
        if index >= len(text) or text[index] != "=":
            raise ValueError(f"expected '=' after {name}")
        value, index = _parse_value(text, index + 1)
        out[name] = value
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ";":
            index += 1


def flatten_cfg(text: str) -> dict[str, str]:
    obj, _end = _parse_map("{" + text + "}", 0)

    def walk(node: Any, prefix: str) -> dict[str, str]:
        if isinstance(node, dict):
            acc: dict[str, str] = {}
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else key
                acc.update(walk(value, path))
            return acc
        return {prefix: str(node)}

    return walk(obj, "")


def _skip_source(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "pd_closed": False,
        "note": "do not invent Simulated speed diffs when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("Simulated speed-diff audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    if not default_path.is_file() or not sim_path.is_file():
        return _skip_source("Default or Simulated walkingEngine.cfg missing")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    simulated = flatten_cfg(sim_path.read_text(encoding="utf-8"))
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    slot_errors: list[str] = []
    expected_slot = {
        "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
        "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
        "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
        "ballNetworkParameters.kickModel": KICK_ONNX,
        "ballNetworkParameters.numInput": str(KICK_OBS),
    }
    for key, want in expected_slot.items():
        if default.get(key) != want or simulated.get(key) != want:
            slot_errors.append(f"{key}: Default={default.get(key)} Simulated={simulated.get(key)}")
    if slot_errors:
        raise AssertionError("net-slot / dim drift in Simulated vs Default: " + "; ".join(slot_errors))

    keys = sorted(set(default) | set(simulated))
    diffs = [
        (key, default.get(key), simulated.get(key))
        for key in keys
        if default.get(key) != simulated.get(key)
    ]
    allowed = ALLOWED_SPEED_DIFFS | ALLOWED_PLANT_DIFFS
    unexpected = [row for row in diffs if row not in allowed]
    if unexpected:
        pretty = ", ".join(f"{k} {d}→{s}" for k, d, s in unexpected)
        raise AssertionError(f"unexpected Simulated vs Default diffs (not allowlisted): {pretty}")

    speed_rows = [
        {"key": key, "default": left, "simulated": right, "kind": "speed"}
        for key, left, right in sorted(ALLOWED_SPEED_DIFFS)
        if (key, left, right) in diffs
    ]
    plant_rows = [
        {"key": key, "default": left, "simulated": right, "kind": "plant"}
        for key, left, right in sorted(ALLOWED_PLANT_DIFFS)
        if (key, left, right) in diffs
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {"default": DEFAULT_WALK_REL, "simulated": SIM_WALK_REL},
        "speed_diffs": speed_rows,
        "plant_diffs": plant_rows,
        "allowed_speed_count": len(ALLOWED_SPEED_DIFFS),
        "observed_speed_count": len(speed_rows),
        "net_slot_diff": False,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "simulated_speed_diff_closes_pd": False,
        "fabricated": False,
        "note": (
            "Simulated vs Default speed diffs are an intentional allowlist; "
            "net slot stays 344→13 / K1_walk.onnx / kick 59; "
            "these diffs do not close the PD domain gap"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "simulated_sha256": hashlib.sha256(sim_path.read_bytes()).hexdigest(),
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


def assert_speed_diff_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("Simulated speed-diff audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate speed diffs")
        return snap
    if snap.get("net_slot_diff") or snap.get("simulated_speed_diff_closes_pd"):
        raise AssertionError("net-slot drift or PD-closed claim leaked")
    if snap.get("observed_speed_count") != snap.get("allowed_speed_count"):
        raise AssertionError("allowlisted speed diffs missing from Simulated vs Default")
    try:
        refuse_speed_diff_net_slot({"net_slot_diff": True, "numInput": 365})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_speed_diff_net_slot must raise")
    try:
        refuse_simulated_speed_as_pd_closed({"simulated_speed_closes_pd": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_simulated_speed_as_pd_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("Simulated speed-diff audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    try:
        snap = assert_speed_diff_frozen(repo)
        notes.append("assert_speed_diff_frozen: allowlisted speed diffs; net slot 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: Simulated speed diffs not fabricated")
    elif snap:
        notes.append(
            f"speed diffs {snap.get('observed_speed_count')}/"
            f"{snap.get('allowed_speed_count')} allowlisted"
        )
        notes.append("net slot still 344→13 / K1_walk.onnx; kick 59")
        notes.append("Simulated speed diffs do not close PD")

    for fn, claim, label in (
        (refuse_speed_diff_net_slot, {"net_slot_diff": True, "walk_obs": 365}, "net-slot in speed diff"),
        (
            refuse_simulated_speed_as_pd_closed,
            {"source": "simulated_speed", "gap_closed": True},
            "Simulated speed as PD closed",
        ),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(default_path)
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
            errors.append("K1.yaml changed during Simulated speed-diff audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during speed-diff audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during speed-diff audit")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "pd_closed": False,
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
        print(f"[sim-speed] FAIL {exc}")
        return 1
    print(
        f"[sim-speed] {snap.get('status')} "
        f"{snap.get('observed_speed_count')} allowlisted speed diffs; "
        f"net slot 344→13; PD not closed; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
