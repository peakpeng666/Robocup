"""CompressedTeamCommunication shape stub (no WLAN, no robot).

Parses official stream-type declarations and TeamMessageContainer size.
HSL GameController budget is 512 B; official B-Human container is the
rule-book `data[N]` (currently 128). Do not pretend they are the same.
Teammate / compressed payload must not enter walk 344.
Missing source → honest SKIP. Bandwidth without robot/WLAN → SKIP.
Never writes K1.yaml. TRAINABLE=false.

See GLOBAL §6.7 and teamcomm_budget.py (budget convention; this file is shape).
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

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from teamcomm_budget import (  # noqa: E402
    BUDGET_B,
    probe_bandwidth,
    refuse_fake_bandwidth_pass,
    refuse_teammate_into_344,
)

TRAINABLE = False
IMPLEMENTED = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
HSL_BUDGET_B = BUDGET_B
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/compressed-teamcomm-shape-latest.json"

STREAMS_RELS = (
    "bhuman/BHumanCodeRelease/Src/Tools/Communication/CompressedTeamCommunicationStreams.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Tools/Communication/CompressedTeamCommunicationStreams.h",
)
CONTAINER_RELS = (
    "bhuman/BHumanCodeRelease/Src/Tools/Communication/TeamMessageContainer.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Tools/Communication/TeamMessageContainer.h",
)
HANDLER_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/Communication/TeamMessageHandler/TeamMessageHandler.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/Communication/TeamMessageHandler/TeamMessageHandler.cpp",
)
DEF_RELS = (
    "bhuman/BHumanCodeRelease/Config/teamMessage.def",
    "bhuman/BHumanCodeRelease/Config/Scenarios/Default/teamMessage.def",
)
DOC_RELS = (
    "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md",
    "bhuman/docs/P5-PREVIEW.md",
)

EXPECTED_TYPES = (
    "RecordType",
    "ArrayType",
    "BooleanType",
    "IntegerType",
    "AngleType",
    "FloatType",
    "TimestampType",
    "EnumType",
    "VectorType",
    "MatrixType",
)
EXPECTED_STREAMS = (
    "CompressedTeamCommunicationIn",
    "CompressedTeamCommunicationOut",
)
EXPECTED_REPS = (
    "RobotStatus",
    "FrameInfo",
    "BallModel",
    "Whistle",
    "BehaviorStatus",
    "StrategyStatus",
    "IndirectKick",
)
CONTAINER_RE = re.compile(r"char\s+data\[(\d+)\]")
TYPE_RE = re.compile(r"\b(?:struct|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
REP_RE = re.compile(r"_\(([A-Za-z0-9_]+)\)")


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
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
        f"CompressedTeamCommunication shape stub is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_oversize_vs_hsl(nbytes: int) -> None:
    if nbytes > HSL_BUDGET_B:
        raise ValueError(f"TeamComm payload {nbytes} B exceeds HSL 512 B budget")


def refuse_oversize_vs_official(nbytes: int, official_b: int | None) -> None:
    if official_b is None:
        return
    if nbytes > official_b:
        raise ValueError(
            f"TeamComm payload {nbytes} B exceeds official TeamMessageContainer {official_b} B"
        )


def refuse_teamcomm_into_344(claim: dict[str, Any]) -> None:
    refuse_teammate_into_344(claim)
    if not isinstance(claim, dict):
        raise ValueError("obs claim must be a mapping")
    if claim.get("compressed_into_344") or claim.get("team_message_into_walk"):
        raise ValueError("compressed TeamComm must not enter official walk 344")
    extra = int(claim.get("teamcomm_dim") or 0)
    if claim.get("obs") == WALK_OBS and extra:
        raise ValueError("teamcomm_dim must stay 0 on official walk 344")


def extract_declared_types(text: str) -> list[str]:
    found = [name for name in TYPE_RE.findall(text) if name in EXPECTED_TYPES]
    # Preserve official declaration order.
    return [name for name in EXPECTED_TYPES if name in found]


def extract_stream_classes(text: str) -> list[str]:
    found = [name for name in TYPE_RE.findall(text) if name in EXPECTED_STREAMS]
    return [name for name in EXPECTED_STREAMS if name in found]


def extract_container_bytes(text: str) -> int | None:
    match = CONTAINER_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def extract_foreach_reps(text: str) -> list[str]:
    idx = text.find("#define FOREACH_TEAM_MESSAGE_REPRESENTATION")
    if idx < 0:
        return []
    chunk = text[idx : idx + 500]
    names = REP_RE.findall(chunk)
    # Keep first-hit order, drop the macro parameter `_` if captured.
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def _skip_snapshot(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "sources": {},
        "stream_types": [],
        "stream_classes": [],
        "representations": [],
        "hsl_budget_b": HSL_BUDGET_B,
        "official_container_b": None,
        "team_message_def_present": False,
        "schema_status": "SKIP",
        "bandwidth": probe_bandwidth(),
        "teammate_into_344": False,
        "fabricated": False,
        "note": "do not invent CompressedTeamCommunication types when source is missing",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        raise AssertionError("teamcomm shape stub leaked TRAINABLE/IMPLEMENTED/WRITE_YAML")
    repo = _repo(repo)
    streams, streams_rel = locate_first(repo, STREAMS_RELS)
    if streams is None:
        return _skip_snapshot(
            "CompressedTeamCommunicationStreams.h not found; not fabricating types"
        )

    text = streams.read_text(encoding="utf-8")
    types = extract_declared_types(text)
    classes = extract_stream_classes(text)
    if not types or not classes:
        return _skip_snapshot("stream type/class declarations unreadable; not fabricating")
    missing_types = [name for name in EXPECTED_TYPES if name not in types]
    missing_classes = [name for name in EXPECTED_STREAMS if name not in classes]
    if missing_types or missing_classes:
        raise AssertionError(
            f"CompressedTeamCommunication declarations drifted: types={missing_types} "
            f"classes={missing_classes}"
        )

    container, container_rel = locate_first(repo, CONTAINER_RELS)
    official_b = None
    container_note = "TeamMessageContainer.h missing; official size unknown"
    if container is not None:
        official_b = extract_container_bytes(container.read_text(encoding="utf-8"))
        if official_b is None:
            return _skip_snapshot("TeamMessageContainer data[N] unreadable; not fabricating size")
        container_note = (
            f"official B-Human container is data[{official_b}] (rule-book constant); "
            f"HSL GameController budget is {HSL_BUDGET_B} B; do not pretend they match"
        )

    handler, handler_rel = locate_first(repo, HANDLER_RELS)
    reps: list[str] = []
    if handler is not None:
        reps = extract_foreach_reps(handler.read_text(encoding="utf-8"))
        missing_reps = [name for name in EXPECTED_REPS if name not in reps]
        if missing_reps:
            raise AssertionError(f"FOREACH_TEAM_MESSAGE_REPRESENTATION drifted: {missing_reps}")

    def_path, def_rel = locate_first(repo, DEF_RELS)
    schema_status = "PASS" if def_path is not None else "SKIP"
    schema_reason = None if def_path is not None else "teamMessage.def not in checkout"

    docs_record_512 = False
    for rel in DOC_RELS:
        path = repo / rel
        if path.is_file() and "512" in path.read_text(encoding="utf-8"):
            docs_record_512 = True
            break
    if not docs_record_512:
        raise AssertionError("docs no longer record HSL TeamComm 512 B")

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    bandwidth = probe_bandwidth()
    if bandwidth.get("status") == "PASS":
        raise AssertionError("bandwidth measure must stay SKIP without robot/WLAN")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "sources": {
            "streams": streams_rel,
            "container": container_rel,
            "handler": handler_rel,
            "team_message_def": def_rel,
        },
        "stream_types": types,
        "stream_classes": classes,
        "representations": reps,
        "hsl_budget_b": HSL_BUDGET_B,
        "official_container_b": official_b,
        "same_as_hsl_512": official_b == HSL_BUDGET_B,
        "team_message_def_present": def_path is not None,
        "schema_status": schema_status,
        "schema_reason": schema_reason,
        "docs_record_512": docs_record_512,
        "bandwidth": bandwidth,
        "teammate_into_344": False,
        "container_note": container_note,
        "fabricated": False,
        "note": (
            "HSL max 512 B; official container is rule-book data[N]; "
            "compressed teammate state must not concat onto walk 344; "
            "no WLAN → bandwidth SKIP"
        ),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_shape_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        raise AssertionError("teamcomm shape leaked flags")
    if snap.get("skipped"):
        if snap.get("stream_types") or snap.get("stream_classes"):
            raise AssertionError("SKIP snapshot must not fabricate stream types")
        return snap
    if snap.get("hsl_budget_b") != HSL_BUDGET_B or snap.get("teammate_into_344"):
        raise AssertionError("TeamComm shape budget drifted")
    refuse_oversize_vs_hsl(HSL_BUDGET_B)
    try:
        refuse_oversize_vs_hsl(HSL_BUDGET_B + 1)
    except ValueError:
        pass
    else:
        raise AssertionError("HSL 513 B payload must be refused")
    official = snap.get("official_container_b")
    if official:
        refuse_oversize_vs_official(official, official)
        try:
            refuse_oversize_vs_official(official + 1, official)
        except ValueError:
            pass
        else:
            raise AssertionError("payload above official container must be refused")
    try:
        refuse_teamcomm_into_344({"compressed_into_344": True, "obs": WALK_OBS})
    except ValueError:
        return snap
    raise AssertionError("compressed TeamComm into 344 must be refused")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("teamcomm shape stub imported Gym")
    if TRAINABLE or IMPLEMENTED or WRITE_YAML:
        errors.append("teamcomm shape flags leaked")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated stream types")
        if snap.get("stream_types") or snap.get("stream_classes"):
            errors.append("SKIP snapshot must not invent stream types")
    elif snap:
        official = snap.get("official_container_b")
        notes.append(
            f"HSL budget {snap.get('hsl_budget_b')} B; official container {official} B; "
            "not the same number"
        )
        notes.append(f"stream types: {', '.join(snap.get('stream_types') or [])}")
        if snap.get("schema_status") == "SKIP":
            warnings.append(str(snap.get("schema_reason") or "teamMessage.def missing"))
            notes.append("teamMessage.def schema SKIP (not in checkout)")

    live = probe_bandwidth()
    if live.get("status") == "PASS":
        errors.append("bandwidth must not PASS without robot/WLAN")
    else:
        notes.append("bandwidth measure SKIP (no robot / WLAN)")

    try:
        refuse_oversize_vs_hsl(HSL_BUDGET_B + 1)
        errors.append("513 B HSL payload must raise")
    except ValueError:
        notes.append("negative: payload >512 B HSL refused")

    official = snap.get("official_container_b")
    if official:
        try:
            refuse_oversize_vs_official(official + 1, official)
            errors.append("payload above official container must raise")
        except ValueError:
            notes.append(f"negative: payload >{official} B official container refused")

    for claim, label in (
        ({"teammate_into_344": True, "obs": WALK_OBS}, "teammate_into_344"),
        ({"compressed_into_344": True, "obs": WALK_OBS}, "compressed_into_344"),
        ({"obs": WALK_OBS, "teamcomm_dim": 8}, "teamcomm_dim on 344"),
    ):
        try:
            refuse_teamcomm_into_344(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_fake_bandwidth_pass({"status": "PASS", "kind": "wlan"})
        errors.append("fake WLAN PASS must raise")
    except ValueError:
        notes.append("negative: fake WLAN PASS refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before != after:
            errors.append("K1.yaml changed during teamcomm shape stub")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped") or live.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
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
        print(f"[teamcomm-shape] FAIL {exc}")
        return 1
    tag = snap.get("status") or "FAIL"
    print(
        f"[teamcomm-shape] {tag} HSL {HSL_BUDGET_B} B / official "
        f"{snap.get('official_container_b')} B; not into 344; wrote {path}"
    )
    if snap.get("skipped"):
        print(f"[note] SKIP {snap.get('reason')}; no fabricated types")
    elif snap.get("schema_status") == "SKIP":
        print(f"[note] schema SKIP {snap.get('schema_reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
