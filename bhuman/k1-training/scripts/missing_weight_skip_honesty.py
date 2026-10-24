"""Shared missing-weight SKIP honesty (inventory overlay).

Pins walk / kick / standup / fast replay+eval contracts to one helper:

  * Missing weights → honest SKIP (not fabricated PASS / 比赛合格)
  * Inventory may PASS without weights (existence_required_here=false)
  * Missing weights must not fail-closed
  * Shared record_missing_weight_honesty + two refuses

Never writes weights / yaml / cfg. Never execs replay / eval / train.
walk↔kick GAP stays open. Does not import walk_onnx_export_dry_run
or merge_readiness_blockers.

Runnable: python3 bhuman/k1-training/scripts/missing_weight_skip_honesty.py
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

from bounded_fast_standup_replay import assert_fast_standup_replay_frozen  # noqa: E402
from bounded_kick_replay import assert_kick_replay_frozen  # noqa: E402
from bounded_standup_replay import assert_standup_replay_frozen  # noqa: E402
from bounded_walk_replay import assert_replay_bounds_frozen  # noqa: E402
from kick_eval_metrics import assert_kick_eval_frozen  # noqa: E402
from kick_onnx_naming import KICK_DEPLOY_RELS, KICK_TRAIN_PTH  # noqa: E402
from onnx_export_contract import WALK_ONNX_REL, WALK_PTH_REL  # noqa: E402
from standup_eval_metrics import assert_standup_eval_frozen  # noqa: E402
from walk_eval_metrics import assert_walk_eval_frozen  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
STANDUP_PT_REL = "bhuman/k1-training/src/IsaacGymRL/pre-trained/GetUp/K1_stand_up.pt"
STANDUP_ONNX_REL = "bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx"
FAST_ONNX_REL = "bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1_fast_standup.onnx"
SNAPSHOT_REL = "bhuman/k1-training/manifests/missing-weight-skip-honesty-latest.json"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"

PATH_SPECS: tuple[tuple[str, tuple[str, ...], Callable[..., Any]], ...] = (
    ("walk_replay", (WALK_PTH_REL, WALK_ONNX_REL), assert_replay_bounds_frozen),
    ("walk_eval", (WALK_PTH_REL, WALK_ONNX_REL), assert_walk_eval_frozen),
    ("kick_replay", KICK_DEPLOY_RELS + (KICK_TRAIN_PTH,), assert_kick_replay_frozen),
    ("kick_eval", KICK_DEPLOY_RELS + (KICK_TRAIN_PTH,), assert_kick_eval_frozen),
    (
        "standup_replay",
        (STANDUP_PT_REL, STANDUP_ONNX_REL),
        assert_standup_replay_frozen,
    ),
    (
        "standup_eval",
        (STANDUP_PT_REL, STANDUP_ONNX_REL),
        assert_standup_eval_frozen,
    ),
    ("fast_replay", (FAST_ONNX_REL,), assert_fast_standup_replay_frozen),
)

DOC_NEEDLES = (
    "missing_weight_skip_honesty",
    "missing-weight SKIP",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "GAP 已闭合",
    "gap_closed=true",
    "competition_ready=true",
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
        f"missing-weight SKIP honesty is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"missing-weight SKIP honesty is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_weights(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"missing-weight SKIP honesty must not write {path or 'weights'}"
    )


def refuse_missing_weight_as_fabricated_pass(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("missing-weight-as-fabricated-pass claim must be a mapping")
    missing = bool(
        claim.get("missing_weight")
        or claim.get("missing_weights")
        or claim.get("missing")
    )
    as_have = bool(
        claim.get("as_have_weights") or claim.get("missing_weight_as_fabricated_pass")
    )
    status = str(claim.get("status") or "")
    if claim.get("missing_weight_as_fabricated_pass") or (
        (missing or as_have)
        and as_have
        and (
            status in {"PASS", "PASS_FOR_DECLARED_PROFILE", "比赛合格", "competition_ready"}
            or claim.get("比赛合格")
            or claim.get("competition_ready") is True
        )
    ):
        raise ValueError(
            "missing weights must stay honest SKIP; "
            "inventory PASS is not fabricated have-weights / 比赛合格"
        )


def refuse_missing_weight_fails_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("missing-weight-fails-closed claim must be a mapping")
    if (
        claim.get("missing_weight_fails_closed")
        or (
            claim.get("fail_closed")
            and (
                claim.get("missing_weight")
                or claim.get("missing")
                or claim.get("because_missing")
            )
        )
        or (
            (claim.get("missing_weight") or claim.get("missing"))
            and str(claim.get("status") or "") == "FAIL"
            and claim.get("because_missing")
        )
    ):
        raise ValueError(
            "missing weights must not fail-closed; "
            "inventory stays PASS with honest SKIP"
        )


def record_missing_weight_honesty(
    path_id: str,
    weight_rels: tuple[str, ...],
    repo: Path,
    *,
    inventory_status: str = "PASS",
    as_have_weights: bool = False,
    fail_closed: bool = False,
) -> dict[str, Any]:
    missing = [
        rel
        for rel in weight_rels
        if not (repo / rel).is_file() or (repo / rel).stat().st_size <= 0
    ]
    row = {
        "id": path_id,
        "weight_rels": list(weight_rels),
        "missing_weights": missing,
        "missing": bool(missing),
        "honesty": "SKIP" if missing else "present",
        "inventory_status": inventory_status,
        "fabricated": False,
        "fail_closed": False,
        "as_have_weights": False,
    }
    if as_have_weights and inventory_status in {
        "PASS",
        "PASS_FOR_DECLARED_PROFILE",
        "比赛合格",
        "competition_ready",
    }:
        refuse_missing_weight_as_fabricated_pass(
            {
                "missing_weight_as_fabricated_pass": True,
                "missing_weight": bool(missing),
                "as_have_weights": True,
                "status": inventory_status,
            }
        )
    if fail_closed and missing:
        refuse_missing_weight_fails_closed(
            {
                "missing_weight_fails_closed": True,
                "fail_closed": True,
                "missing_weight": True,
                "because_missing": True,
                "status": "FAIL",
            }
        )
    return row


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
    fn: Callable[..., Any] | None,
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
    if isinstance(result, dict):
        status = str(result.get("status") or "PASS")
        if status == "SKIP":
            return {
                "id": label,
                "status": "SKIP",
                "reason": str(result.get("reason") or f"{label} SKIP"),
                "fabricated": False,
            }
    return {"id": label, "status": "PASS", "reason": None, "fabricated": False}


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("missing-weight SKIP honesty leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    artifacts_doc = repo / ARTIFACTS_DOC_REL
    compat_doc = repo / COMPAT_DOC_REL
    if not artifacts_doc.is_file() or not compat_doc.is_file():
        raise AssertionError("LOCAL-RUN-ARTIFACTS / LOCAL-BH-GYM-COMPAT missing")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    compat_text = compat_doc.read_text(encoding="utf-8")
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    if "gap_closed=false" not in compat_text:
        raise AssertionError(f"{COMPAT_DOC_REL} missing gap_closed=false")
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)

    paths = [
        record_missing_weight_honesty(path_id, weights, repo)
        for path_id, weights, _fn in PATH_SPECS
    ]
    steps = [
        _call_assert(path_id, fn, repo) for path_id, _weights, fn in PATH_SPECS
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "missing-weight sibling contract FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    any_missing = any(row.get("missing") for row in paths)
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/missing_weight_skip_honesty.py",
        "paths": paths,
        "steps": steps,
        "missing_weight_skip": any_missing,
        "missing_weight_honesty": "SKIP" if any_missing else "present",
        "will_exec_replay_here": False,
        "will_run_eval_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "missing_weight_as_fabricated_pass": False,
        "missing_weight_fails_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "missing-weight SKIP honesty across walk/kick/standup/fast "
            "replay+eval; inventory PASS without weights is OK; "
            "not fabricated PASS / not fail-closed; TRAINABLE=false"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_weights": False,
        "walk": "344→13",
        "kick": "59→13",
        "standup": "73→22",
        "fast": "72→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg", ".onnx", ".pth", ".pt"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "K1_walk.onnx",
        "K1_kick_inner.onnx",
        "K1.onnx",
        "K1_fast_standup.onnx",
    }:
        refuse_write_weights(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_missing_weight_skip_honesty_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("missing-weight SKIP honesty leaked flags")
    if snap.get("will_exec_replay_here") or snap.get("will_run_train_py"):
        raise AssertionError("missing-weight honesty leaked replay / train")
    ids = [row.get("id") for row in (snap.get("paths") or [])]
    expected = [path_id for path_id, _w, _fn in PATH_SPECS]
    if ids != expected:
        raise AssertionError(f"honesty path table drifted: {ids}")
    if (
        snap.get("missing_weight_as_fabricated_pass")
        or snap.get("missing_weight_fails_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("missing-weight honesty leaked fabricated PASS / fail-closed / GAP-closed")
    try:
        refuse_missing_weight_as_fabricated_pass(
            {
                "missing_weight_as_fabricated_pass": True,
                "missing_weight": True,
                "as_have_weights": True,
                "status": "PASS",
            }
        )
        raise AssertionError("refuse_missing_weight_as_fabricated_pass must raise")
    except ValueError:
        pass
    try:
        refuse_missing_weight_fails_closed(
            {
                "missing_weight_fails_closed": True,
                "fail_closed": True,
                "missing_weight": True,
                "because_missing": True,
                "status": "FAIL",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_missing_weight_fails_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("missing-weight SKIP honesty imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_missing_weight_skip_honesty_frozen(repo)
        notes.append("assert_missing_weight_skip_honesty_frozen: 7-path SKIP honesty")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("inventory PASS without weights is OK; not fabricated / not fail-closed")
        if snap.get("missing_weight_skip"):
            warnings.append("one or more weight files absent; honest SKIP recorded")
            notes.append("missing-weight SKIP honesty: not fabricated PASS")
        for row in snap.get("paths") or []:
            if row.get("missing"):
                notes.append(f"honest SKIP: {row.get('id')} missing {row.get('missing_weights')}")

    try:
        refuse_missing_weight_as_fabricated_pass(
            {
                "missing_weight": True,
                "as_have_weights": True,
                "status": "PASS",
                "比赛合格": True,
            }
        )
        errors.append("missing_weight_as_fabricated_pass must raise")
    except ValueError:
        notes.append("negative: missing-weight as fabricated PASS refused")
    try:
        refuse_missing_weight_fails_closed(
            {
                "missing_weight_fails_closed": True,
                "fail_closed": True,
                "because_missing": True,
            }
        )
        errors.append("missing_weight_fails_closed must raise")
    except ValueError:
        notes.append("negative: missing-weight fail-closed refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(walk_cfg)
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
            errors.append("K1.yaml changed during missing-weight SKIP honesty pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during missing-weight SKIP honesty pin")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "missing_weight_as_fabricated_pass": False,
        "missing_weight_fails_closed": False,
        "missing_weight_skip": bool(snap.get("missing_weight_skip")),
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
        print(f"[missing-weight] FAIL {exc}")
        return 1
    skip = "missing-weight SKIP" if snap.get("missing_weight_skip") else "weights present"
    print(
        f"[missing-weight] {snap.get('status')} "
        f"7-path honesty; {skip}; not fabricated / not fail-closed; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
