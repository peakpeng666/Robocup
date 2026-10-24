#!/usr/bin/env python3
"""T1/K1 isolation: any T1 weight/dim/ONNX replace of K1 walk must FAIL."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from t1_k1_isolation import (  # noqa: E402
    K1_FAMILY,
    T1_FAMILY,
    TRAINABLE,
    WRITE_YAML,
    assert_matrix_frozen,
    isolation_matrix,
    refuse_replace_k1_walk,
    refuse_t1_dims_as_k1_walk,
    refuse_t1_onnx_as_k1_walk,
    refuse_t1_weight_as_k1_walk,
    refuse_write_yaml,
    write_matrix,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("T1/K1 isolation imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("T1/K1 isolation flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = assert_matrix_frozen(repo)
        notes.append("assert_matrix_frozen: T1*/Huoshen → K1* may_replace=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    cells = data.get("cells") or isolation_matrix()
    if any(cell.get("may_replace") for cell in cells):
        errors.append("matrix leaked a replace=true cell")
    else:
        notes.append(f"isolation matrix {len(cells)} cells; none may replace")

    k1_walk = next(row for row in K1_FAMILY if row["is_walk_baseline"])
    if (k1_walk["obs"], k1_walk["act"]) != (344, 13):
        errors.append("K1 walk baseline drifted")
    t1_walk = next(row for row in T1_FAMILY if row["task"] == "T1")
    if (t1_walk["obs"], t1_walk["act"]) != (365, 14):
        errors.append("T1 walk dims drifted off 365→14")

    for src in T1_FAMILY:
        try:
            refuse_t1_dims_as_k1_walk(src["obs"], src["act"])
            errors.append(f"{src['task']} dims as K1 walk must raise")
        except ValueError:
            notes.append(f"negative: {src['task']} {src['obs']}→{src['act']} as walk refused")
        try:
            refuse_t1_onnx_as_k1_walk(src["onnx"])
            errors.append(f"{src['onnx']} as K1_walk.onnx must raise")
        except ValueError:
            notes.append(f"negative: {src['onnx']} as K1 walk ONNX refused")
        try:
            refuse_t1_weight_as_k1_walk(src["pth"])
            errors.append(f"{src['pth']} as K1_walk.pth must raise")
        except ValueError:
            notes.append(f"negative: {src['pth']} as K1 walk weight refused")
        try:
            refuse_replace_k1_walk(
                {
                    "family": "T1",
                    "from": src["task"],
                    "dest": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx",
                    "name": src["onnx"],
                    "obs": src["obs"],
                    "act": src["act"],
                    "replace_k1_walk": True,
                }
            )
            errors.append(f"{src['task']} replace K1 walk must raise")
        except ValueError:
            notes.append(f"negative: {src['task']} replace-K1-walk path refused")

    try:
        refuse_replace_k1_walk({"family": "huoshen_t1", "name": "model.pth", "as": "K1"})
        errors.append("Huoshen model.pth as K1 walk must raise")
    except ValueError:
        notes.append("negative: Huoshen model.pth as K1 walk refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = write_matrix(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during T1/K1 isolation")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[t1-k1-iso] {'PASS' if report['ok'] else 'FAIL'} "
        "T1 365/62/76 must not replace K1 walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
