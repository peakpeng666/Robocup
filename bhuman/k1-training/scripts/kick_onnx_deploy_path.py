"""Read-only kick ONNX deploy-path contract (inventory overlay).

Pins kick deploy path versus walk ONNX without re-auditing
kick_onnx_naming / onnx_deploy_path_crosscheck wholesale:

  * Kick file is K1_kick_inner.onnx under NeuralNets/Walk/ (same dir, not
    Walk/ default slot K1_walk.onnx)
  * Kick path is 59→13, not walk 344→13
  * Missing weights → honest SKIP (not fabricated PASS / 比赛合格)
  * Kick ONNX path must not go live without TRAINABLE gate
    (TRAINABLE stays false here)

This script never writes weights / yaml / cfg, never execs export or
train. walk↔kick GAP stays open.

Runnable: python3 bhuman/k1-training/scripts/kick_onnx_deploy_path.py
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

from kick_onnx_naming import (  # noqa: E402
    KICK_DEPLOY_RELS,
    KICK_ONNX_NAMES,
    WALK_DEFAULT_ONNX,
    WALK_DEFAULT_SLOT,
    assert_naming_frozen,
    refuse_kick_onnx_on_walk_slot,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
KICK_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-onnx-deploy-path-latest.json"
LAYOUT_DOC_REL = "bhuman/docs/CHECKPOINT-LAYOUT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

SIBLINGS = (
    "kick_onnx_naming.py",
    "onnx_deploy_path_crosscheck.py",
    "checkpoint_layout.py",
)

LAYOUT_NEEDLES = (
    "kick_onnx_deploy_path",
    "K1_kick_inner.onnx",
    "K1_walk.onnx",
    "SKIP",
)
DOC_NEEDLES = (
    "kick_onnx_deploy_path",
    "K1_kick_inner.onnx",
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
        f"kick ONNX deploy-path pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick ONNX deploy-path pin is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_weights(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick ONNX deploy-path pin must not write {path or 'K1_kick_inner.onnx'}"
    )


def refuse_kick_onnx_path_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-onnx-path-as-walk-344 claim must be a mapping")
    name = str(claim.get("name") or claim.get("onnx") or "")
    dest = str(claim.get("dest") or claim.get("path") or "").replace("\\", "/")
    kickish = (
        name in KICK_ONNX_NAMES
        or "kick_inner" in name
        or "kick_inner" in dest
        or bool(claim.get("kick_onnx"))
        or claim.get("obs") == KICK_OBS
    )
    as_walk = (
        claim.get("kick_onnx_path_as_walk_344")
        or claim.get("as_walk_344")
        or claim.get("as_walk_baseline")
        or claim.get("occupies_walk_slot")
        or dest.endswith("K1_walk.onnx")
        or name == WALK_DEFAULT_ONNX
        or claim.get("obs") == WALK_OBS
        or str(claim.get("net") or "") in {"344→13", "K1_walk.onnx"}
    )
    if claim.get("kick_onnx_path_as_walk_344") or (kickish and as_walk):
        raise ValueError(
            "kick ONNX deploy path is K1_kick_inner.onnx 59→13; "
            "must not be treated as walk 344→13 / K1_walk.onnx"
        )


def refuse_kick_onnx_live_without_trainable(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-onnx-live-without-trainable claim must be a mapping")
    if (
        claim.get("kick_onnx_live_without_trainable")
        or claim.get("apply_to_live") is True
        or claim.get("live_kick_onnx")
        or claim.get("deploy_from_missing_weight")
        or (
            claim.get("trainable") is True
            and claim.get("this_pin")
        )
        or (
            claim.get("missing_weight")
            and claim.get("status") in {"PASS", "competition_ready", "比赛合格"}
            and claim.get("as_have_weights")
        )
    ):
        raise ValueError(
            "kick ONNX deploy path stays TRAINABLE=false; "
            "missing weights are honest SKIP, not live deploy / fabricated PASS"
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


def _probe_missing(repo: Path) -> list[str]:
    missing: list[str] = []
    for rel in KICK_DEPLOY_RELS:
        path = repo / rel
        if not path.is_file() or path.stat().st_size <= 0:
            missing.append(rel)
    return missing


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("kick ONNX deploy-path leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    kick_text = kick_yaml.read_text(encoding="utf-8")
    if "num_observations: 59" not in kick_text or "num_actions: 13" not in kick_text:
        raise AssertionError("official K1_Ball.yaml drifted off 59→13")

    layout_doc = repo / LAYOUT_DOC_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    if not layout_doc.is_file() or not artifacts_doc.is_file():
        raise AssertionError("CHECKPOINT-LAYOUT / LOCAL-RUN-ARTIFACTS missing")
    layout_text = layout_doc.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    _require_needles(layout_text, LAYOUT_NEEDLES, LAYOUT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(layout_text, DOC_FORBIDDEN, LAYOUT_DOC_REL)

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (_SWITCHER / name).is_file()
        and not (repo / "bhuman/k1-training/scripts" / name).is_file()
        and not (repo / "bhuman/k1-training/k1-switcher" / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}")

    layout_assert = None
    try:
        from onnx_deploy_path_crosscheck import assert_paths_frozen

        layout_assert = assert_paths_frozen
    except ImportError:
        layout_assert = None

    steps = [
        _call_assert("kick_onnx_naming", assert_naming_frozen, repo),
        _call_assert("onnx_deploy_path_crosscheck", layout_assert, repo),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "kick ONNX deploy-path segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    missing_weights = _probe_missing(repo)
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/kick_onnx_deploy_path.py",
        "kick_names": list(KICK_ONNX_NAMES),
        "kick_deploy_rels": list(KICK_DEPLOY_RELS),
        "walk_default_slot": WALK_DEFAULT_SLOT,
        "walk_default_name": WALK_DEFAULT_ONNX,
        "missing_weights": missing_weights,
        "missing_weight_skip": bool(missing_weights),
        "missing_weight_honesty": "SKIP",
        "steps": steps,
        "will_exec_export_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "kick_onnx_path_as_walk_344": False,
        "kick_onnx_live_without_trainable": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "kick ONNX deploy path: K1_kick_inner.onnx 59→13 beside walk "
            "K1_walk.onnx 344→13 (same dir, not default slot); "
            "missing weights honest SKIP; TRAINABLE=false; GAP open"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_weights": False,
        "walk": "344→13",
        "kick": "59→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "kick_yaml_sha256": hashlib.sha256(kick_yaml.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg", ".onnx", ".pth"} or name in {
        "K1.yaml",
        "K1_Ball.yaml",
        "walkingEngine.cfg",
        "K1_walk.onnx",
        "K1_kick_inner.onnx",
    }:
        refuse_write_weights(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_kick_onnx_deploy_path_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("kick ONNX deploy-path leaked flags")
    if snap.get("will_exec_export_here") or snap.get("will_run_train_py"):
        raise AssertionError("kick ONNX deploy-path leaked export / train")
    if snap.get("walk_default_name") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk default name drifted")
    if (
        snap.get("kick_onnx_path_as_walk_344")
        or snap.get("kick_onnx_live_without_trainable")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("kick ONNX deploy-path leaked walk-344 / live / GAP-closed")
    try:
        refuse_kick_onnx_path_as_walk_344(
            {
                "kick_onnx_path_as_walk_344": True,
                "name": "K1_kick_inner.onnx",
                "obs": 344,
            }
        )
        raise AssertionError("refuse_kick_onnx_path_as_walk_344 must raise")
    except ValueError:
        pass
    try:
        refuse_kick_onnx_live_without_trainable(
            {
                "kick_onnx_live_without_trainable": True,
                "apply_to_live": True,
            }
        )
        raise AssertionError("refuse_kick_onnx_live_without_trainable must raise")
    except ValueError:
        pass
    try:
        refuse_kick_onnx_on_walk_slot(
            {
                "dest": WALK_DEFAULT_SLOT,
                "name": "K1_kick_inner.onnx",
                "family": "kick",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_onnx_on_walk_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick ONNX deploy-path imported Gym")

    yaml_path = repo / K1_YAML_REL
    kick_yaml = repo / KICK_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest() if kick_yaml.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_kick_onnx_deploy_path_frozen(repo)
        notes.append("assert_kick_onnx_deploy_path_frozen: K1_kick_inner ≠ K1_walk slot")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("same Walk/ dir; kick filename ≠ walk default; TRAINABLE=false")
        if snap.get("missing_weight_skip"):
            warnings.append("kick ONNX files absent; honest SKIP recorded")
            notes.append("missing-weight SKIP honesty: not fabricated PASS")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_kick_onnx_path_as_walk_344(
            {"name": "K1_kick_inner.onnx", "obs": 344, "as_walk_baseline": True}
        )
        errors.append("kick_onnx_path_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick ONNX path as walk 344 refused")
    try:
        refuse_kick_onnx_live_without_trainable(
            {
                "kick_onnx_live_without_trainable": True,
                "missing_weight": True,
                "status": "PASS",
                "as_have_weights": True,
            }
        )
        errors.append("kick_onnx_live_without_trainable must raise")
    except ValueError:
        notes.append("negative: kick ONNX live without TRAINABLE refused")
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
            errors.append("K1.yaml changed during kick ONNX deploy-path pin")
        else:
            notes.append("official K1.yaml untouched")
    if kick_yaml.is_file():
        after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
        if before_kick != after_kick:
            errors.append("K1_Ball.yaml changed during kick ONNX deploy-path pin")
        else:
            notes.append("official K1_Ball.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during kick ONNX deploy-path pin")
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
        "kick": "59→13",
        "kick_onnx_path_as_walk_344": False,
        "kick_onnx_live_without_trainable": False,
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
        print(f"[kick-onnx-path] FAIL {exc}")
        return 1
    skip = "missing-weight SKIP" if snap.get("missing_weight_skip") else "weights present"
    print(
        f"[kick-onnx-path] {snap.get('status')} "
        f"K1_kick_inner ≠ K1_walk; {skip}; TRAINABLE=false; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
