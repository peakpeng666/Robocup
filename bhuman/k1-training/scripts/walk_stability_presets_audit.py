"""Read-only audit of official walk-*-stability-v1.json presets.

Lists algorithm keys and baselines (reference_mean_penalty=1.0 on the
reference preset). Draft-only must not pollute official files or
run_walk_stability.sh. Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
CONFIGS_REL = "bhuman/k1-training/configs"
DRAFT_ONLY_REL = "bhuman/k1-training/configs/draft-only"
STABILITY_SCRIPT_REL = "bhuman/k1-training/scripts/run_walk_stability.sh"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
AUDIT_REL = "bhuman/k1-training/manifests/walk-stability-presets-audit-latest.json"

EXPECTED_OFFICIAL = (
    "walk-reference-stability-v1.json",
    "walk-critic-stability-v1.json",
)
SHARED_BASELINE = {
    "max_update_kl": 0.02,
    "guard_min_lr": 1e-8,
    "critic_warmup_iterations": 20,
    "critic_warmup_lr": 0.0003,
    "critic_learning_rate": 0.0003,
}
REFERENCE_ONLY = {
    "reference_mean_penalty": 1.0,
}


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
        f"walk stability audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_draft_pollution(text: str, label: str) -> None:
    lowered = text.lower()
    if "draft-only" in lowered or "walk-p1-factors" in lowered:
        raise ValueError(f"{label} must not import draft-only")
    if '"draft_only": true' in lowered or "draft_only: true" in lowered:
        raise ValueError(f"{label} must not be a draft-only file")


def discover_official_presets(repo: Path) -> list[Path]:
    configs = repo / CONFIGS_REL
    found: list[Path] = []
    for path in sorted(configs.glob("walk-*-stability-v1.json")):
        rel = path.relative_to(repo).as_posix()
        if "draft-only" in rel:
            raise AssertionError(f"official glob leaked draft-only {rel}")
        found.append(path)
    names = {path.name for path in found}
    if names != set(EXPECTED_OFFICIAL):
        raise AssertionError(
            f"official walk-*-stability-v1 set drifted: {sorted(names)} vs {list(EXPECTED_OFFICIAL)}"
        )
    by_name = {path.name: path for path in found}
    return [by_name[name] for name in EXPECTED_OFFICIAL]


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(value, path))
    else:
        out[prefix] = obj
    return out


def _num_eq(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-12
    except (TypeError, ValueError):
        return False


def audit_presets(repo: Path | None = None) -> dict[str, Any]:
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("walk stability audit leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    presets: list[dict[str, Any]] = []
    for path in discover_official_presets(repo):
        text = path.read_text(encoding="utf-8")
        refuse_draft_pollution(text, path.name)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} is not a mapping")
        if data.get("draft_only") is True:
            raise AssertionError(f"{path.name} leaked draft_only:true")
        algo = data.get("algorithm") or {}
        if not isinstance(algo, dict):
            raise ValueError(f"{path.name} algorithm is not a mapping")
        keys = sorted(algo.keys())
        flat = _flatten({"algorithm": algo})
        row = {
            "name": path.name,
            "rel": path.relative_to(repo).as_posix(),
            "draft_only": False,
            "algorithm_keys": keys,
            "algorithm": dict(algo),
            "flat": flat,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for key, expect in SHARED_BASELINE.items():
            if key not in algo or not _num_eq(algo[key], expect):
                raise AssertionError(f"{path.name} {key} drifted off {expect}")
        if path.name == "walk-reference-stability-v1.json":
            penalty = algo.get("reference_mean_penalty")
            if not _num_eq(penalty, REFERENCE_ONLY["reference_mean_penalty"]):
                raise AssertionError(
                    f"reference preset reference_mean_penalty drifted: {penalty}"
                )
            row["reference_mean_penalty"] = float(penalty)
        else:
            if "reference_mean_penalty" in algo:
                raise AssertionError(
                    "critic preset must not carry reference_mean_penalty "
                    "(that baseline lives on walk-reference-stability-v1)"
                )
            row["reference_mean_penalty"] = None
        presets.append(row)

    script = repo / STABILITY_SCRIPT_REL
    script_text = script.read_text(encoding="utf-8") if script.is_file() else ""
    if not script_text:
        raise AssertionError("missing run_walk_stability.sh")
    refuse_draft_pollution(script_text, "run_walk_stability.sh")
    if "walk-${preset}-stability-v1.json" not in script_text:
        raise AssertionError("run_walk_stability.sh must load official walk-*-stability-v1")

    draft_root = repo / DRAFT_ONLY_REL
    leaked = [
        path.name
        for path in draft_root.glob("walk-*-stability-v1.json")
        if path.is_file()
    ]
    if leaked:
        raise AssertionError(f"draft-only leaked official stability filenames: {leaked}")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "walk": "344→13",
        "official": [row["name"] for row in presets],
        "presets": presets,
        "baseline": {
            **SHARED_BASELINE,
            "reference_mean_penalty": REFERENCE_ONLY["reference_mean_penalty"],
            "reference_mean_penalty_lives_on": "walk-reference-stability-v1.json",
        },
        "draft_pollution": False,
        "stability_script_reads_draft": False,
        "trainable": False,
        "write_yaml": False,
        "note": (
            "official walk-*-stability-v1 only; draft-only excluded; "
            "reference_mean_penalty 1.0 stays on the reference preset"
        ),
    }


def write_audit(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = audit_presets(repo)
    path = dest or (repo / AUDIT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_audit_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = audit_presets(repo)
    if data.get("draft_pollution") or data.get("stability_script_reads_draft"):
        raise AssertionError("draft-only polluted official walk stability presets")
    if data.get("official") != list(EXPECTED_OFFICIAL):
        raise AssertionError("official preset list drifted")
    ref = next(row for row in data["presets"] if row["name"].startswith("walk-reference"))
    if ref.get("reference_mean_penalty") != 1.0:
        raise AssertionError("reference_mean_penalty baseline drifted")
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
        print(f"[walk-stability] FAIL {exc}")
        return 1
    print(f"[walk-stability] PASS official presets; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
