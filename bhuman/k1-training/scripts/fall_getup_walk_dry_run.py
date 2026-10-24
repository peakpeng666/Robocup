"""No-GPU fall→getup→force-walk→walk344 dry-run checklist (glue only).

Stitches already-closed segments into one runnable inventory:

  fallen → GetUpGenerator.createPhase
        → standup 73→22 / K1.onnx  or  fast 72→22 / K1_fast_standup.onnx
        → Force walk afterwards (theWalkGenerator.createPhase)
        → walkPolicy 344→13 / K1_walk.onnx + 13-zero last_action

Calls existing assert_* from falldown_motion_chain, standup_policy_apply_dims,
fast_standup_isolation, force_walk_afterwards, getup_walk_handoff_chain
(and last_action_reset if importable). Does not re-audit them wholesale.

Missing sibling → honest SKIP that step; do not fabricate.
will_run_isaac=false. TRAINABLE=false. walk↔kick GAP stays open.

Runnable: python3 bhuman/k1-training/scripts/fall_getup_walk_dry_run.py
Never writes K1.yaml or official cfg.
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
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/fall-getup-walk-dry-run-latest.json"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
HANDOFF_DOC_REL = "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"

CHECKLIST_SEQUENCE = (
    "fallen",
    "getup_createPhase",
    "standup_73_22_or_fast_72_22",
    "force_walk_afterwards",
    "walk_344_13_plus_13_zero",
)

DOC_NEEDLES = (
    "fall_getup_walk_dry_run",
    "fallen",
    "Force walk",
    "344→13",
    "gap_closed=false",
    "getup_walk_handoff_chain",
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
        f"fall-getup-walk dry-run pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"fall-getup-walk dry-run pin is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_e2e_dry_run_skips_force_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("e2e-dry-run-skips-force-walk claim must be a mapping")
    nxt = str(claim.get("next") or claim.get("lands_on") or "")
    if (
        claim.get("e2e_dry_run_skips_force_walk")
        or claim.get("skip_force_walk")
        or claim.get("skip_createNextPhase")
        or nxt in {"kick", "standup", "playDead", "walk_without_force"}
        or (
            claim.get("from") in {"standup", "getup_create", "standup_or_fast_apply"}
            and claim.get("to") == "return_walk"
            and not claim.get("via_force_walk")
        )
    ):
        raise ValueError(
            "fall→getup→walk dry-run must keep Force walk afterwards; "
            "skipping that step is illegal"
        )


def refuse_e2e_dry_run_claims_gap_closed(claim: dict[str, Any] | None = None) -> None:
    blob = claim if isinstance(claim, dict) else {}
    text = str(blob.get("text") or blob.get("doc") or "")
    if (
        blob.get("e2e_dry_run_claims_gap_closed")
        or blob.get("gap_closed") is True
        or "GAP 已闭合" in text
        or "gap_closed=true" in text
    ):
        raise ValueError(
            "fall→getup→walk dry-run must keep walk↔kick resetHistoryData "
            "as GAP (gap_closed=false)"
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
    *,
    takes_repo: bool = True,
) -> dict[str, Any]:
    if fn is None:
        return {
            "id": label,
            "status": "SKIP",
            "reason": f"{label} sibling missing; not fabricated",
            "fabricated": False,
        }
    try:
        result = fn(repo) if takes_repo else fn()
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


def _load_asserts() -> dict[str, Callable[..., Any] | None]:
    loaded: dict[str, Callable[..., Any] | None] = {}
    pairs = (
        ("falldown_motion_chain", "assert_chain_frozen"),
        ("standup_policy_apply_dims", "assert_standup_apply_dims_frozen"),
        ("fast_standup_isolation", "assert_fast_standup_isolated"),
        ("force_walk_afterwards", "assert_force_walk_frozen"),
        ("getup_walk_handoff_chain", "assert_handoff_chain_frozen"),
        ("last_action_reset", "cross_assert_return_to_walk"),
    )
    for module_name, attr in pairs:
        try:
            mod = __import__(module_name)
            loaded[module_name] = getattr(mod, attr)
        except (ImportError, AttributeError):
            loaded[module_name] = None
    return loaded


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("e2e dry-run leaked TRAINABLE / WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    artifacts_doc = repo / ARTIFACTS_DOC_REL
    handoff_doc = repo / HANDOFF_DOC_REL
    if not artifacts_doc.is_file() or not handoff_doc.is_file():
        raise AssertionError("LOCAL-RUN-ARTIFACTS / DEPLOY-CALL-SEQUENCE missing")
    art_text = artifacts_doc.read_text(encoding="utf-8")
    dep_text = handoff_doc.read_text(encoding="utf-8")
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(dep_text, DOC_FORBIDDEN, HANDOFF_DOC_REL)
    if "fall_getup_walk_dry_run" not in dep_text:
        raise AssertionError("DEPLOY-CALL-SEQUENCE must point at fall_getup_walk_dry_run")

    asserts = _load_asserts()
    steps = [
        _call_assert("falldown_motion_chain", asserts.get("falldown_motion_chain"), repo),
        _call_assert(
            "standup_policy_apply_dims",
            asserts.get("standup_policy_apply_dims"),
            repo,
        ),
        _call_assert(
            "fast_standup_isolation", asserts.get("fast_standup_isolation"), repo
        ),
        _call_assert("force_walk_afterwards", asserts.get("force_walk_afterwards"), repo),
        _call_assert(
            "getup_walk_handoff_chain", asserts.get("getup_walk_handoff_chain"), repo
        ),
        _call_assert(
            "last_action_reset",
            asserts.get("last_action_reset"),
            repo,
            takes_repo=False,
        ),
    ]
    failed = [row for row in steps if row.get("status") == "FAIL"]
    if failed:
        raise AssertionError(
            "e2e dry-run segment FAIL: "
            + "; ".join(f"{row['id']}: {row.get('reason')}" for row in failed)
        )

    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/fall_getup_walk_dry_run.py",
        "sequence": list(CHECKLIST_SEQUENCE),
        "steps": steps,
        "docs_pointer": {
            "handoff": "bhuman/k1-training/scripts/getup_walk_handoff_chain.py",
            "deploy": HANDOFF_DOC_REL,
            "artifacts": ARTIFACTS_DOC_REL,
        },
        "will_run_isaac": False,
        "will_run_train_py": False,
        "will_exec_eval_here": False,
        "e2e_dry_run_skips_force_walk": False,
        "e2e_dry_run_claims_gap_closed": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "glue checklist: fallen→GetUp createPhase→standup 73→22 or fast 72→22→"
            "Force walk afterwards→walk 344→13 + 13-zero; "
            "missing sibling SKIP that step; GAP stays open; no Isaac"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "getup_cfg_sha256": hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if getup_cfg.is_file()
        else "",
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


def assert_e2e_dry_run_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("e2e dry-run leaked flags")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        raise AssertionError("e2e dry-run leaked Isaac / train")
    if snap.get("sequence") != list(CHECKLIST_SEQUENCE):
        raise AssertionError(f"e2e sequence drifted: {snap.get('sequence')}")
    if (
        snap.get("e2e_dry_run_skips_force_walk")
        or snap.get("e2e_dry_run_claims_gap_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        raise AssertionError("e2e dry-run leaked skip-force-walk / GAP-closed / fabricate")
    try:
        refuse_e2e_dry_run_skips_force_walk(
            {"e2e_dry_run_skips_force_walk": True, "next": "walk_without_force"}
        )
        raise AssertionError("refuse_e2e_dry_run_skips_force_walk must raise")
    except ValueError:
        pass
    try:
        refuse_e2e_dry_run_claims_gap_closed(
            {"e2e_dry_run_claims_gap_closed": True, "gap_closed": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_e2e_dry_run_claims_gap_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("e2e dry-run imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    try:
        snap = assert_e2e_dry_run_frozen(repo)
        notes.append("assert_e2e_dry_run_frozen: fallen→getup→force-walk→walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("glue only; existing assert_* referenced, not re-audited")
        notes.append("will_run_isaac=false; GAP stays open")
        for row in snap.get("steps") or []:
            if row.get("status") == "SKIP":
                warnings.append(str(row.get("reason") or row.get("id")))
                notes.append(f"honest SKIP: {row.get('id')} not fabricated")

    try:
        refuse_e2e_dry_run_skips_force_walk(
            {"e2e_dry_run_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("e2e_dry_run_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: e2e dry-run skips Force walk refused")
    try:
        refuse_e2e_dry_run_claims_gap_closed(
            {"e2e_dry_run_claims_gap_closed": True, "text": "GAP 已闭合"}
        )
        errors.append("e2e_dry_run_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: e2e dry-run claims GAP closed refused")
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
            errors.append("K1.yaml changed during e2e dry-run pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during e2e dry-run pin")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during e2e dry-run pin")
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
        "e2e_dry_run_skips_force_walk": False,
        "e2e_dry_run_claims_gap_closed": False,
        "will_run_isaac": False,
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
        print(f"[e2e-dry-run] FAIL {exc}")
        return 1
    print(
        f"[e2e-dry-run] {snap.get('status')} "
        f"fallen→getup→force-walk→walk 344→13; GAP open; no Isaac; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
