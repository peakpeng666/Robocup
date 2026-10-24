"""Read-only getUpEngine.cfg audit (no Gym).

Parses official K1 getUpEngine.cfg: standup 73→22 / K1.onnx and
deploy-only fast 72→22 / K1_fast_standup.onnx (same file fields).
Must not overwrite the walk 344→13 / K1_walk.onnx slot.
T1 getUp (76→23 / T1.onnx) must not impersonate K1.
Fast 72→22 is deploy-only: not an Isaac registered task;
SimRobot must not impersonate it (GetUpEngine forces fastActive off
in simulatedRobot). Never writes getUpEngine.cfg, walkingEngine.cfg,
or K1.yaml. TRAINABLE=false.
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

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
if str(_SWITCHER) not in sys.path:
    sys.path.insert(0, str(_SWITCHER))

from kick_standup_joint_map import refuse_fast_standup_as_walk  # noqa: E402
from standup_kick_contract import refuse_simrobot_as_fast_standup  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
T1_STANDUP_OBS = 76
T1_STANDUP_ACT = 23
T1_FAST_OBS = 75
T1_FAST_ACT = 23
WALK_DEFAULT_ONNX = "K1_walk.onnx"
GETUP_ONNX = "K1.onnx"
FAST_ONNX = "K1_fast_standup.onnx"
T1_GETUP_ONNX = "T1.onnx"
T1_FAST_ONNX = "T1_fast_standup.onnx"
T1_GETUP_NAMES = frozenset({T1_GETUP_ONNX, T1_FAST_ONNX, "T1_Stand_Up"})
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/getup-engine-cfg-audit-latest.json"
K1_GETUP_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg",
    "bhuman/k1-training/src/Config/Robots/Default/K1/getUpEngine.cfg",
    "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/getUpEngine.cfg",
)
T1_GETUP_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/T1/getUpEngine.cfg",
)
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CPP_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp"
)
ENV_INIT_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py",
    "bhuman/MachineLearning/IsaacGymRL/envs/__init__.py",
)
ASSIGN_RE = re.compile(
    r"^\s*(policyName|policyNameFast|numInput|numOutput|"
    r"numInputFast|numOutputFast|fastActive|useWaist)\s*=\s*(\S+);"
)
IMPORT_RE = re.compile(r"^from envs\.([A-Za-z0-9_]+) import ([A-Za-z0-9_]+)\s*$")


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
        f"getUpEngine.cfg audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"getUpEngine.cfg audit is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_getup_overwrites_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("getup-overwrites-walk claim must be a mapping")
    name = str(claim.get("policyName") or claim.get("name") or "")
    dest = str(claim.get("dest") or "")
    if (
        claim.get("getup_overwrites_walk")
        or name == WALK_DEFAULT_ONNX
        or dest.endswith(WALK_DEFAULT_ONNX)
        or (claim.get("slot") == "getup" and claim.get("numInput") == WALK_OBS)
        or (claim.get("family") == "getup" and claim.get("walk_slot"))
    ):
        raise ValueError(
            "getUpEngine.cfg must not overwrite walk 344→13 / K1_walk.onnx"
        )


def refuse_t1_getup_as_k1(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("T1-getup-as-K1 claim must be a mapping")
    name = str(
        claim.get("policyName")
        or claim.get("policyNameFast")
        or claim.get("name")
        or ""
    )
    if (
        claim.get("t1_getup_as_k1")
        or name in T1_GETUP_NAMES
        or name.startswith("T1")
        or (claim.get("family") == "T1" and claim.get("as_k1") is not False)
        or (claim.get("numInput") == T1_STANDUP_OBS and claim.get("slot") == "k1_getup")
    ):
        raise ValueError("T1 getUp must not impersonate K1 getUp 73→22 / K1.onnx")


def refuse_fast_standup_as_isaac(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("fast-as-Isaac claim must be a mapping")
    name = str(claim.get("task") or claim.get("name") or claim.get("policyNameFast") or "")
    if (
        claim.get("fast_as_isaac")
        or claim.get("register_isaac")
        or claim.get("registered_in_isaac")
        or claim.get("is_isaac_task") is True
        or claim.get("registered") is True
        or (
            name in {"K1_fast_standup", FAST_ONNX}
            and claim.get("registered") is not False
            and claim.get("deploy_only") is not True
        )
    ):
        raise ValueError(
            "K1_fast_standup 72→22 is deploy-only; not an Isaac registered task"
        )
    if claim.get("simrobot_pass") and claim.get("impersonates") in {
        "fast_standup",
        "72→22",
        FAST_ONNX,
    }:
        raise ValueError("SimRobot PASS must not impersonate fast standup 72→22")


def parse_getup_fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = ASSIGN_RE.match(line)
        if match:
            out[match.group(1)] = match.group(2).rstrip(";")
    return out


def _as_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    token = raw.strip().lower()
    if token == "true":
        return True
    if token == "false":
        return False
    return None


def extract_getup_row(text: str, rel: str, *, family: str = "K1") -> dict[str, Any]:
    fields = parse_getup_fields(text)
    policy = fields.get("policyName")
    fast_name = fields.get("policyNameFast")
    num_in = int(fields["numInput"]) if fields.get("numInput") else None
    num_out = int(fields["numOutput"]) if fields.get("numOutput") else None
    fast_in = int(fields["numInputFast"]) if fields.get("numInputFast") else None
    fast_out = int(fields["numOutputFast"]) if fields.get("numOutputFast") else None
    fast_active = _as_bool(fields.get("fastActive"))
    use_waist = _as_bool(fields.get("useWaist"))
    if family == "K1":
        if policy != GETUP_ONNX:
            raise AssertionError(f"{rel} policyName={policy} ≠ {GETUP_ONNX}")
        if num_in != STANDUP_OBS or num_out != STANDUP_ACT:
            raise AssertionError(f"{rel} standup drifted off 73→22")
        if policy == WALK_DEFAULT_ONNX:
            raise AssertionError(f"{rel} getUp policyName overwrites walk slot")
        if policy in T1_GETUP_NAMES or fast_name in T1_GETUP_NAMES:
            raise AssertionError(f"{rel} T1 getUp occupies K1 getUp slot")
        if fast_name != FAST_ONNX:
            raise AssertionError(f"{rel} policyNameFast={fast_name} ≠ {FAST_ONNX}")
        if fast_in != FAST_OBS or fast_out != FAST_ACT:
            raise AssertionError(f"{rel} fast standup drifted off 72→22")
        if "policyName" in fields and fields.get("modelName") == WALK_DEFAULT_ONNX:
            raise AssertionError(f"{rel} must not host walk modelName")
    return {
        "rel": rel,
        "family": family,
        "policyName": policy,
        "numInput": num_in,
        "numOutput": num_out,
        "contract": "73→22" if family == "K1" else "76→23",
        "policyNameFast": fast_name,
        "numInputFast": fast_in,
        "numOutputFast": fast_out,
        "fast_contract": "72→22" if family == "K1" else "75→23",
        "fastActive": fast_active,
        "useWaist": use_waist,
        "overwrites_walk": False,
        "is_k1_getup": family == "K1",
        "isaac_registered_fast": False,
        "deploy_only_fast": True,
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
        "standup": "73→22",
        "fast_standup": "72→22",
        "note": "do not invent getUpEngine.cfg fields when the file is missing",
    }


def _registered_tasks(repo: Path) -> set[str]:
    names: set[str] = set()
    for rel in ENV_INIT_RELS:
        path = repo / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = IMPORT_RE.match(line.strip())
            if match:
                names.add(match.group(2))
    return names


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("getUpEngine.cfg audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    primary, primary_rel = locate_first(repo, K1_GETUP_CFG_RELS)
    if primary is None:
        return _skip_source("getUpEngine.cfg not found; not fabricating standup dims")

    rows: list[dict[str, Any]] = []
    for rel in K1_GETUP_CFG_RELS:
        path = repo / rel
        if not path.is_file():
            continue
        rows.append(extract_getup_row(path.read_text(encoding="utf-8"), rel))

    head = next(row for row in rows if row["rel"] == primary_rel)
    for row in rows:
        if (
            row["policyName"] != head["policyName"]
            or row["numInput"] != head["numInput"]
            or row["numOutput"] != head["numOutput"]
            or row["policyNameFast"] != head["policyNameFast"]
            or row["numInputFast"] != head["numInputFast"]
            or row["numOutputFast"] != head["numOutputFast"]
        ):
            raise AssertionError(f"{row['rel']} disagrees with official K1 getUpEngine.cfg")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    walk_cfg = repo / WALK_CFG_REL
    if walk_cfg.is_file():
        walk_text = walk_cfg.read_text(encoding="utf-8")
        if "modelName = K1_walk.onnx" not in walk_text:
            raise AssertionError("walk default slot drifted off K1_walk.onnx")
        if "policyName =" in walk_text.split("walkNeuronalNetworkParameters", 1)[-1][:400]:
            raise AssertionError("walkingEngine.cfg must not host getUp policyName")

    registered = _registered_tasks(repo)
    if "K1_fast_standup" in registered:
        raise AssertionError("K1_fast_standup must not be an Isaac registered task")

    t1_path, t1_rel = locate_first(repo, T1_GETUP_CFG_RELS)
    t1: dict[str, Any] | None = None
    if t1_path is not None:
        t1 = extract_getup_row(
            t1_path.read_text(encoding="utf-8"), t1_rel or "", family="T1"
        )
        if t1["policyName"] in {GETUP_ONNX, WALK_DEFAULT_ONNX}:
            raise AssertionError("T1 getUpEngine.cfg must not use K1.onnx / K1_walk.onnx")
        if t1["numInput"] == STANDUP_OBS and t1["numOutput"] == STANDUP_ACT:
            raise AssertionError("T1 getUp must not impersonate K1 73→22")
        if t1["policyName"] != T1_GETUP_ONNX:
            raise AssertionError(f"T1 getUp policyName={t1['policyName']} ≠ {T1_GETUP_ONNX}")
        if t1["numInput"] != T1_STANDUP_OBS or t1["numOutput"] != T1_STANDUP_ACT:
            raise AssertionError("T1 getUp drifted off 76→23")
        t1["is_k1_getup"] = False

    cpp = repo / GETUP_CPP_REL
    simrobot_forces_off = False
    if cpp.is_file():
        cpp_text = cpp.read_text(encoding="utf-8")
        simrobot_forces_off = (
            "simulatedRobot" in cpp_text and "fastActive = false" in cpp_text
        )

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {"getup_engine_cfg": primary_rel, "getup_engine_cpp": GETUP_CPP_REL},
        "cfgs": rows,
        "standup": {
            "policyName": head["policyName"],
            "numInput": head["numInput"],
            "numOutput": head["numOutput"],
            "contract": "73→22",
        },
        "fast": {
            "policyNameFast": head["policyNameFast"],
            "numInputFast": head["numInputFast"],
            "numOutputFast": head["numOutputFast"],
            "contract": "72→22",
            "fastActive": head["fastActive"],
            "deploy_only": True,
            "isaac_registered": False,
            "simrobot_impersonates": False,
            "simrobot_forces_fastActive_off": simrobot_forces_off,
        },
        "t1": t1,
        "overwrites_walk": False,
        "t1_as_k1": False,
        "fabricated": False,
        "note": (
            "official K1 getUpEngine.cfg: standup 73→22 / K1.onnx; "
            "fast 72→22 / K1_fast_standup.onnx deploy-only (same file); "
            "must not overwrite walk 344→13; T1 getUp is not K1; "
            "SimRobot forces fastActive off"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "standup_contract": "73→22",
        "fast_contract": "72→22",
        "cfg_sha256": hashlib.sha256(primary.read_bytes()).hexdigest(),
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
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_getup_cfg_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("getUpEngine.cfg audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate getUp fields")
        return snap
    standup = snap.get("standup") or {}
    fast = snap.get("fast") or {}
    if standup.get("contract") != "73→22" or standup.get("policyName") != GETUP_ONNX:
        raise AssertionError("standup drifted off 73→22 / K1.onnx")
    if fast.get("contract") != "72→22" or fast.get("policyNameFast") != FAST_ONNX:
        raise AssertionError("fast standup drifted off 72→22 / K1_fast_standup.onnx")
    if snap.get("overwrites_walk") or standup.get("policyName") == WALK_DEFAULT_ONNX:
        raise AssertionError("getUp must not overwrite walk 344→13 slot")
    if snap.get("t1_as_k1") or (snap.get("t1") or {}).get("is_k1_getup"):
        raise AssertionError("T1 getUp must not count as K1")
    if fast.get("isaac_registered") or not fast.get("deploy_only"):
        raise AssertionError("fast standup must stay deploy-only / unregistered")
    try:
        refuse_getup_overwrites_walk({"getup_overwrites_walk": True, "policyName": WALK_DEFAULT_ONNX})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_getup_overwrites_walk must raise")
    try:
        refuse_t1_getup_as_k1({"policyName": T1_GETUP_ONNX})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_t1_getup_as_k1 must raise")
    try:
        refuse_fast_standup_as_isaac({"task": "K1_fast_standup", "registered": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_fast_standup_as_isaac must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("getUpEngine.cfg audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path, _cfg_rel = locate_first(repo, K1_GETUP_CFG_RELS)
    walk_path = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path is not None else ""
    before_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest() if walk_path.is_file() else ""
    try:
        snap = assert_getup_cfg_frozen(repo)
        notes.append("assert_getup_cfg_frozen: 73→22 / K1.onnx; fast 72→22 deploy-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "getUpEngine.cfg missing"))
        notes.append("honest SKIP: getUpEngine.cfg not fabricated")
    elif snap:
        notes.append(
            f"standup {snap.get('standup_contract')} "
            f"policyName={(snap.get('standup') or {}).get('policyName')}"
        )
        notes.append(
            f"fast {snap.get('fast_contract')} "
            f"policyNameFast={(snap.get('fast') or {}).get('policyNameFast')} deploy-only"
        )
        notes.append("getUp does not overwrite walk 344→13 / K1_walk.onnx")
        if (snap.get("fast") or {}).get("simrobot_forces_fastActive_off"):
            notes.append("GetUpEngine.cpp simulatedRobot forces fastActive off")

    for fn, claim, label in (
        (refuse_getup_overwrites_walk, {"getup_overwrites_walk": True}, "getUp overwrites walk"),
        (refuse_t1_getup_as_k1, {"policyName": T1_GETUP_ONNX}, "T1 getUp as K1"),
        (refuse_fast_standup_as_isaac, {"task": "K1_fast_standup", "registered": True}, "fast as Isaac"),
        (
            refuse_simrobot_as_fast_standup,
            {"simrobot_pass": True, "impersonates": "fast_standup"},
            "SimRobot as fast",
        ),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_fast_standup_as_walk()
        errors.append("refuse_fast_standup_as_walk must raise")
    except ValueError:
        notes.append("negative: fast standup as walk refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(cfg_path or "getUpEngine.cfg")
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of getUpEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during getUpEngine.cfg audit")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path is not None:
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during audit")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if walk_path.is_file():
        after_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during getUp audit")
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
        "standup": "73→22",
        "fast_standup": "72→22",
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
        print(f"[getup-cfg] FAIL {exc}")
        return 1
    print(
        f"[getup-cfg] {snap.get('status')} standup 73→22 / K1.onnx; "
        f"fast 72→22 deploy-only; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
