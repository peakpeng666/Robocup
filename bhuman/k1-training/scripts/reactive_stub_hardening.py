"""Harden reactive / estimator / draft stubs: TRAINABLE=false, not default walk.

Inventory only. Does not re-audit hardening.py / estimator_ab_audit /
probe_reserved_gpu wholesale — those siblings stay the source of the
bypass / A-B / GPU-checklist facts.

Facts this pin must keep:

  * K1_Reactive 64→15 is a parallel stub (TRAINABLE=false, implemented=false).
  * Default skill stays official walk 344→13 (K1_walk.onnx).
  * Estimator latent is a side-channel and must not enter 344.
  * Draft-only files must not write live rewards / K1.yaml.
  * ready_gpu is true only from cuda + isaac + disk + official K1 + checkpoint.
    Stub presence must never flip ready_gpu true.
  * If reactive is labeled the default walk baseline → FAIL.
  * If a stub sets ready_gpu true → FAIL.

Never writes K1.yaml or official cfg. Never calls train.py / Isaac.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
_ESTIMATORS = _SCRIPTS.parent / "k1-estimators"
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE, _ESTIMATORS, _DRAFT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from bt_skill_select import DEFAULT_SKILL, IMPLEMENTED, SkillSelectContext, select_skill  # noqa: E402
from contract import NUM_ACTIONS, NUM_OBSERVATIONS, TASK_NAME, TRAINABLE as REACTIVE_TRAINABLE  # noqa: E402
from env_stub import ISAAC_GYM_TASK_REGISTERED, create_training_env  # noqa: E402
from interface import TRAINABLE as EST_TRAINABLE  # noqa: E402
from probe_reserved_gpu import (  # noqa: E402
    CHECKLIST_KEYS,
    WILL_RUN_ISAAC_GYM,
    WILL_RUN_TRAIN_PY,
    build_checklist,
    probe,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
REACTIVE_OBS = 64
REACTIVE_ACT = 15
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/reactive-stub-hardening-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
OFFICIAL_ENVS_INIT = "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py"
OFFICIAL_REACTIVE_YAML = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Reactive.yaml"

SIBLINGS = (
    "hardening.py",
    "estimator_ab_audit.py",
    "probe_reserved_gpu.py",
    "bt_skill_select.py",
    "env_registry_audit.py",
    "env_stub.py",
)

STUB_INVENTORY = (
    {
        "id": "k1_reactive_contract",
        "rel": "bhuman/k1-training/k1-reactive/contract.py",
        "needles": ("TRAINABLE = False", 'TASK_NAME = "K1_Reactive"', 'STATUS = "STUB_NOT_TRAINABLE"'),
        "trainable": False,
        "default_walk": False,
        "contract": "64→15",
    },
    {
        "id": "k1_reactive_env_stub",
        "rel": "bhuman/k1-training/k1-reactive/env_stub.py",
        "needles": ("ISAAC_GYM_TASK_REGISTERED = False", "create_training_env", "TRAINABLE"),
        "trainable": False,
        "registered": False,
    },
    {
        "id": "k1_reactive_hardening",
        "rel": "bhuman/k1-training/k1-reactive/hardening.py",
        "needles": ("def assert_reactive_bypass", "walk remains the default"),
        "trainable": False,
        "see": "assert_reactive_bypass (sibling, not re-audited)",
    },
    {
        "id": "bt_skill_select",
        "rel": "bhuman/k1-training/k1-reactive/bt_skill_select.py",
        "needles": ("IMPLEMENTED = False", 'DEFAULT_SKILL = "walk"', "want_kick: bool = False"),
        "trainable": False,
        "default_skill": "walk",
        "implemented": False,
    },
    {
        "id": "k1_estimators_interface",
        "rel": "bhuman/k1-training/k1-estimators/interface.py",
        "needles": ("TRAINABLE = False", "WALK_OBS = 344"),
        "trainable": False,
        "latent_into_344": False,
    },
    {
        "id": "k1_estimators_hooks",
        "rel": "bhuman/k1-training/k1-estimators/hooks.py",
        "needles": ("if TRAINABLE:", "latent must not enter official 344"),
        "trainable": False,
    },
    {
        "id": "estimator_ab_audit",
        "rel": "bhuman/k1-training/scripts/estimator_ab_audit.py",
        "needles": ("TRAINABLE = False", "not registered in train.py"),
        "trainable": False,
        "see": "estimator_ab_audit (sibling, not re-audited)",
    },
    {
        "id": "draft_validator",
        "rel": "bhuman/k1-training/configs/draft-only/draft_validator.py",
        "needles": ("draft_only", "refuse_overwrite_live_rewards", "still_proportion"),
        "trainable": False,
        "writes_live": False,
    },
    {
        "id": "probe_reserved_gpu",
        "rel": "bhuman/k1-training/scripts/probe_reserved_gpu.py",
        "needles": (
            "WILL_RUN_TRAIN_PY = False",
            'CHECKLIST_KEYS = ("cuda", "isaacgym_or_alt", "disk", "official_k1_task", "checkpoint")',
        ),
        "trainable": False,
        "ready_from_stub": False,
        "see": "probe_reserved_gpu (sibling, not re-audited)",
    },
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
        f"reactive stub hardening is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"reactive stub hardening is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_reactive_as_default_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("reactive-as-default-walk claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("skill") or "")
    if (
        claim.get("reactive_as_default_walk")
        or claim.get("reactive_is_default_baseline")
        or claim.get("default_skill") == "reactive"
        or claim.get("default_baseline") == "K1_Reactive"
        or (
            source
            in {
                "reactive",
                "K1_Reactive",
                "k1-reactive",
                "64→15",
                "bt_skill_select",
            }
            and (
                claim.get("default") is True
                or claim.get("is_default_walk")
                or claim.get("occupies_walk_slot")
                or claim.get("contract") == "344→13"
                or claim.get("walk_obs") == WALK_OBS
                or claim.get("skill") == "walk"
            )
        )
    ):
        raise ValueError(
            "K1_Reactive 64→15 is a parallel stub (TRAINABLE=false); "
            "default walk baseline stays official 344→13 / K1_walk.onnx"
        )


def refuse_stub_sets_ready_gpu_true(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("stub-sets-ready-gpu-true claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("stub") or "")
    if (
        claim.get("stub_sets_ready_gpu_true")
        or claim.get("ready_gpu_from_stub")
        or claim.get("ready_because_stub")
        or (
            source
            in {
                "stub",
                "reactive",
                "K1_Reactive",
                "estimator",
                "k1-estimators",
                "draft",
                "draft-only",
                "hardening",
            }
            and (
                claim.get("ready_gpu") is True
                or claim.get("ready") is True
                or claim.get("flips_ready_gpu")
            )
        )
    ):
        raise ValueError(
            "ready_gpu is true only from cuda+isaac+disk+official K1+checkpoint; "
            "a TRAINABLE=false stub must never flip ready_gpu true"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


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
        "reactive": "64→15",
        "reactive_as_default_walk": False,
        "stub_sets_ready_gpu_true": False,
        "ready_gpu": False,
        "note": "do not invent stub inventory when source is missing",
    }


def _load_hardening(repo: Path):
    rel = "bhuman/k1-training/k1-reactive/hardening.py"
    spec = importlib.util.spec_from_file_location("reactive_hardening_ref", repo / rel)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("reactive stub hardening leaked TRAINABLE/WRITE flags")
    if REACTIVE_TRAINABLE or EST_TRAINABLE:
        raise AssertionError("reactive / estimator TRAINABLE leaked true")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    rows: list[dict[str, Any]] = []
    for item in STUB_INVENTORY:
        path = repo / str(item["rel"])
        if not path.is_file():
            return _skip_source(f"{item['rel']} missing; not fabricating stub inventory")
        text = path.read_text(encoding="utf-8")
        _require_needles(text, tuple(item["needles"]), item["rel"])
        if "TRAINABLE = True" in text or "TRAINABLE = true" in text:
            raise AssertionError(f"{item['rel']} leaked TRAINABLE=true")
        rows.append(
            {
                "id": item["id"],
                "rel": item["rel"],
                "trainable": False,
                "default_walk": bool(item.get("default_walk", False)),
            }
        )

    if NUM_OBSERVATIONS != REACTIVE_OBS or NUM_ACTIONS != REACTIVE_ACT:
        raise AssertionError("reactive contract drifted off 64→15")
    if NUM_OBSERVATIONS == WALK_OBS or NUM_ACTIONS == WALK_ACT:
        raise AssertionError("reactive collided with official walk 344→13")
    if TASK_NAME != "K1_Reactive":
        raise AssertionError("reactive task name drifted")
    if ISAAC_GYM_TASK_REGISTERED or IMPLEMENTED:
        raise AssertionError("reactive leaked registry / implemented=true")
    if DEFAULT_SKILL != "walk":
        raise AssertionError("default skill drifted off official walk")

    empty = select_skill(SkillSelectContext())
    reactive_ctx = select_skill(
        SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    )
    if not empty.is_official_walk() or not reactive_ctx.is_official_walk():
        raise AssertionError("empty / reactive-conditions must stay walk 344→13")

    try:
        create_training_env()
        raise AssertionError("create_training_env must raise")
    except RuntimeError:
        pass

    if (repo / OFFICIAL_REACTIVE_YAML).is_file():
        raise AssertionError("K1_Reactive.yaml leaked into official IsaacGymRL/envs/")
    init_text = (repo / OFFICIAL_ENVS_INIT).read_text(encoding="utf-8")
    if "K1_Reactive" in init_text:
        raise AssertionError("official envs/__init__.py leaked K1_Reactive")

    if WILL_RUN_TRAIN_PY or WILL_RUN_ISAAC_GYM:
        raise AssertionError("probe_reserved_gpu must keep will_run_* false")
    checklist = build_checklist(repo)
    ready = bool(checklist.get("ready"))
    extra_keys = set(checklist.get("checklist") or {}) - set(CHECKLIST_KEYS)
    if extra_keys & {"reactive", "stub", "estimator", "draft", "K1_Reactive"}:
        raise AssertionError(f"GPU checklist grew stub keys {sorted(extra_keys)}")
    if ready and extra_keys:
        raise AssertionError("ready_gpu true must not come from extra stub checklist keys")
    # Stubs exist in this tree; they must not be why ready is true.
    if ready and (
        REACTIVE_TRAINABLE
        or EST_TRAINABLE
        or ISAAC_GYM_TASK_REGISTERED
        or IMPLEMENTED
    ):
        raise AssertionError("ready_gpu became true because a stub leaked TRAINABLE/registry")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file()
        and not (_REACTIVE / name).is_file()
        and not (_ESTIMATORS / name).is_file()
        and not (_DRAFT / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}; do not re-audit by inventing them")

    hardening = _load_hardening(repo)
    hardening.assert_reactive_bypass()

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "stubs": rows,
        "reactive": {
            "task": TASK_NAME,
            "contract": "64→15",
            "trainable": False,
            "implemented": False,
            "registered": False,
            "default_skill": DEFAULT_SKILL,
            "is_default_walk_baseline": False,
        },
        "estimators": {
            "trainable": False,
            "latent_into_344": False,
        },
        "ready_gpu": {
            "ready": ready,
            "from_stub": False,
            "checklist_keys": list(CHECKLIST_KEYS),
            "will_run_train_py": False,
            "will_run_isaac_gym": False,
        },
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "reactive_as_default_walk": False,
        "stub_sets_ready_gpu_true": False,
        "walk_kick_gap_closed": False,
        "cross": {
            "empty_bt": empty.skill,
            "reactive_conditions": reactive_ctx.skill,
            "probe_ready": ready,
        },
        "fabricated": False,
        "note": (
            "all reactive / estimator / draft stubs stay TRAINABLE=false; "
            "default walk remains 344→13; stub presence must not flip ready_gpu"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "reactive_contract": "64→15",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else "",
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


def assert_stubs_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("reactive stub hardening leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate stub inventory")
        return snap
    ids = [row.get("id") for row in (snap.get("stubs") or [])]
    expected = [row["id"] for row in STUB_INVENTORY]
    if ids != expected:
        raise AssertionError(f"stub inventory drifted: {ids}")
    reactive = snap.get("reactive") or {}
    if reactive.get("trainable") or reactive.get("is_default_walk_baseline"):
        raise AssertionError("reactive leaked TRAINABLE or default-walk baseline")
    if reactive.get("default_skill") != "walk":
        raise AssertionError("default skill drifted off walk")
    ready = snap.get("ready_gpu") or {}
    if ready.get("from_stub") or ready.get("will_run_train_py"):
        raise AssertionError("stub flipped ready_gpu / will_run_train_py")
    if snap.get("reactive_as_default_walk") or snap.get("stub_sets_ready_gpu_true"):
        raise AssertionError("reactive-as-default or stub-ready_gpu leaked")
    if snap.get("walk_kick_gap_closed"):
        raise AssertionError("stub hardening must not close walk↔kick GAP")
    try:
        refuse_reactive_as_default_walk(
            {
                "reactive_as_default_walk": True,
                "source": "K1_Reactive",
                "default_baseline": "K1_Reactive",
            }
        )
        raise AssertionError("refuse_reactive_as_default_walk must raise")
    except ValueError:
        pass
    try:
        refuse_stub_sets_ready_gpu_true(
            {
                "stub_sets_ready_gpu_true": True,
                "source": "stub",
                "ready_gpu": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_stub_sets_ready_gpu_true must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("reactive stub hardening imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_stubs_frozen(repo)
        notes.append(
            "assert_stubs_frozen: TRAINABLE=false; reactive ≠ default walk; stub ≠ ready_gpu"
        )
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        notes.append("honest SKIP: stub inventory not fabricated")
    elif snap:
        notes.append("inventory: reactive / estimators / draft / GPU probe all TRAINABLE=false")
        notes.append("default skill walk 344→13; reactive conditions still walk")
        notes.append("ready_gpu checklist has no stub keys; will_run_train_py=false")
        notes.append("siblings referenced, not re-audited: hardening / estimator_ab / probe")

    probe_report = probe(repo)
    if probe_report.get("will_run_train_py") or probe_report.get("will_run_isaac_gym"):
        errors.append("probe must keep will_run_train_py / will_run_isaac_gym false")
    else:
        notes.append(f"probe ready={probe_report.get('ready')} (stub presence ignored)")

    for fn, claim, label in (
        (
            refuse_reactive_as_default_walk,
            {
                "reactive_as_default_walk": True,
                "source": "K1_Reactive",
                "default_baseline": "K1_Reactive",
            },
            "reactive as default walk",
        ),
        (
            refuse_stub_sets_ready_gpu_true,
            {
                "stub_sets_ready_gpu_true": True,
                "source": "stub",
                "ready_gpu": True,
            },
            "stub sets ready_gpu true",
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
            errors.append("K1.yaml changed during reactive stub hardening")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during reactive stub hardening")
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
        "reactive": "64→15",
        "ready_gpu": bool((snap.get("ready_gpu") or {}).get("ready")),
        "reactive_as_default_walk": False,
        "stub_sets_ready_gpu_true": False,
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
        print(f"[reactive-stub] FAIL {exc}")
        return 1
    print(
        f"[reactive-stub] {snap.get('status')} "
        f"TRAINABLE=false; default walk {snap.get('walk')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
