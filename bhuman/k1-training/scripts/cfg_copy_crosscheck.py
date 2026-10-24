"""Read-only Default / Simulated / Competition cfg copy cross-check.

Compares K1 walkingEngine.cfg (and getUpEngine.cfg when present) across
Default, SimulatedK1, CompetitionWalk, CompetitionWalk11v11, and the
k1-training/src Default copy. Walk/kick key fields must stay
344→13 / K1_walk.onnx and 59 / K1_kick_inner.onnx. SHA-only diffs in
configuredParameters are recorded as intentional. Unexpected key-field
drift → FAIL. getUp has no Simulated/Competition copies (honest absent,
not fabricated). Never writes official cfg or K1.yaml. TRAINABLE=false.
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
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from getup_engine_cfg_audit import extract_getup_row  # noqa: E402
from walking_engine_cfg_audit import extract_cfg_row  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
WALK_DEFAULT_ONNX = "K1_walk.onnx"
KICK_ONNX = "K1_kick_inner.onnx"
GETUP_ONNX = "K1.onnx"
FAST_ONNX = "K1_fast_standup.onnx"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/cfg-copy-crosscheck-latest.json"

WALK_COPIES: tuple[tuple[str, str], ...] = (
    ("Default/K1", "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"),
    ("SimulatedK1", "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"),
    (
        "CompetitionWalk/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg",
    ),
    (
        "CompetitionWalk11v11/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg",
    ),
    ("src/Default/K1", "bhuman/k1-training/src/Config/Robots/Default/K1/walkingEngine.cfg"),
)
WALK_OPTIONAL: tuple[tuple[str, str], ...] = (
    (
        "local/Default/K1",
        "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/walkingEngine.cfg",
    ),
    (
        "local/SimulatedK1",
        "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/SimulatedK1/walkingEngine.cfg",
    ),
    (
        "local/CompetitionWalk/K1",
        "bhuman/local-k1-validation-20261019/bhuman-local/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg",
    ),
    (
        "local/CompetitionWalk11v11/K1",
        "bhuman/local-k1-validation-20261019/bhuman-local/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg",
    ),
)
GETUP_COPIES: tuple[tuple[str, str], ...] = (
    ("Default/K1", "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"),
    ("src/Default/K1", "bhuman/k1-training/src/Config/Robots/Default/K1/getUpEngine.cfg"),
)
GETUP_OPTIONAL: tuple[tuple[str, str], ...] = (
    (
        "local/Default/K1",
        "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/getUpEngine.cfg",
    ),
)
GETUP_ABSENT_EXPECTED: tuple[tuple[str, str], ...] = (
    ("SimulatedK1", "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/getUpEngine.cfg"),
    (
        "CompetitionWalk/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/getUpEngine.cfg",
    ),
    (
        "CompetitionWalk11v11/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/getUpEngine.cfg",
    ),
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
        f"cfg copy cross-check is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"cfg copy cross-check is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_unexpected_cfg_copy_drift(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("cfg-copy-drift claim must be a mapping")
    walk = claim.get("walk") if isinstance(claim.get("walk"), dict) else {}
    getup = claim.get("getup") if isinstance(claim.get("getup"), dict) else {}
    if (
        claim.get("unexpected_key_drift")
        or claim.get("walk_keys_disagree")
        or claim.get("getup_keys_disagree")
    ):
        raise ValueError("K1 cfg copy key fields drifted unexpectedly")
    if walk.get("numInput") not in (None, WALK_OBS) or walk.get("numOutput") not in (
        None,
        WALK_ACT,
    ):
        raise ValueError("walk copy must stay 344→13")
    if walk.get("modelName") not in (None, WALK_DEFAULT_ONNX):
        raise ValueError("walk copy modelName must stay K1_walk.onnx")
    if getup.get("policyName") in {WALK_DEFAULT_ONNX, "T1.onnx"}:
        raise ValueError("getUp copy must not use walk or T1 names as K1")
    if getup.get("numInput") not in (None, STANDUP_OBS) and claim.get("family") == "K1":
        raise ValueError("K1 getUp copy must stay 73→22")


def _sha_row(path: Path, rel: str) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "rel": rel,
        "sha256": digest,
        "sha16": digest[:16],
        "bytes": path.stat().st_size,
    }


def _walk_keys(row: dict[str, Any]) -> dict[str, Any]:
    walk = row.get("walk") or {}
    kick = row.get("kick") or {}
    return {
        "modelName": walk.get("modelName"),
        "numInput": walk.get("numInput"),
        "numOutput": walk.get("numOutput"),
        "kickModel": kick.get("kickModel"),
        "kick_numInput": kick.get("numInput"),
    }


def _getup_keys(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "policyName": row.get("policyName"),
        "numInput": row.get("numInput"),
        "numOutput": row.get("numOutput"),
        "policyNameFast": row.get("policyNameFast"),
        "numInputFast": row.get("numInputFast"),
        "numOutputFast": row.get("numOutputFast"),
    }


def _classify_copy(
    *,
    role: str,
    sha: dict[str, Any],
    keys: dict[str, Any],
    default_sha: str,
    default_keys: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    keys_match = keys == default_keys
    sha_match = sha["sha256"] == default_sha
    if not keys_match:
        classification = "unexpected_drift"
        reason = f"{kind} key fields drifted off Default/K1"
    elif sha_match:
        classification = "identical"
        reason = f"{kind} byte-identical to Default/K1"
    else:
        classification = "intentional_diff"
        reason = (
            f"{kind} sha differs; key fields still match Default/K1 "
            "(configuredParameters / speed, not net slot)"
            if kind == "walk"
            else f"{kind} sha differs; key fields still match Default/K1"
        )
    return {
        "role": role,
        **sha,
        "keys": keys,
        "keys_match_default": keys_match,
        "sha_match_default": sha_match,
        "classification": classification,
        "reason": reason,
        "present": True,
        "fabricated": False,
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
        "note": "do not invent cfg copies when Default/K1 is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("cfg copy cross-check leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_rel = WALK_COPIES[0][1]
    default_path = repo / default_rel
    if not default_path.is_file():
        return _skip_source("Default/K1 walkingEngine.cfg not found; not fabricating copies")

    default_text = default_path.read_text(encoding="utf-8")
    default_walk_row = extract_cfg_row(default_text, default_rel)
    default_walk_keys = _walk_keys(default_walk_row)
    default_walk_sha = hashlib.sha256(default_path.read_bytes()).hexdigest()
    if (
        default_walk_keys["modelName"] != WALK_DEFAULT_ONNX
        or default_walk_keys["numInput"] != WALK_OBS
        or default_walk_keys["numOutput"] != WALK_ACT
        or default_walk_keys["kickModel"] != KICK_ONNX
        or default_walk_keys["kick_numInput"] != KICK_OBS
    ):
        raise AssertionError("Default/K1 walkingEngine.cfg drifted off 344→13 / 59 kick")

    walk_rows: list[dict[str, Any]] = []
    unexpected: list[str] = []
    for role, rel in (*WALK_COPIES, *WALK_OPTIONAL):
        path = repo / rel
        if not path.is_file():
            if (role, rel) in WALK_COPIES:
                unexpected.append(f"required walk copy missing: {rel}")
            else:
                walk_rows.append(
                    {
                        "role": role,
                        "rel": rel,
                        "present": False,
                        "expected_absent": False,
                        "classification": "optional_absent",
                        "fabricated": False,
                    }
                )
            continue
        parsed = extract_cfg_row(path.read_text(encoding="utf-8"), rel)
        row = _classify_copy(
            role=role,
            sha=_sha_row(path, rel),
            keys=_walk_keys(parsed),
            default_sha=default_walk_sha,
            default_keys=default_walk_keys,
            kind="walk",
        )
        walk_rows.append(row)
        if row["classification"] == "unexpected_drift":
            unexpected.append(f"{rel}: {row['reason']}")

    getup_default_rel = GETUP_COPIES[0][1]
    getup_default_path = repo / getup_default_rel
    getup_rows: list[dict[str, Any]] = []
    default_getup_keys: dict[str, Any] | None = None
    default_getup_sha = ""
    if getup_default_path.is_file():
        default_getup_row = extract_getup_row(
            getup_default_path.read_text(encoding="utf-8"), getup_default_rel
        )
        default_getup_keys = _getup_keys(default_getup_row)
        default_getup_sha = hashlib.sha256(getup_default_path.read_bytes()).hexdigest()
        if (
            default_getup_keys["policyName"] != GETUP_ONNX
            or default_getup_keys["numInput"] != STANDUP_OBS
            or default_getup_keys["numOutput"] != STANDUP_ACT
            or default_getup_keys["policyNameFast"] != FAST_ONNX
            or default_getup_keys["numInputFast"] != FAST_OBS
            or default_getup_keys["numOutputFast"] != FAST_ACT
        ):
            raise AssertionError("Default/K1 getUpEngine.cfg drifted off 73→22 / 72→22")

        for role, rel in (*GETUP_COPIES, *GETUP_OPTIONAL):
            path = repo / rel
            if not path.is_file():
                if (role, rel) in GETUP_COPIES:
                    unexpected.append(f"required getUp copy missing: {rel}")
                else:
                    getup_rows.append(
                        {
                            "role": role,
                            "rel": rel,
                            "present": False,
                            "expected_absent": False,
                            "classification": "optional_absent",
                            "fabricated": False,
                        }
                    )
                continue
            parsed = extract_getup_row(path.read_text(encoding="utf-8"), rel)
            row = _classify_copy(
                role=role,
                sha=_sha_row(path, rel),
                keys=_getup_keys(parsed),
                default_sha=default_getup_sha,
                default_keys=default_getup_keys,
                kind="getup",
            )
            getup_rows.append(row)
            if row["classification"] == "unexpected_drift":
                unexpected.append(f"{rel}: {row['reason']}")

    for role, rel in GETUP_ABSENT_EXPECTED:
        path = repo / rel
        if not path.is_file():
            getup_rows.append(
                {
                    "role": role,
                    "rel": rel,
                    "present": False,
                    "expected_absent": True,
                    "classification": "absent_expected",
                    "reason": "no Simulated/Competition getUpEngine.cfg; not fabricating",
                    "fabricated": False,
                }
            )
            continue
        parsed = extract_getup_row(path.read_text(encoding="utf-8"), rel)
        keys = _getup_keys(parsed)
        if default_getup_keys is None or keys != default_getup_keys:
            unexpected.append(f"{rel} appeared with key fields ≠ Default/K1 getUp")
            getup_rows.append(
                {
                    "role": role,
                    "rel": rel,
                    "present": True,
                    "expected_absent": True,
                    "classification": "unexpected_drift",
                    "keys": keys,
                    "fabricated": False,
                }
            )
        else:
            getup_rows.append(
                {
                    "role": role,
                    **_sha_row(path, rel),
                    "keys": keys,
                    "present": True,
                    "expected_absent": True,
                    "classification": "present_keys_match",
                    "reason": "copy appeared; key fields still 73→22 / 72→22",
                    "fabricated": False,
                }
            )

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    if unexpected:
        raise AssertionError("unexpected cfg copy drift: " + "; ".join(unexpected))

    intentional = [
        row
        for row in walk_rows
        if row.get("classification") == "intentional_diff"
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "walk_copies": walk_rows,
        "getup_copies": getup_rows,
        "default_walk_keys": default_walk_keys,
        "default_getup_keys": default_getup_keys,
        "default_walk_sha256": default_walk_sha,
        "default_getup_sha256": default_getup_sha or None,
        "intentional_walk_diffs": [
            {"role": row["role"], "sha16": row.get("sha16"), "reason": row.get("reason")}
            for row in intentional
        ],
        "unexpected_drift": False,
        "fabricated": False,
        "note": (
            "Default/Simulated/Competition K1 walkingEngine key fields agree "
            "(344→13 / K1_walk.onnx; kick 59 / K1_kick_inner.onnx); "
            "sha-only speed-parameter diffs are intentional; "
            "getUp only on Default (Simulated/Competition absent)"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "standup_contract": "73→22",
        "fast_contract": "72→22",
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


def assert_copies_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("cfg copy cross-check leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate cfg copies")
        return snap
    if snap.get("unexpected_drift"):
        raise AssertionError("cfg copies reported unexpected drift")
    for row in snap.get("walk_copies") or []:
        if row.get("present") and row.get("classification") == "unexpected_drift":
            raise AssertionError(f"walk copy drift: {row.get('rel')}")
        if row.get("present") and (row.get("keys") or {}).get("modelName") != WALK_DEFAULT_ONNX:
            raise AssertionError(f"{row.get('rel')} walk modelName drifted")
    for row in snap.get("getup_copies") or []:
        if row.get("classification") == "unexpected_drift":
            raise AssertionError(f"getUp copy drift: {row.get('rel')}")
        if row.get("expected_absent") and row.get("present") and not row.get("keys"):
            raise AssertionError("absent getUp row must not fabricate keys")
    try:
        refuse_unexpected_cfg_copy_drift({"unexpected_key_drift": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_unexpected_cfg_copy_drift must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("cfg copy cross-check imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_path = repo / WALK_COPIES[0][1]
    getup_path = repo / GETUP_COPIES[0][1]
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest() if walk_path.is_file() else ""
    before_getup = hashlib.sha256(getup_path.read_bytes()).hexdigest() if getup_path.is_file() else ""
    try:
        snap = assert_copies_frozen(repo)
        notes.append("assert_copies_frozen: walk keys 344→13; getUp Default-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "Default walkingEngine.cfg missing"))
        notes.append("honest SKIP: cfg copies not fabricated")
    elif snap:
        present_walk = [row for row in (snap.get("walk_copies") or []) if row.get("present")]
        notes.append(f"walk copies present: {len(present_walk)}")
        for row in present_walk:
            notes.append(
                f"{row.get('role')} sha16={row.get('sha16')} {row.get('classification')}"
            )
        for row in snap.get("getup_copies") or []:
            if row.get("expected_absent") and not row.get("present"):
                notes.append(f"{row.get('role')} getUp absent (expected; not fabricated)")
            elif row.get("present"):
                notes.append(
                    f"{row.get('role')} getUp sha16={row.get('sha16')} "
                    f"{row.get('classification')}"
                )
        notes.append("unexpected key drift: none")

    try:
        refuse_unexpected_cfg_copy_drift({"walk_keys_disagree": True})
        errors.append("refuse_unexpected_cfg_copy_drift must raise")
    except ValueError:
        notes.append("negative: unexpected key drift refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(walk_path)
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
            errors.append("K1.yaml changed during cfg copy cross-check")
        else:
            notes.append("official K1.yaml untouched")
    if walk_path.is_file():
        after_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during copy cross-check")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_path.is_file():
        after_getup = hashlib.sha256(getup_path.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during copy cross-check")
        else:
            notes.append("official getUpEngine.cfg untouched")

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
        print(f"[cfg-copy] FAIL {exc}")
        return 1
    diffs = snap.get("intentional_walk_diffs") or []
    print(
        f"[cfg-copy] {snap.get('status')} walk keys 344→13; "
        f"intentional sha diffs={len(diffs)}; getUp Default-only; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
