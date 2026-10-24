"""Read-only audit of official registered sibling tasks.

K1_Ball / K1_Stand_Up (and same-tree T1*) are registered Isaac tasks.
They are not the default walk baseline and are not a license to merge
into official walk 344. Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
DEFAULT_TASK = "K1"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
AUDIT_REL = "bhuman/k1-training/manifests/official-sibling-tasks-audit-latest.json"
ENV_TREES = (
    "bhuman/MachineLearning/IsaacGymRL/envs",
    "bhuman/k1-training/src/IsaacGymRL/envs",
)
IMPORT_RE = re.compile(r"^from envs\.([A-Za-z0-9_]+) import ([A-Za-z0-9_]+)\s*$")
DIM_RE = re.compile(r"^\s*num_(observations|actions):\s*(-?\d+)\s*$")

# Registered official K1 family besides default walk.
K1_SIBLINGS = (
    {
        "task": "K1_Ball",
        "yaml": "K1_Ball.yaml",
        "obs": 59,
        "act": 13,
        "purpose": "official kick (shared 13-D walk exit)",
        "skill": "kick",
        "contract": "59→13",
    },
    {
        "task": "K1_Stand_Up",
        "yaml": "K1_Stand_Up.yaml",
        "obs": 73,
        "act": 22,
        "purpose": "official standup (GetUpEngine 22 motors)",
        "skill": "standup",
        "contract": "73→22",
    },
)
# Same Isaac registry, B-Human T1 — not K1 walk and not Huoshen T1.
T1_REGISTERED = (
    {
        "task": "T1",
        "yaml": "T1.yaml",
        "obs": 365,
        "act": 14,
        "purpose": "B-Human T1 walk (same family, not K1)",
        "skill": "t1_walk",
        "contract": "365→14",
    },
    {
        "task": "T1_Ball",
        "yaml": "T1_Ball.yaml",
        "obs": 62,
        "act": 14,
        "purpose": "B-Human T1 kick (not K1_Ball)",
        "skill": "t1_kick",
        "contract": "62→14",
    },
    {
        "task": "T1_Stand_Up",
        "yaml": "T1_Stand_Up.yaml",
        "obs": 76,
        "act": 23,
        "purpose": "B-Human T1 standup (not K1_Stand_Up)",
        "skill": "t1_standup",
        "contract": "76→23",
    },
)
DEPLOY_ONLY = (
    {
        "task": "K1_fast_standup",
        "yaml": None,
        "obs": 72,
        "act": 22,
        "purpose": "deploy-only GetUpEngine fast net; not an Isaac task",
        "skill": "fast_standup",
        "contract": "72→22",
        "registered": False,
    },
)
NOT_WALK_BASELINE = frozenset(
    row["task"] for row in (*K1_SIBLINGS, *T1_REGISTERED, *DEPLOY_ONLY)
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
        f"sibling-task audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_sibling_as_walk_baseline(task: str, obs: int | None = None, act: int | None = None) -> None:
    name = str(task or "")
    if name in NOT_WALK_BASELINE:
        raise ValueError(f"{name} is not the default walk baseline 344→13")
    if name == DEFAULT_TASK and (obs, act) not in {(None, None), (WALK_OBS, WALK_ACT)}:
        raise ValueError("official K1 walk baseline must stay 344→13")
    if (obs, act) == (WALK_OBS, WALK_ACT) and name and name != DEFAULT_TASK:
        raise ValueError(f"{name} must not impersonate official walk 344→13")


def refuse_merge_sibling_into_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("merge claim must be a mapping")
    task = str(claim.get("task") or claim.get("source") or "")
    if claim.get("concat_into") == WALK_OBS or claim.get("merge_into_walk_obs"):
        raise ValueError(
            f"{task or 'sibling'} obs must not be concatenated into official walk 344"
        )
    if claim.get("is_walk_baseline") and task in NOT_WALK_BASELINE:
        raise ValueError(f"{task} is not a license to become the walk baseline")
    extra = claim.get("extra_obs")
    if extra in {59, 73, 72, 365, 62, 76}:
        raise ValueError("sibling / T1 obs dims must not be folded into 344")


def parse_registered_tasks(init_text: str) -> list[str]:
    names: list[str] = []
    for line in init_text.splitlines():
        match = IMPORT_RE.match(line.strip())
        if match:
            names.append(match.group(2))
    return names


def parse_yaml_dims(text: str) -> tuple[int | None, int | None]:
    obs = act = None
    for line in text.splitlines():
        match = DIM_RE.match(line)
        if not match:
            continue
        value = int(match.group(2))
        if match.group(1) == "observations":
            obs = value
        else:
            act = value
    return obs, act


def _audit_row(repo: Path, spec: dict[str, Any], registered: set[str]) -> dict[str, Any]:
    yaml_name = spec.get("yaml")
    yaml_hits: list[dict[str, Any]] = []
    for tree in ENV_TREES:
        if not yaml_name:
            continue
        path = repo / tree / yaml_name
        if not path.is_file():
            yaml_hits.append({"rel": f"{tree}/{yaml_name}", "present": False})
            continue
        obs, act = parse_yaml_dims(path.read_text(encoding="utf-8"))
        yaml_hits.append(
            {
                "rel": f"{tree}/{yaml_name}",
                "present": True,
                "obs": obs,
                "act": act,
                "matches_contract": (obs, act) == (spec["obs"], spec["act"]),
            }
        )
    is_registered = spec["task"] in registered
    expected_registered = spec.get("registered", True)
    return {
        **spec,
        "is_walk_baseline": False,
        "may_merge_into_344": False,
        "registered": is_registered,
        "registration_ok": is_registered is expected_registered,
        "yaml": yaml_hits,
        "dims_ok": all(
            hit.get("matches_contract") for hit in yaml_hits if hit.get("present")
        )
        if yaml_hits
        else spec.get("registered") is False,
    }


def audit(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("sibling-task audit leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    walk_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    walk_obs, walk_act = parse_yaml_dims(walk_text)
    if (walk_obs, walk_act) != (WALK_OBS, WALK_ACT):
        raise AssertionError("official K1.yaml drifted off 344→13")

    registered: set[str] = set()
    trees: list[dict[str, Any]] = []
    for tree in ENV_TREES:
        init = repo / tree / "__init__.py"
        text = init.read_text(encoding="utf-8") if init.is_file() else ""
        tasks = parse_registered_tasks(text)
        registered.update(tasks)
        trees.append({"rel": tree, "tasks": tasks})
        if "K1" not in tasks:
            raise AssertionError(f"{tree} lost official K1 registration")

    k1_rows = [_audit_row(repo, spec, registered) for spec in K1_SIBLINGS]
    t1_rows = [_audit_row(repo, spec, registered) for spec in T1_REGISTERED]
    deploy_rows = [_audit_row(repo, spec, registered) for spec in DEPLOY_ONLY]
    for row in (*k1_rows, *t1_rows):
        if not row["registration_ok"] or not row["dims_ok"]:
            raise AssertionError(f"{row['task']} sibling contract drifted")
        if row["is_walk_baseline"] or row["may_merge_into_344"]:
            raise AssertionError(f"{row['task']} leaked walk-baseline / merge-into-344")
    for row in deploy_rows:
        if row["registered"]:
            raise AssertionError("K1_fast_standup must not be an Isaac registered task")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "default_task": DEFAULT_TASK,
        "default_is_walk_baseline": True,
        "siblings_are_walk_baseline": False,
        "may_merge_into_344": False,
        "k1_siblings": k1_rows,
        "t1_registered_not_k1": t1_rows,
        "deploy_only": deploy_rows,
        "trees": trees,
        "trainable": False,
        "write_yaml": False,
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
        "note": (
            "K1_Ball 59→13 / K1_Stand_Up 73→22 are official siblings, not the "
            "walk baseline and not a concat-into-344 permit; T1* is B-Human T1"
        ),
    }


def write_audit(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = audit(repo)
    path = dest or (repo / AUDIT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_siblings_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit(repo)
    if data.get("siblings_are_walk_baseline") or data.get("may_merge_into_344"):
        raise AssertionError("siblings leaked walk-baseline / merge-into-344")
    if data.get("default_task") != DEFAULT_TASK:
        raise AssertionError("default task drifted off K1")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_audit(repo, dest)
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[sibling-tasks] FAIL {exc}")
        return 1
    print(f"[sibling-tasks] PASS K1_Ball/Stand_Up ≠ walk 344; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
