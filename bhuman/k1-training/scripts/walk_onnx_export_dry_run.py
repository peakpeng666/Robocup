"""Walk ONNX export dry-run alignment (inventory overlay).

Pins existing onnx_export_contract against kick / fast deploy paths:

  * Default exportable path stays official walk 344→13 (--task K1)
  * Export commands stay stub / dry-run under TRAINABLE=false
    (IMPLEMENTED=false; would_export=false even with checkpoint + approval)
  * Kick 59→13 and fast 72→22 are not the default walk export
  * Export inventory PASS ≠ competition deploy / 比赛合格

Never writes weights / yaml / cfg. Never execs a real exporter.
walk↔kick GAP stays open.

Runnable: python3 bhuman/k1-training/scripts/walk_onnx_export_dry_run.py
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

from kick_onnx_deploy_path import assert_kick_onnx_deploy_path_frozen  # noqa: E402
from onnx_export_contract import (  # noqa: E402
    DEFAULT_EXPORT,
    IMPLEMENTED,
    WALK_ONNX_REL,
    WALK_PTH_REL,
    WRITE_WEIGHTS,
    assert_onnx_export_frozen,
    export_readiness,
    refuse_foreign_as_default_export,
    refuse_hot_swap_into_official_actor,
    refuse_write_official_onnx,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_ONNX = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
FAST_OBS = 72
FAST_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-onnx-export-dry-run-latest.json"
LAYOUT_DOC_REL = "bhuman/docs/CHECKPOINT-LAYOUT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
HANDOFF_DOC_REL = "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"

CHECKLIST = (
    "onnx_export_contract_stub",
    "default_export_walk_344",
    "kick_not_default_export",
    "fast_not_default_export",
    "would_export_false",
    "trainable_false",
)

LAYOUT_NEEDLES = (
    "walk_onnx_export_dry_run",
    "K1_walk.onnx",
    "SKIP",
    "TRAINABLE=false",
)
DOC_NEEDLES = (
    "walk_onnx_export_dry_run",
    "competition deploy",
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
        f"walk ONNX export dry-run is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk ONNX export dry-run is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_export_pass_as_competition_deploy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("export-pass-as-competition-deploy claim must be a mapping")
    status = str(claim.get("status") or "")
    if (
        claim.get("export_pass_as_competition_deploy")
        or claim.get("competition_ready") is True
        or claim.get("比赛合格")
        or status in {"competition_ready", "比赛合格"}
        or (
            claim.get("as_competition_deploy")
            and status in {"PASS", "PASS_FOR_DECLARED_PROFILE", "SKIP"}
        )
    ):
        raise ValueError(
            "walk ONNX export dry-run PASS / SKIP is not competition deploy / 比赛合格"
        )


def refuse_export_as_live_without_trainable(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("export-as-live-without-trainable claim must be a mapping")
    if (
        claim.get("export_as_live_without_trainable")
        or claim.get("apply_to_live") is True
        or claim.get("would_export") is True
        or claim.get("write_onnx") is True
        or (
            claim.get("trainable") is True
            and claim.get("this_pin")
        )
    ):
        raise ValueError(
            "walk ONNX export stays TRAINABLE=false / IMPLEMENTED=false; "
            "dry-run must not write live ONNX"
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
    fn: Callable[..., Any] | None,
    repo: Path | None,
    *,
    pass_repo: bool,
) -> dict[str, Any]:
    if fn is None:
        return {
            "id": label,
            "status": "SKIP",
            "reason": f"{label} sibling missing; not fabricated",
            "fabricated": False,
        }
    try:
        result = fn(repo) if pass_repo else fn()
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
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ONNX or IMPLEMENTED or WRITE_WEIGHTS:
        raise AssertionError("walk ONNX export dry-run leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    layout_doc = repo / LAYOUT_DOC_REL
    artifacts_doc = repo / ARTIFACTS_DOC_REL
    handoff_doc = repo / HANDOFF_DOC_REL
    for path, label in (
        (layout_doc, LAYOUT_DOC_REL),
        (artifacts_doc, ARTIFACTS_DOC_REL),
        (handoff_doc, HANDOFF_DOC_REL),
    ):
        if not path.is_file():
            raise AssertionError(f"{label} missing")
    layout_text = layout_doc.read_text(encoding="utf-8")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    dep_text = handoff_doc.read_text(encoding="utf-8")
    _require_needles(layout_text, LAYOUT_NEEDLES, LAYOUT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(dep_text, ("walk_onnx_export_dry_run", "onnx_export_contract"), HANDOFF_DOC_REL)
    _forbid_tokens(layout_text, DOC_FORBIDDEN, LAYOUT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(dep_text, DOC_FORBIDDEN, HANDOFF_DOC_REL)

    ready = export_readiness(repo, user_approved=False)
    approved = export_readiness(repo, user_approved=True)
    if ready.get("would_export") or approved.get("would_export"):
        raise AssertionError("export_readiness leaked would_export=true")
    if ready.get("status") != "SKIP" or approved.get("status") != "SKIP":
        raise AssertionError("export_readiness must stay honest SKIP")

    steps = [
        _call_assert("onnx_export_contract", assert_onnx_export_frozen, repo, pass_repo=False),
        _call_assert(
            "kick_onnx_deploy_path",
            assert_kick_onnx_deploy_path_frozen,
            repo,
            pass_repo=True,
        ),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "walk ONNX export dry-run segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/walk_onnx_export_dry_run.py",
        "checklist": list(CHECKLIST),
        "default_export": dict(DEFAULT_EXPORT),
        "not_default": {
            "kick": f"{KICK_OBS}→{KICK_ACT}",
            "fast": f"{FAST_OBS}→{FAST_ACT}",
        },
        "export_readiness": {
            "status": ready.get("status"),
            "would_export": False,
            "approved_still_skip": True,
            "reason": ready.get("reason"),
        },
        "steps": steps,
        "will_exec_export_here": False,
        "will_run_train_py": False,
        "will_run_isaac_gym": False,
        "export_pass_as_competition_deploy": False,
        "export_as_live_without_trainable": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "walk ONNX export dry-run: default 344→13 stub; kick/fast not default "
            "export; would_export=false; TRAINABLE=false; PASS ≠ competition deploy"
        ),
        "trainable": False,
        "implemented": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_onnx": False,
        "walk": "344→13",
        "kick": "59→13",
        "fast": "72→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "walk_pth_rel": WALK_PTH_REL,
        "walk_onnx_rel": WALK_ONNX_REL,
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg", ".onnx", ".pth"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "K1_walk.onnx",
    }:
        refuse_write_official_onnx(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_walk_onnx_export_dry_run_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_ONNX or IMPLEMENTED:
        raise AssertionError("walk ONNX export dry-run leaked flags")
    if snap.get("will_exec_export_here") or snap.get("will_run_train_py"):
        raise AssertionError("walk ONNX export dry-run leaked export / train")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"export checklist drifted: {snap.get('checklist')}")
    if (
        snap.get("export_pass_as_competition_deploy")
        or snap.get("export_as_live_without_trainable")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("export dry-run leaked live / competition-deploy / GAP-closed")
    try:
        refuse_export_pass_as_competition_deploy(
            {
                "export_pass_as_competition_deploy": True,
                "status": "PASS",
                "as_competition_deploy": True,
            }
        )
        raise AssertionError("refuse_export_pass_as_competition_deploy must raise")
    except ValueError:
        pass
    try:
        refuse_export_as_live_without_trainable(
            {"export_as_live_without_trainable": True, "would_export": True}
        )
        raise AssertionError("refuse_export_as_live_without_trainable must raise")
    except ValueError:
        pass
    try:
        refuse_foreign_as_default_export("kick", KICK_OBS, KICK_ACT)
        raise AssertionError("refuse_foreign_as_default_export kick must raise")
    except ValueError:
        pass
    try:
        refuse_foreign_as_default_export("fast_standup", FAST_OBS, FAST_ACT)
        raise AssertionError("refuse_foreign_as_default_export fast must raise")
    except ValueError:
        pass
    try:
        refuse_hot_swap_into_official_actor({"hot_swap_into_official_actor": True})
        raise AssertionError("refuse_hot_swap_into_official_actor must raise")
    except ValueError:
        pass
    try:
        refuse_write_official_onnx(WALK_ONNX_REL)
    except RuntimeError:
        return snap
    raise AssertionError("refuse_write_official_onnx must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk ONNX export dry-run imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_walk_onnx_export_dry_run_frozen(repo)
        notes.append("assert_walk_onnx_export_dry_run_frozen: walk 344 stub; kick/fast not default")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("would_export=false; IMPLEMENTED=false; TRAINABLE=false")
        notes.append("export inventory PASS ≠ competition deploy")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_export_pass_as_competition_deploy(
            {
                "export_pass_as_competition_deploy": True,
                "status": "SKIP",
                "as_competition_deploy": True,
            }
        )
        errors.append("export_pass_as_competition_deploy must raise")
    except ValueError:
        notes.append("negative: export PASS/SKIP as competition deploy refused")
    try:
        refuse_export_as_live_without_trainable(
            {"export_as_live_without_trainable": True, "apply_to_live": True}
        )
        errors.append("export_as_live_without_trainable must raise")
    except ValueError:
        notes.append("negative: export live without TRAINABLE refused")
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
            errors.append("K1.yaml changed during walk ONNX export dry-run pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during walk ONNX export dry-run pin")
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
        "export_pass_as_competition_deploy": False,
        "export_as_live_without_trainable": False,
        "will_exec_export_here": False,
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
        print(f"[export-dry-run] FAIL {exc}")
        return 1
    print(
        f"[export-dry-run] {snap.get('status')} "
        f"walk 344 stub; kick/fast not default; would_export=false; "
        f"PASS ≠ competition deploy; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
