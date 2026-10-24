"""Read-only ONNX/PTH path cross-check: CHECKPOINT-LAYOUT vs WalkingEngine.

Composed deploy path must be Config/NeuralNets/Walk/ + K1_walk.onnx.
Missing onnx/pth → honest SKIP. Path-declaration mismatch → FAIL.
Never writes weights or YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
if str(_SWITCHER) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_SWITCHER))

from checkpoint_layout import WALK_SLOTS  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13
SNAPSHOT_REL = "bhuman/k1-training/manifests/onnx-deploy-path-crosscheck-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DOC_REL = "bhuman/docs/CHECKPOINT-LAYOUT.md"
WALK_ENGINE_H_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h"
)
GETUP_ENGINE_H_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h"
)
K1_WALK_CFGS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg",
)
K1_GETUP_CFG = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
T1_WALK_CFG = "bhuman/BHumanCodeRelease/Config/Robots/Default/T1/walkingEngine.cfg"

EXPECTED_WALK_DIR = "Config/NeuralNets/Walk/"
EXPECTED_WALK_ONNX_NAME = "K1_walk.onnx"
EXPECTED_WALK_ONNX_REL = (
    "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx"
)
EXPECTED_GETUP_DIR = "Config/NeuralNets/GetUpEngine/"
PATH_RE = re.compile(r'File::getBHDir\(\)\) \+ "(/Config/NeuralNets/[^"]+)"')
NAME_RE = re.compile(r"^\s*(modelName|kickModel|policyName|policyNameFast)\s*=\s*(\S+);")
NUM_RE = re.compile(r"^\s*(numInput|numOutput|numInputFast|numOutputFast)\s*=\s*(\d+);")
def _named_block(text: str, name: str) -> str | None:
    token = f"{name} ="
    start = text.find(token)
    if start < 0:
        return None
    open_at = text.find("{", start)
    if open_at < 0:
        return None
    depth = 0
    for index, char in enumerate(text[open_at:], open_at):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : index]
    return None
DOC_ONNX_RE = re.compile(r"`(bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk\.onnx)`")
DOC_PTH_RE = re.compile(
    r"`(bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk\.pth)`"
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
        f"ONNX path cross-check is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_weights(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"ONNX path cross-check must not write {path or 'K1_walk.onnx'}"
    )


def refuse_t1_onnx_as_k1_walk(name: str) -> None:
    if name in {"T1_walk.onnx", "T1_kick_inner.onnx", "model.pth"}:
        raise ValueError(f"{name} must not be the official K1 walk ONNX")


def _parse_assignments(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = NAME_RE.match(line) or NUM_RE.match(line)
        if match:
            out[match.group(1)] = match.group(2).rstrip(";")
    return out


def _skip(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "path_consistent": None,
        "reason": reason,
        "files_missing": True,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "write_weights": False,
        "walk": "344→13",
        "note": "do not invent ONNX paths when sources are missing",
    }


def extract_crosscheck(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_WEIGHTS:
        raise AssertionError("ONNX path cross-check leaked write/train flags")
    repo = _repo(repo)
    walk_yaml = repo / K1_YAML_REL
    if "num_observations: 344" not in walk_yaml.read_text(encoding="utf-8"):
        raise AssertionError("official K1.yaml drifted off 344→13")

    engine_h = repo / WALK_ENGINE_H_REL
    doc = repo / DOC_REL
    if not engine_h.is_file() or not doc.is_file():
        missing = []
        if not engine_h.is_file():
            missing.append(WALK_ENGINE_H_REL)
        if not doc.is_file():
            missing.append(DOC_REL)
        return _skip(f"missing declaration source: {', '.join(missing)}")

    engine_text = engine_h.read_text(encoding="utf-8")
    path_match = PATH_RE.search(engine_text)
    if not path_match:
        return _skip("WalkingEngine.h modelPath not readable; not fabricating")
    engine_dir = path_match.group(1).lstrip("/") + (
        "" if path_match.group(1).endswith("/") else "/"
    )
    if engine_dir != EXPECTED_WALK_DIR:
        raise AssertionError(
            f"WalkingEngine modelPath drifted: {engine_dir} vs {EXPECTED_WALK_DIR}"
        )

    doc_text = doc.read_text(encoding="utf-8")
    doc_onnx = DOC_ONNX_RE.search(doc_text)
    doc_pth = DOC_PTH_RE.search(doc_text)
    if not doc_onnx or not doc_pth:
        raise AssertionError("CHECKPOINT-LAYOUT.md lost official walk onnx/pth paths")
    if doc_onnx.group(1) != EXPECTED_WALK_ONNX_REL:
        raise AssertionError("CHECKPOINT-LAYOUT walk ONNX path drifted")

    layout_onnx = next(
        slot["rel"] for slot in WALK_SLOTS if slot["role"] == "deploy_onnx"
    )
    if layout_onnx != EXPECTED_WALK_ONNX_REL:
        raise AssertionError("checkpoint_layout WALK_SLOTS deploy_onnx drifted")

    cfg_rows: list[dict[str, Any]] = []
    for rel in K1_WALK_CFGS:
        path = repo / rel
        if not path.is_file():
            raise AssertionError(f"missing K1 walkingEngine.cfg {rel}")
        text = path.read_text(encoding="utf-8")
        walk_block = _named_block(text, "walkNeuronalNetworkParameters")
        if not walk_block:
            raise AssertionError(f"{rel} missing walkNeuronalNetworkParameters")
        fields = _parse_assignments(walk_block)
        kick_block = _named_block(text, "ballNetworkParameters")
        kick_fields = _parse_assignments(kick_block) if kick_block else {}
        name = fields.get("modelName")
        if name != EXPECTED_WALK_ONNX_NAME:
            raise AssertionError(f"{rel} modelName={name} ≠ {EXPECTED_WALK_ONNX_NAME}")
        if fields.get("numInput") != str(WALK_OBS) or fields.get("numOutput") != str(WALK_ACT):
            raise AssertionError(f"{rel} walk net drifted off 344→13")
        composed = f"bhuman/BHumanCodeRelease/{EXPECTED_WALK_DIR}{name}"
        if composed != EXPECTED_WALK_ONNX_REL:
            raise AssertionError(f"composed walk ONNX drifted: {composed}")
        cfg_rows.append(
            {
                "rel": rel,
                "modelName": name,
                "numInput": int(fields["numInput"]),
                "numOutput": int(fields["numOutput"]),
                "kickModel": kick_fields.get("kickModel"),
                "composed_onnx": composed,
            }
        )

    t1_cfg = repo / T1_WALK_CFG
    t1_name = None
    if t1_cfg.is_file():
        t1_name = _parse_assignments(t1_cfg.read_text(encoding="utf-8")).get("modelName")
        if t1_name == EXPECTED_WALK_ONNX_NAME:
            raise AssertionError("T1 walkingEngine.cfg must not use K1_walk.onnx")

    getup: dict[str, Any] | None = None
    getup_h = repo / GETUP_ENGINE_H_REL
    getup_cfg = repo / K1_GETUP_CFG
    if getup_h.is_file() and getup_cfg.is_file():
        gpath = PATH_RE.search(getup_h.read_text(encoding="utf-8"))
        gfields = _parse_assignments(getup_cfg.read_text(encoding="utf-8"))
        gdir = gpath.group(1).lstrip("/") if gpath else None
        if gdir and not gdir.endswith("/"):
            gdir += "/"
        if gdir and gdir != EXPECTED_GETUP_DIR:
            raise AssertionError(f"GetUpEngine modelPath drifted: {gdir}")
        getup = {
            "dir": gdir,
            "policyName": gfields.get("policyName"),
            "policyNameFast": gfields.get("policyNameFast"),
            "is_walk_default": False,
            "note": "GetUpEngine ONNX is sibling deploy, not walk 344→13",
        }

    missing: list[str] = []
    present: list[str] = []
    for slot in WALK_SLOTS:
        path = repo / slot["rel"]
        if path.is_file() and path.stat().st_size > 0:
            present.append(slot["rel"])
        else:
            missing.append(slot["rel"])

    skipped = bool(missing)
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP" if skipped else "PASS",
        "skipped": skipped,
        "path_consistent": True,
        "reason": (
            "official walk onnx/pth absent (gitignored / local-only); "
            "declarations still cross-checked"
            if skipped
            else "official walk slots present and declarations match"
        ),
        "engine_dir": engine_dir,
        "cfg_model_name": EXPECTED_WALK_ONNX_NAME,
        "composed_walk_onnx": EXPECTED_WALK_ONNX_REL,
        "doc_walk_onnx": doc_onnx.group(1),
        "doc_walk_pth": doc_pth.group(1),
        "layout_walk_onnx": layout_onnx,
        "k1_cfgs": cfg_rows,
        "t1_model_name": t1_name,
        "t1_is_k1_walk": False,
        "getup": getup,
        "present": present,
        "missing": missing,
        "files_missing": skipped,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "write_weights": False,
        "walk": "344→13",
        "note": (
            "WalkingEngine + CHECKPOINT-LAYOUT + WALK_SLOTS agree on "
            "NeuralNets/Walk/K1_walk.onnx; missing weights stay SKIP"
        ),
    }


def write_crosscheck(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = extract_crosscheck(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml", ".onnx", ".pth"} or path.name in {
        "K1.yaml",
        "K1_walk.onnx",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_paths_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = extract_crosscheck(repo)
    if data.get("path_consistent") is False:
        raise AssertionError("ONNX/PTH path declarations inconsistent")
    if data.get("fabricated"):
        raise AssertionError("must not fabricate ONNX paths")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_crosscheck(repo, dest)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[onnx-path] FAIL {exc}")
        return 1
    tag = data.get("status") or "FAIL"
    print(f"[onnx-path] {tag} walk ONNX declarations; wrote {path}")
    if data.get("skipped"):
        print(f"[note] SKIP missing weights; path_consistent={data.get('path_consistent')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
