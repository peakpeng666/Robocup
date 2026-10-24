"""Standup vs fast-standup vs walk isolation matrix (read-only checklist).

One inventory table; does not re-audit apply-site / replay wholesale:

  walk     344→13  K1_walk.onnx           Isaac K1           run_replay K1
  standup  73→22   K1.onnx / K1_stand_up  Isaac K1_Stand_Up  run_replay K1_Stand_Up
  fast     72→22   K1_fast_standup.onnx   NOT Isaac          NOT in run_replay

Live cfg is scanned for cross-wiring (73 as 72, 72 as 344, fast as
K1_Stand_Up). None is allowed. Missing ONNX is honest, not fabricated.

walk↔kick GAP is a different contract and stays open.
standup→walk 13-zero is already closed elsewhere.

Never writes yaml / cfg. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from bounded_fast_standup_replay import (  # noqa: E402
    assert_fast_standup_replay_frozen,
)
from fast_standup_isolation import assert_fast_standup_isolated  # noqa: E402
from standup_policy_apply_dims import assert_standup_apply_dims_frozen  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
STANDUP_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
ABSENT_FAST_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_fast_standup.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
REPLAY_SH_REL = "bhuman/k1-training/scripts/run_replay.sh"
SNAPSHOT_REL = "bhuman/k1-training/manifests/standup-fast-isolation-matrix-latest.json"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

MATRIX = (
    {
        "id": "walk",
        "obs": 344,
        "act": 13,
        "onnx": "K1_walk.onnx",
        "isaac": "K1",
        "replay": "K1",
    },
    {
        "id": "standup",
        "obs": 73,
        "act": 22,
        "onnx": "K1.onnx",
        "isaac": "K1_Stand_Up",
        "replay": "K1_Stand_Up",
    },
    {
        "id": "fast",
        "obs": 72,
        "act": 22,
        "onnx": "K1_fast_standup.onnx",
        "isaac": None,
        "replay": None,
    },
)

GETUP_NEEDLES = (
    "numInput = 73",
    "numOutput = 22",
    "policyName = K1.onnx",
    "numInputFast = 72",
    "numOutputFast = 22",
    "policyNameFast = K1_fast_standup.onnx",
)
WALK_CFG_NEEDLES = (
    "modelName = K1_walk.onnx",
    "numInput = 344",
    "numOutput = 13",
)
DOC_NEEDLES = (
    "standup_fast_isolation_matrix",
    "73→22",
    "72→22",
    "344→13",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
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
        f"isolation matrix pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"isolation matrix pin is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_isolation_matrix_cross_wires_slots(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("isolation-matrix-cross-wire claim must be a mapping")
    source = str(claim.get("from") or claim.get("source") or claim.get("id") or "")
    dest = str(claim.get("to") or claim.get("as") or claim.get("slot") or "")
    crossed = {
        ("standup", "fast"),
        ("fast", "standup"),
        ("standup", "walk"),
        ("fast", "walk"),
        ("walk", "standup"),
        ("walk", "fast"),
        ("73→22", "72→22"),
        ("72→22", "73→22"),
        ("72→22", "344→13"),
        ("73→22", "344→13"),
    }
    if (
        claim.get("isolation_matrix_cross_wires_slots")
        or claim.get("same_net")
        or claim.get("fast_is_73")
        or claim.get("fast_is_walk_344")
        or claim.get("standup_is_fast")
        or (source, dest) in crossed
        or (
            claim.get("obs") == FAST_OBS
            and claim.get("isaac") == "K1_Stand_Up"
        )
        or (
            claim.get("obs") == STANDUP_OBS
            and claim.get("onnx") == "K1_fast_standup.onnx"
        )
        or (
            claim.get("obs") in {STANDUP_OBS, FAST_OBS}
            and claim.get("obs_as_walk") == WALK_OBS
        )
    ):
        raise ValueError(
            "isolation matrix keeps walk 344→13 / standup 73→22 / fast 72→22 "
            "as three slots; live cross-wiring is illegal"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _call_assert(
    label: str,
    fn: Callable[..., dict[str, Any]] | None,
    repo: Path,
) -> dict[str, Any]:
    if fn is None:
        return {
            "id": label,
            "status": "SKIP",
            "reason": f"{label} sibling missing; not fabricated",
            "fabricated": False,
        }
    try:
        result = fn(repo)
    except FileNotFoundError as exc:
        return {
            "id": label,
            "status": "SKIP",
            "reason": str(exc),
            "fabricated": False,
        }
    except (AssertionError, ValueError) as exc:
        return {"id": label, "status": "FAIL", "reason": str(exc), "fabricated": False}
    status = str((result or {}).get("status") or "PASS")
    if status == "SKIP":
        return {
            "id": label,
            "status": "SKIP",
            "reason": str((result or {}).get("reason") or f"{label} SKIP"),
            "fabricated": False,
        }
    return {"id": label, "status": "PASS", "reason": None, "fabricated": False}


def _live_cross_wires(getup_text: str, walk_text: str, replay_text: str) -> list[str]:
    leaks: list[str] = []
    if "numInputFast = 73" in getup_text or "numInput = 72" in getup_text:
        leaks.append("getUpEngine.cfg swapped 73/72 inputs")
    if "policyNameFast = K1.onnx" in getup_text:
        leaks.append("fast slot points at regular K1.onnx")
    if "policyName = K1_fast_standup.onnx" in getup_text:
        leaks.append("regular standup points at K1_fast_standup.onnx")
    if "policyName = K1_walk.onnx" in getup_text or "policyNameFast = K1_walk.onnx" in getup_text:
        leaks.append("getUpEngine.cfg occupied walk ONNX")
    if "modelName = K1.onnx" in walk_text or "modelName = K1_fast_standup.onnx" in walk_text:
        leaks.append("walkingEngine.cfg walk slot occupied by standup/fast")
    if "K1_fast_standup)" in replay_text:
        leaks.append("run_replay.sh grew a K1_fast_standup case")
    return leaks


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("isolation matrix leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    standup_yaml = repo / STANDUP_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    standup_text = standup_yaml.read_text(encoding="utf-8")
    if (
        "num_observations: 73" not in standup_text
        or "num_actions: 22" not in standup_text
    ):
        raise AssertionError("official K1_Stand_Up.yaml drifted off 73→22")
    if (repo / ABSENT_FAST_YAML_REL).is_file():
        raise AssertionError("K1_fast_standup.yaml must not exist")

    getup = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    replay = repo / REPLAY_SH_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    for path, label in (
        (getup, GETUP_CFG_REL),
        (walk_cfg, WALK_CFG_REL),
        (replay, REPLAY_SH_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (compat_doc, COMPAT_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")

    getup_text = getup.read_text(encoding="utf-8")
    walk_text = walk_cfg.read_text(encoding="utf-8")
    replay_text = replay.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(getup_text, GETUP_NEEDLES, GETUP_CFG_REL)
    _require_needles(walk_text, WALK_CFG_NEEDLES, WALK_CFG_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    if "gap_closed=false" not in compat_text:
        raise AssertionError("LOCAL-BH-GYM-COMPAT must keep gap_closed=false")

    leaks = _live_cross_wires(getup_text, walk_text, replay_text)
    if leaks:
        raise AssertionError("live cross-wiring appeared: " + "; ".join(leaks))

    steps = [
        _call_assert(
            "standup_policy_apply_dims", assert_standup_apply_dims_frozen, repo
        ),
        _call_assert("fast_standup_isolation", assert_fast_standup_isolated, repo),
        _call_assert(
            "bounded_fast_standup_replay",
            assert_fast_standup_replay_frozen,
            repo,
        ),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "isolation matrix segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/standup_fast_isolation_matrix.py",
        "matrix": [dict(row) for row in MATRIX],
        "live_cross_wiring": [],
        "steps": steps,
        "will_run_isaac": False,
        "will_run_train_py": False,
        "isolation_matrix_cross_wires_slots": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "matrix: walk 344→13 / standup 73→22 / fast 72→22 deploy-only; "
            "no live cross-wiring; fast not Isaac; GAP open"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest(),
        "getup_cfg_sha256": hashlib.sha256(getup.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "standup_yaml_sha256": hashlib.sha256(standup_yaml.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Stand_Up.yaml",
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


def assert_isolation_matrix_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("isolation matrix leaked flags")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        raise AssertionError("isolation matrix leaked Isaac / train")
    matrix = snap.get("matrix") or []
    if [row.get("id") for row in matrix] != [row["id"] for row in MATRIX]:
        raise AssertionError(f"isolation matrix drifted: {matrix}")
    if snap.get("live_cross_wiring"):
        raise AssertionError(f"live cross-wiring: {snap.get('live_cross_wiring')}")
    if (
        snap.get("isolation_matrix_cross_wires_slots")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("isolation matrix leaked cross-wire / GAP-closed")
    try:
        refuse_isolation_matrix_cross_wires_slots(
            {
                "isolation_matrix_cross_wires_slots": True,
                "from": "fast",
                "to": "walk",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_isolation_matrix_cross_wires_slots must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("isolation matrix imported Gym")

    yaml_path = repo / K1_YAML_REL
    standup_yaml = repo / STANDUP_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_standup = (
        hashlib.sha256(standup_yaml.read_bytes()).hexdigest() if standup_yaml.is_file() else ""
    )
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_isolation_matrix_frozen(repo)
        notes.append("assert_isolation_matrix_frozen: 344→13 / 73→22 / 72→22 isolated")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("live cfg scan: no 73↔72 / fast↔walk cross-wiring")
        notes.append("fast stays deploy-only; not Isaac; not run_replay.sh")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_isolation_matrix_cross_wires_slots(
            {"from": "standup", "to": "fast", "standup_is_fast": True}
        )
        errors.append("isolation_matrix_cross_wires_slots must raise")
    except ValueError:
        notes.append("negative: isolation matrix cross-wire refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(getup_cfg)
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
            errors.append("K1.yaml changed during isolation matrix pin")
        else:
            notes.append("official K1.yaml untouched")
    if standup_yaml.is_file():
        after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
        if before_standup != after_standup:
            errors.append("K1_Stand_Up.yaml changed during isolation matrix pin")
        else:
            notes.append("official K1_Stand_Up.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during isolation matrix pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during isolation matrix pin")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "isolation_matrix_cross_wires_slots": False,
        "live_cross_wiring": [],
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
        print(f"[isolation-matrix] FAIL {exc}")
        return 1
    print(
        f"[isolation-matrix] {snap.get('status')} "
        f"walk 344→13 / standup 73→22 / fast 72→22; no live cross-wire; "
        f"wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
