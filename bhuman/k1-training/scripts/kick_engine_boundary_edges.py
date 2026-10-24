"""KickEngine request/finish/abort edges vs kickPolicy 59→13 (read-only).

Deepens kick_engine_boundary without replacing it:

  * Request: dribble / walkToBallAndKick + walk-stay all false → kickPolicy 59→13
  * Abort/finish: walk-stay predicates set wasKicking=false → walkPolicy 344→13
  * PlayBall ≠ kickPolicy (pose chain only)
  * Standalone KickEngine.cpp stays un-fabricated SKIP
  * Overlay PASS is not a live RL kick deploy

Does not import ball_task_isolation_matrix.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/kick_engine_boundary_edges.py
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

from kick_engine_boundary import (  # noqa: E402
    KICK_ENGINE_RELS,
    TRAINABLE as BOUNDARY_TRAINABLE,
    locate_first,
    refuse_kick_replaces_walk,
)
from playball_not_kick_policy import (  # noqa: E402
    TRAINABLE as PLAYBALL_TRAINABLE,
    refuse_playball_as_kick_policy,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-engine-boundary-edges-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "request_edge_inventory",
    "finish_abort_edges",
    "playball_not_kick_policy",
    "standalone_kickengine_not_fabricated",
    "pass_not_live_rl_kick_deploy",
)

EDGES = (
    {
        "id": "request_kick_policy",
        "needle": "wasKicking = true",
        "selects": "kickPolicy",
        "contract": "59→13",
    },
    {
        "id": "abort_finish_walk",
        "needle": "wasKicking = false",
        "selects": "walkPolicy",
        "contract": "344→13",
    },
    {
        "id": "walk_stay_apply",
        "needle": "engine.walkPolicy.apply()",
        "selects": "walkPolicy",
        "contract": "344→13",
    },
    {
        "id": "kick_policy_apply",
        "needle": "CompiledNN& policy = !isOldKick ? engine.kickPolicy",
        "selects": "kickPolicy",
        "contract": "59→13",
    },
)

DOC_NEEDLES = (
    "kick_engine_boundary_edges",
    "apply_to_live=false",
    "59→13",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
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
        f"KickEngine edge overlay is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"KickEngine edge overlay is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_kick_engine_pass_as_live_rl_kick_deploy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-engine-pass-as-live-rl-kick-deploy claim must be a mapping")
    if (
        claim.get("kick_engine_pass_as_live_rl_kick_deploy")
        or claim.get("as_live_rl_kick_deploy")
        or claim.get("live_rl_kick_deploy")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("live") or claim.get("live_rl"))
        )
    ):
        raise ValueError(
            "KickEngine edge overlay PASS is not a live RL kick deploy; "
            "standalone KickEngine is un-fabricated SKIP; PlayBall ≠ kickPolicy; "
            "kickPolicy 59→13 stays a bypass"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _inventory_edges(repo: Path) -> list[dict[str, Any]]:
    cpp = repo / WALK_CPP_REL
    if not cpp.is_file():
        raise AssertionError(f"missing {WALK_CPP_REL}")
    text = cpp.read_text(encoding="utf-8")
    found: list[dict[str, Any]] = []
    for edge in EDGES:
        if edge["needle"] not in text:
            raise AssertionError(f"WalkingEngine.cpp missing edge {edge['id']}")
        found.append(dict(edge))
    if "policy.apply()" not in text:
        raise AssertionError("WalkingEngine.cpp missing kick policy.apply()")
    return found


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or BOUNDARY_TRAINABLE or PLAYBALL_TRAINABLE:
        raise AssertionError("KickEngine edge overlay leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    edges = _inventory_edges(repo)
    standalone, standalone_rel = locate_first(repo, KICK_ENGINE_RELS)
    if standalone is not None:
        raise AssertionError("standalone KickEngine appeared; overlay must not treat it as live RL")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/kick_engine_boundary_edges.py",
        "checklist": list(CHECKLIST),
        "edges": edges,
        "playball_is_kick_policy": False,
        "standalone_kick_engine": {
            "path": standalone_rel,
            "status": "SKIP",
            "fabricated": False,
        },
        "apply_to_live": False,
        "kick_engine_pass_as_live_rl_kick_deploy": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "request/abort edges stay kickPolicy 59→13 vs walkPolicy 344→13; "
            "PlayBall ≠ kickPolicy; overlay PASS ≠ live RL kick deploy"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
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
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_kick_engine_boundary_edges_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("KickEngine edge overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"KickEngine edge checklist drifted: {snap.get('checklist')}")
    if snap.get("apply_to_live") or snap.get("kick_engine_pass_as_live_rl_kick_deploy"):
        raise AssertionError("KickEngine edge leaked apply_to_live / live RL deploy")
    if snap.get("playball_is_kick_policy"):
        raise AssertionError("PlayBall must not be labeled kickPolicy")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("KickEngine edge leaked ready_gpu / would_train / GAP-closed")
    if (snap.get("standalone_kick_engine") or {}).get("fabricated"):
        raise AssertionError("must not fabricate standalone KickEngine")
    try:
        refuse_kick_engine_pass_as_live_rl_kick_deploy(
            {
                "kick_engine_pass_as_live_rl_kick_deploy": True,
                "as_live_rl_kick_deploy": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_kick_engine_pass_as_live_rl_kick_deploy must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("KickEngine edge overlay imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_kick_engine_boundary_edges_frozen(repo)
        notes.append("assert_kick_engine_boundary_edges_frozen: request/abort inventoried")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append(
            f"edges={len(snap.get('edges') or [])}; standalone KickEngine SKIP; "
            "PlayBall ≠ kickPolicy"
        )
        notes.append("overlay PASS ≠ live RL kick deploy")
        warnings.append("standalone KickEngine.cpp not in checkout; not fabricated")

    try:
        refuse_kick_engine_pass_as_live_rl_kick_deploy(
            {"status": "PASS", "live_rl": True, "this_pin": True}
        )
        errors.append("kick_engine_pass_as_live_rl_kick_deploy must raise")
    except ValueError:
        notes.append("negative: KickEngine PASS as live RL kick deploy refused")
    try:
        refuse_playball_as_kick_policy({"playball_as_kick_policy": True, "source": "PlayBall"})
        errors.append("refuse_playball_as_kick_policy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        refuse_kick_replaces_walk({"replaces_walk": True})
        errors.append("refuse_kick_replaces_walk must raise")
    except ValueError:
        notes.append("negative: kick replaces walk refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during KickEngine edge overlay")
            else:
                notes.append(f"official {label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "kick_engine_pass_as_live_rl_kick_deploy": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[kick-engine-edges] FAIL {exc}")
        return 1
    print(
        f"[kick-engine-edges] {snap.get('status')} "
        f"request/abort vs 59→13; PlayBall≠kickPolicy; "
        f"PASS ≠ live RL kick deploy; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
