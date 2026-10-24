"""TeamComm shape negatives (128 vs 512 / CompressedTeamComm bounds).

Deepens teamcomm_128_vs_512 + compressed_teamcomm_shape + teamcomm_budget
without replacing them:

  * Official TeamMessageContainer data[128] ≠ HSL GameController 512 B budget
  * CompressedTeamCommunication type/stream bounds stay inventoried
  * Bandwidth without robot/WLAN stays SKIP
  * Silent size-upgrade claims are refused
  * gap_closed stays false

Does not import reactive_intercept_bypass_hardening or pr_volume_health_rescan.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/teamcomm_shape_negatives.py
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
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from compressed_teamcomm_shape import (  # noqa: E402
    CONTAINER_RELS,
    EXPECTED_STREAMS,
    EXPECTED_TYPES,
    HSL_BUDGET_B,
    STREAMS_RELS,
    extract_container_bytes,
    extract_declared_types,
    extract_stream_classes,
    locate_first,
    refuse_oversize_vs_hsl,
)
from teamcomm_128_vs_512 import (  # noqa: E402
    OFFICIAL_CONTAINER_B,
    refuse_mix_128_512,
)
from teamcomm_budget import (  # noqa: E402
    BUDGET_B,
    probe_bandwidth,
    refuse_fake_bandwidth_pass,
    refuse_teammate_into_344,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
IMPLEMENTED = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/teamcomm-shape-negatives-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
TEAMCOMM_DOC_REL = "bhuman/docs/TEAMCOMM-128-VS-512.md"

CHECKLIST = (
    "official_128_vs_hsl_512",
    "compressed_bounds",
    "bandwidth_skip",
    "silent_upgrade_forbidden",
    "gap_closed_false",
)

DOC_NEEDLES = (
    "teamcomm_shape_negatives",
    "128",
    "512",
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
        f"teamcomm shape negatives are read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"teamcomm shape negatives are read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_silent_teamcomm_size_upgrade(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-teamcomm-size-upgrade claim must be a mapping")
    if (
        claim.get("silent_teamcomm_size_upgrade")
        or claim.get("silent_size_upgrade")
        or claim.get("overwrite_128_with_512")
        or claim.get("data_512_as_official")
        or claim.get("official_container_b") == 512
        or claim.get("label_128_as_hsl_satisfied")
    ):
        raise ValueError(
            "must not silently upgrade TeamMessageContainer 128 to 512; "
            "128 is the rule-book onboard container; 512 is the HSL budget"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or IMPLEMENTED:
        raise AssertionError("teamcomm shape overlay leaked TRAINABLE / IMPLEMENTED")
    if OFFICIAL_CONTAINER_B != 128 or HSL_BUDGET_B != 512 or BUDGET_B != 512:
        raise AssertionError("official 128 / HSL 512 bounds drifted")
    if OFFICIAL_CONTAINER_B == HSL_BUDGET_B:
        raise AssertionError("128 and 512 must stay different purposes")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    container, container_rel = locate_first(repo, CONTAINER_RELS)
    official_b = None
    if container is None:
        raise AssertionError("TeamMessageContainer.h missing; not fabricating 128")
    official_b = extract_container_bytes(container.read_text(encoding="utf-8"))
    if official_b != OFFICIAL_CONTAINER_B:
        raise AssertionError(
            f"official container drifted to data[{official_b}]; expected 128"
        )

    streams, streams_rel = locate_first(repo, STREAMS_RELS)
    if streams is None:
        raise AssertionError("CompressedTeamCommunicationStreams.h missing")
    streams_text = streams.read_text(encoding="utf-8")
    types = extract_declared_types(streams_text)
    stream_classes = extract_stream_classes(streams_text)
    if types != list(EXPECTED_TYPES):
        raise AssertionError(f"CompressedTeamComm types drifted: {types}")
    if stream_classes != list(EXPECTED_STREAMS):
        raise AssertionError(f"CompressedTeamComm streams drifted: {stream_classes}")

    try:
        refuse_oversize_vs_hsl(HSL_BUDGET_B + 1)
        raise AssertionError("refuse_oversize_vs_hsl must raise above 512")
    except ValueError:
        pass

    bandwidth = probe_bandwidth()
    if bandwidth.get("status") == "PASS":
        raise AssertionError("bandwidth measure must stay SKIP without robot/WLAN")
    refuse_fake_bandwidth_pass(
        {"status": "SKIP", "kind": "bandwidth", "robot_connected": False, "wlan": False}
    )

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    teamcomm_doc = repo / TEAMCOMM_DOC_REL
    if not compat.is_file() or not artifacts.is_file() or not teamcomm_doc.is_file():
        raise AssertionError("COMPAT / ARTIFACTS / TEAMCOMM-128-VS-512 missing")
    for path, label in (
        (compat, COMPAT_DOC_REL),
        (artifacts, ARTIFACTS_DOC_REL),
        (teamcomm_doc, TEAMCOMM_DOC_REL),
    ):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/teamcomm_shape_negatives.py",
        "checklist": list(CHECKLIST),
        "official_container_b": official_b,
        "hsl_budget_b": HSL_BUDGET_B,
        "same_number": False,
        "sources": {"container": container_rel, "streams": streams_rel, "doc": TEAMCOMM_DOC_REL},
        "compressed_types": types,
        "compressed_streams": stream_classes,
        "bandwidth": bandwidth,
        "overwrite_128_with_512": False,
        "label_128_as_hsl_satisfied": False,
        "silent_teamcomm_size_upgrade": False,
        "teammate_into_344": False,
        "implemented": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "128 vs 512 stay different purposes; CompressedTeamComm bounds inventoried; "
            "bandwidth SKIP; silent size upgrade refused"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
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


def assert_teamcomm_shape_negatives_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or IMPLEMENTED:
        raise AssertionError("teamcomm shape overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"teamcomm shape checklist drifted: {snap.get('checklist')}")
    if snap.get("official_container_b") != 128 or snap.get("hsl_budget_b") != 512:
        raise AssertionError("128 vs 512 bounds drifted")
    if snap.get("same_number") or snap.get("silent_teamcomm_size_upgrade"):
        raise AssertionError("teamcomm shape leaked silent size upgrade")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("teamcomm shape leaked ready_gpu / would_train / GAP-closed")
    try:
        refuse_silent_teamcomm_size_upgrade(
            {
                "silent_teamcomm_size_upgrade": True,
                "overwrite_128_with_512": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_silent_teamcomm_size_upgrade must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("teamcomm shape overlay imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_teamcomm_shape_negatives_frozen(repo)
        notes.append("assert_teamcomm_shape_negatives_frozen: 128≠512")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append(
            f"official data[{snap.get('official_container_b')}] vs HSL {snap.get('hsl_budget_b')} B; "
            f"types={len(snap.get('compressed_types') or [])}"
        )
        notes.append("silent size upgrade forbidden; bandwidth SKIP; GAP open")

    try:
        refuse_silent_teamcomm_size_upgrade(
            {"official_container_b": 512, "data_512_as_official": True}
        )
        errors.append("silent_teamcomm_size_upgrade must raise")
    except ValueError:
        notes.append("negative: data[512] as official refused")
    try:
        refuse_mix_128_512({"overwrite_128_with_512": True})
        errors.append("refuse_mix_128_512 must raise")
    except ValueError:
        notes.append("negative: mix 128/512 refused")
    try:
        refuse_teammate_into_344({"teammate_into_344": True, "obs": 344})
        errors.append("refuse_teammate_into_344 must raise")
    except ValueError:
        notes.append("negative: teammate into 344 refused")
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
                errors.append(f"{label} changed during teamcomm shape overlay")
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
        "silent_teamcomm_size_upgrade": False,
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
        print(f"[teamcomm-negatives] FAIL {exc}")
        return 1
    print(
        f"[teamcomm-negatives] {snap.get('status')} "
        f"128≠512; silent upgrade refused; bandwidth SKIP; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
