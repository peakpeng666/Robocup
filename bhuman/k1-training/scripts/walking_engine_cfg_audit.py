"""Read-only walkingEngine.cfg audit (no Gym).

Parses official K1 walkingEngine.cfg walk/kick blocks into a manifest.
Walk default stays 344→13 / K1_walk.onnx. Kick models must not overwrite
that walk slot. T1 model names must not appear on the K1 walk slot.
Standup is not in this cfg (sibling getUpEngine.cfg only).
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

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
WALK_DEFAULT_ONNX = "K1_walk.onnx"
KICK_ONNX_NAMES = frozenset(
    {"K1_kick_inner.onnx", "K1_kick_inner_soft.onnx", "K1_kick_90degree.onnx"}
)
T1_MODEL_NAMES = frozenset(
    {
        "T1_walk.onnx",
        "T1_kick_inner.onnx",
        "T1_kick_inner_soft.onnx",
        "model.pth",
    }
)
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walking-engine-cfg-audit-latest.json"
K1_WALK_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg",
    "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/walkingEngine.cfg",
)
T1_WALK_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/T1/walkingEngine.cfg",
)
GETUP_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg",
    "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/getUpEngine.cfg",
)
ASSIGN_RE = re.compile(
    r"^\s*(modelName|kickModel|policyName|policyNameFast|"
    r"numInput|numOutput|numInputFast|numOutputFast)\s*=\s*(\S+);"
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def locate_first(repo: Path, rels: tuple[str, ...]) -> tuple[Path | None, str | None]:
    for rel in rels:
        path = repo / rel
        if path.is_file() and path.stat().st_size > 0:
            return path, rel
    return None, None


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walkingEngine.cfg audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walkingEngine.cfg audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_cfg_dim_rewrite(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("cfg-dim claim must be a mapping")
    if claim.get("cfg_dim_changed") or claim.get("rewrite_cfg_dims"):
        raise ValueError("official walkingEngine.cfg dims are frozen; must not rewrite")
    if claim.get("slot") == "walk" and claim.get("numInput") not in (None, WALK_OBS):
        raise ValueError("K1 walk numInput must stay 344")
    if claim.get("slot") == "walk" and claim.get("numOutput") not in (None, WALK_ACT):
        raise ValueError("K1 walk numOutput must stay 13")
    if claim.get("walk_obs") not in (None, WALK_OBS) or claim.get("walk_act") not in (
        None,
        WALK_ACT,
    ):
        raise ValueError("cfg walk default must stay 344→13")
    if claim.get("walk") in {"365→14", "59→13", "73→22"}:
        raise ValueError("cfg walk default must stay 344→13")
    if claim.get("numInput") == 365 and claim.get("family") in (None, "K1", "walk"):
        raise ValueError("T1 365 must not be declared as K1 walk numInput")


def refuse_kickmodel_points_t1(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kickModel-T1 claim must be a mapping")
    name = str(claim.get("kickModel") or claim.get("name") or "")
    if (
        claim.get("kickmodel_t1")
        or name.startswith("T1_")
        or name in T1_MODEL_NAMES
        or (claim.get("family") == "T1" and claim.get("slot") == "kick")
    ):
        raise ValueError("K1 kickModel must not point at a T1 ONNX")


def refuse_t1_model_on_k1_walk_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("T1-on-walk-slot claim must be a mapping")
    name = str(claim.get("modelName") or claim.get("name") or "")
    if (
        claim.get("t1_on_k1_walk")
        or name in T1_MODEL_NAMES
        or (claim.get("family") == "T1" and claim.get("slot") == "walk")
    ):
        raise ValueError("T1 model name must not occupy the K1 walk slot")


def _named_block(text: str, name: str) -> str | None:
    token = f"{name} ="
    start = text.find(token)
    if start < 0:
        return None
    open_at = text.find("{", start)
    if open_at < 0:
        return None
    depth = 0
    for index, char in enumerate(text[open_at:], open_at):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : index]
    return None


def _parse_assignments(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = ASSIGN_RE.match(line)
        if match:
            out[match.group(1)] = match.group(2).rstrip(";")
    return out


def parse_walk_cfg(text: str) -> dict[str, dict[str, str]]:
    return {
        "walk": _parse_assignments(_named_block(text, "walkNeuronalNetworkParameters") or ""),
        "kick": _parse_assignments(_named_block(text, "ballNetworkParameters") or ""),
        "kick_soft": _parse_assignments(_named_block(text, "oldBallNetworkParameters") or ""),
    }


def extract_cfg_row(text: str, rel: str) -> dict[str, Any]:
    blocks = parse_walk_cfg(text)
    walk = blocks["walk"]
    kick = blocks["kick"]
    soft = blocks["kick_soft"]
    if walk.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError(f"{rel} modelName={walk.get('modelName')} ≠ {WALK_DEFAULT_ONNX}")
    if walk.get("numInput") != str(WALK_OBS) or walk.get("numOutput") != str(WALK_ACT):
        raise AssertionError(f"{rel} walk net drifted off 344→13")
    if walk.get("modelName") in KICK_ONNX_NAMES:
        raise AssertionError(f"{rel} kick ONNX occupies walk modelName")
    if walk.get("modelName") in T1_MODEL_NAMES:
        raise AssertionError(f"{rel} T1 model occupies K1 walk slot")
    kick_name = kick.get("kickModel")
    if kick_name == WALK_DEFAULT_ONNX:
        raise AssertionError(f"{rel} kickModel overwrites walk default {WALK_DEFAULT_ONNX}")
    if kick_name in T1_MODEL_NAMES:
        raise AssertionError(f"{rel} kickModel points at T1")
    if kick.get("numInput") != str(KICK_OBS):
        raise AssertionError(f"{rel} kick numInput drifted off 59")
    if "standup" in blocks["walk"] or "policyName" in walk:
        raise AssertionError(f"{rel} must not host standup policyName in walk block")
    return {
        "rel": rel,
        "walk": {
            "modelName": walk.get("modelName"),
            "numInput": int(walk["numInput"]),
            "numOutput": int(walk["numOutput"]),
            "contract": "344→13",
        },
        "kick": {
            "kickModel": kick_name,
            "numInput": int(kick["numInput"]),
            "numOutput_in_cfg": None,
            "implied_act": KICK_ACT,
            "contract": "59→13",
        },
        "kick_soft": {
            "kickModel": soft.get("kickModel"),
            "numInput": int(soft["numInput"]) if soft.get("numInput") else None,
            "numOutput_in_cfg": None,
            "implied_act": KICK_ACT,
        },
        "standup_in_walking_engine_cfg": False,
        "kick_overwrites_walk": False,
        "t1_in_k1_walk_slot": False,
    }


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
        "note": "do not invent walkingEngine.cfg fields when the file is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walkingEngine.cfg audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    primary, primary_rel = locate_first(repo, K1_WALK_CFG_RELS)
    if primary is None:
        return _skip_source("walkingEngine.cfg not found; not fabricating walk/kick dims")

    rows: list[dict[str, Any]] = []
    for rel in K1_WALK_CFG_RELS:
        path = repo / rel
        if not path.is_file():
            continue
        rows.append(extract_cfg_row(path.read_text(encoding="utf-8"), rel))

    head = next(row for row in rows if row["rel"] == primary_rel)
    for row in rows:
        if row["walk"] != head["walk"] or row["kick"]["kickModel"] != head["kick"]["kickModel"]:
            raise AssertionError(f"{row['rel']} disagrees with official K1 walkingEngine.cfg")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    t1_path, t1_rel = locate_first(repo, T1_WALK_CFG_RELS)
    t1: dict[str, Any] | None = None
    if t1_path is not None:
        t1_blocks = parse_walk_cfg(t1_path.read_text(encoding="utf-8"))
        t1_name = t1_blocks["walk"].get("modelName")
        if t1_name == WALK_DEFAULT_ONNX:
            raise AssertionError("T1 walkingEngine.cfg must not use K1_walk.onnx")
        t1 = {
            "rel": t1_rel,
            "modelName": t1_name,
            "numInput": int(t1_blocks["walk"]["numInput"]) if t1_blocks["walk"].get("numInput") else None,
            "numOutput": int(t1_blocks["walk"]["numOutput"]) if t1_blocks["walk"].get("numOutput") else None,
            "is_k1_walk_slot": False,
        }

    getup_path, getup_rel = locate_first(repo, GETUP_CFG_RELS)
    standup: dict[str, Any] = {
        "in_walking_engine_cfg": False,
        "note": "standup lives in getUpEngine.cfg, not walkingEngine.cfg",
    }
    if getup_path is not None:
        gfields = _parse_assignments(getup_path.read_text(encoding="utf-8"))
        standup.update(
            {
                "sibling_rel": getup_rel,
                "policyName": gfields.get("policyName"),
                "numInput": int(gfields["numInput"]) if gfields.get("numInput") else None,
                "numOutput": int(gfields["numOutput"]) if gfields.get("numOutput") else None,
                "contract": "73→22",
            }
        )
        if standup.get("numInput") != STANDUP_OBS or standup.get("numOutput") != STANDUP_ACT:
            raise AssertionError("getUpEngine.cfg standup drifted off 73→22")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {"walking_engine_cfg": primary_rel, "getup_engine_cfg": getup_rel},
        "cfgs": rows,
        "walk": head["walk"],
        "kick": head["kick"],
        "kick_soft": head["kick_soft"],
        "standup": standup,
        "t1": t1,
        "kick_overwrites_walk": False,
        "t1_in_k1_walk_slot": False,
        "fabricated": False,
        "note": (
            "official K1 walkingEngine.cfg: walk 344→13 / K1_walk.onnx; "
            "kick 59 / K1_kick_inner.onnx (not walk default); standup not in this cfg"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "kick_contract": "59→13",
        "cfg_sha256": hashlib.sha256(primary.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {"K1.yaml", "walkingEngine.cfg"}:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_cfg_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walkingEngine.cfg audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate cfg fields")
        return snap
    walk = snap.get("walk") or {}
    if walk.get("contract") != "344→13" or walk.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk default drifted off 344→13 / K1_walk.onnx")
    if snap.get("kick_overwrites_walk") or snap.get("t1_in_k1_walk_slot"):
        raise AssertionError("kick/T1 leaked onto K1 walk slot")
    if (snap.get("standup") or {}).get("in_walking_engine_cfg"):
        raise AssertionError("standup must not appear inside walkingEngine.cfg")
    try:
        refuse_cfg_dim_rewrite({"cfg_dim_changed": True, "numInput": 365, "slot": "walk"})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_cfg_dim_rewrite must raise")
    try:
        refuse_kickmodel_points_t1({"kickModel": "T1_kick_inner.onnx"})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_kickmodel_points_t1 must raise")
    try:
        refuse_t1_model_on_k1_walk_slot({"modelName": "T1_walk.onnx"})
    except ValueError:
        return snap
    raise AssertionError("refuse_t1_model_on_k1_walk_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walkingEngine.cfg audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path, _cfg_rel = locate_first(repo, K1_WALK_CFG_RELS)
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path is not None else ""
    try:
        snap = assert_cfg_frozen(repo)
        notes.append("assert_cfg_frozen: walk 344→13 / K1_walk.onnx; kick ≠ walk slot")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: walkingEngine.cfg not fabricated")
    elif snap:
        notes.append(
            f"walk {snap.get('walk_contract')} modelName={(snap.get('walk') or {}).get('modelName')}"
        )
        notes.append(
            f"kick {(snap.get('kick') or {}).get('kickModel')} numInput="
            f"{(snap.get('kick') or {}).get('numInput')}"
        )
        notes.append("standup not in walkingEngine.cfg (sibling getUpEngine.cfg)")

    for fn, claim, label in (
        (refuse_cfg_dim_rewrite, {"cfg_dim_changed": True}, "cfg dim rewrite"),
        (refuse_cfg_dim_rewrite, {"walk": "365→14"}, "walk declared 365"),
        (refuse_kickmodel_points_t1, {"kickModel": "T1_kick_inner.onnx"}, "kickModel T1"),
        (refuse_t1_model_on_k1_walk_slot, {"modelName": "T1_walk.onnx"}, "T1 on K1 walk slot"),
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
        refuse_write_cfg(cfg_path or "walkingEngine.cfg")
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
            errors.append("K1.yaml changed during walkingEngine.cfg audit")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path is not None:
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during audit")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "kick": "59→13",
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
        print(f"[walk-cfg] FAIL {exc}")
        return 1
    print(
        f"[walk-cfg] {snap.get('status')} walk 344→13 / K1_walk.onnx; "
        f"kick={(snap.get('kick') or {}).get('kickModel')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
