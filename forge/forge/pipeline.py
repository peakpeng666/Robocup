"""Candidate pipeline: checkpoint -> pack -> three-engine evidence + fragility atlas -> promotion gate.

Steps run sequentially (they share the GPU and the SimRobot lock) and every intermediate
artefact is recorded in ``runs/pipelines/<stamp>_<name>/pipeline.json`` as soon as it exists,
so an interrupted pipeline still documents what was established.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import arena as arena_mod, atlas, gates, league, packs, paths, training, util

OFFICIAL_EVAL_GLOB = "*_walk_eval_s{seed}"


def _official_isaac_eval(seed: int, on_line, candidate: dict | None = None) -> dict | None:
    """Reuse only complete, version/configuration-matched official evidence."""
    candidates = sorted((paths.TRAINING / "runs").glob(OFFICIAL_EVAL_GLOB.format(seed=seed)), reverse=True)
    for run in candidates:
        results = util.read_json(run / "results.json") or {}
        comparison = gates.gate_isaac(candidate, results, baseline_hash=training.OFFICIAL_WALK_SHA256)
        if comparison["status"] in ("PASS", "FAIL") and results.get("seed") == seed:
            return {"results": results, "run_dir": str(run), "reused": True}
    report = training.evaluate_walk(str(training.OFFICIAL_WALK), seed, on_line=on_line)
    return {"results": report.get("results"), "run_dir": report.get("run_dir"), "reused": False}


def _stress(target: str, worlds: int, seconds: float, push: float, seed: int, tag: str, on_line) -> dict | None:
    command = [str(paths.INTERPRETERS["mjlab"]), "-B", str(paths.FORGE / "sim/mjwarp_eval.py"), "--policy", target,
               "--worlds", str(worlds), "--seconds", str(seconds), "--push-force", str(push), "--seed", str(seed),
               "--tag", util.safe_name(tag, 40)]
    process = subprocess.run(command, capture_output=True, text=True)
    result = None
    for line in process.stdout.splitlines():
        if on_line:
            on_line(line + "\n")
        if line.startswith("RESULT "):
            result = util.read_json(Path(line.split(" ", 1)[1]))
    if on_line:
        on_line(process.stderr[-3000:])
    if process.returncode != 0 or not isinstance(result, dict) or result.get("status") != "COMPLETED":
        return None
    try:
        gates._mj_summary(result)
    except (gates.EvidenceError, KeyError, TypeError, AttributeError) as exc:
        if on_line:
            on_line(f"[stress] 无效评测证据: {exc}\n")
        return None
    return result


def _walk_file(pack: dict) -> str:
    if pack["kind"] == "baseline":
        return str(paths.BH_LOCAL / pack["components"]["walk"]["official_file"])
    return str(packs.pack_dir(pack["id"]) / pack["components"]["walk"]["file"])


def run(checkpoint: str, name: str, seed: int = 2027, worlds: int = 2048, seconds: float = 20.0, push_force: float = 60.0,
        rounds: int = 2, match_seconds: int = 120, on_line=print) -> dict:
    directory = paths.RUNS / "pipelines" / f"{util.stamp()}_{util.safe_name(name, 32)}"
    directory.mkdir(parents=True)
    record = {"schema": "forge.pipeline/1", "checkpoint": str(Path(checkpoint).resolve()), "name": name,
              "parameters": {"seed": seed, "worlds": worlds, "seconds": seconds, "push_force": push_force,
                             "rounds": rounds, "match_seconds": match_seconds}, "steps": {}, "started_at": util.now_iso()}

    def step(key, value):
        record["steps"][key] = value
        util.write_json(directory / "pipeline.json", record)
        if on_line:
            on_line(f"[pipeline] {key}: {value if isinstance(value, str) else value.get('status', 'done')}\n")

    pack = training.export_pack(checkpoint, name, f"由流水线从 {Path(checkpoint).name} 导出", on_line=None)
    step("export_pack", {"status": "PASS", "pack_id": pack["id"], "tri_check": pack["provenance"]["tri_check"]["verdict"]})
    baseline = packs.load(packs.BASELINE_ID)

    isaac_candidate = training.evaluate_walk(checkpoint, seed, on_line=None)
    step("isaac_candidate", {"status": isaac_candidate["status"], "run_dir": isaac_candidate.get("run_dir")})
    isaac_baseline = _official_isaac_eval(seed, None, isaac_candidate.get("results"))
    step("isaac_baseline", {"status": "PASS" if isaac_baseline and isaac_baseline["results"] else "FAIL",
                            "run_dir": isaac_baseline and isaac_baseline["run_dir"], "reused": isaac_baseline and isaac_baseline["reused"]})

    mj_candidate = _stress(_walk_file(pack), worlds, seconds, push_force, seed, f"{pack['id']}-p{int(push_force)}", None)
    step("mjwarp_candidate", {"status": "PASS" if mj_candidate else "FAIL", "run": mj_candidate and mj_candidate.get("run"),
                              "fall_rate": mj_candidate and mj_candidate["metrics"]["fall_rate"]})
    mj_baseline = _stress(_walk_file(baseline), worlds, seconds, push_force, seed, f"official-p{int(push_force)}", None)
    step("mjwarp_baseline", {"status": "PASS" if mj_baseline else "FAIL", "run": mj_baseline and mj_baseline.get("run"),
                             "fall_rate": mj_baseline and mj_baseline["metrics"]["fall_rate"]})

    try:
        fragility = atlas.run([packs.BASELINE_ID, pack["id"]], seed=seed, tag=f"pipeline-{pack['id']}", on_line=None)
        comparison = fragility["comparisons"][0]
        step("atlas", {"status": "PASS", "run": fragility["run"], "verdict": comparison["verdict"],
                       "better_axes": comparison["better_axes"], "worse_axes": comparison["worse_axes"]})
        atlas_run = fragility["run"]
    except atlas.AtlasError as exc:
        step("atlas", {"status": "FAIL", "error": str(exc)})
        atlas_run = None

    series = league.run_series(arena_mod.Arena("main"), pack["id"], packs.BASELINE_ID, rounds, match_seconds,
                               on_line=lambda line: on_line(line) if on_line and line.startswith("[series]") else None)
    step("simrobot_series", {"status": series["status"], "dir": series.get("dir"), "record": series["record"]})

    report = gates.assess(pack["id"], isaac_candidate.get("results"), isaac_baseline and isaac_baseline["results"],
                          mj_candidate, mj_baseline, series, atlas_run=atlas_run)
    step("gate", {"status": report["verdict"], "path": report["path"],
                  "gates": {k: v["status"] for k, v in report["gates"].items()}})
    record["ended_at"] = util.now_iso()
    record["verdict"] = report["verdict"]
    record["pack_id"] = pack["id"]
    util.write_json(directory / "pipeline.json", record)
    record["dir"] = str(directory)
    return record
