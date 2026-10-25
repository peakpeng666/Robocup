"""Regression tests for evidence, resource ownership, shutdown and capture retention.

All state is temporary. Child processes are disposable test sleepers; no simulator,
training runtime, GPU job, build, or robot is launched.
"""
import copy
import fcntl
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge import arena, gates, jobs, league, locking, match, packs, paths, pipeline, training, util


@pytest.fixture
def state(tmp_path, monkeypatch):
    for key, relative in {"PACKS": "packs", "ARENAS": "arena", "RUNS": "runs", "STATE": "run",
                          "DB_PATH": "forge.db", "VARIANTS": "variants", "BH_SIM_LOCK": ".bhuman-sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    return tmp_path


def isaac(policy="a" * 64):
    return {"policy_sha256": policy, "evaluator_sha256": "e" * 64, "source_sha256": "f" * 64,
            "finite_checks_pass": True, "seed": 2027, "num_envs": 8, "seg_steps": 100,
            "planned_steps": 200, "executed_steps": 200, "zero_command_mode": "hold",
            "schedule": ["still", "forward"], "termination_events_total": {"non_timeout_reset": 0},
            "segments": {name: {"steps": 100, "command_vx_vy_wz": command,
                                 "tracking_rmse_settled_vx_vy_wz": [0.1, 0.2, 0.3],
                                 "termination_events": {"non_timeout_reset": 0}}
                         for name, command in (("still", [0, 0, 0]), ("forward", [1, 0, 0]))}}


def mj(policy="b" * 64, falls=40):
    return {"status": "COMPLETED", "policy_sha256": policy, "evaluator_sha256": "e" * 64,
            "setup": {"worlds": 1000, "seconds": 20.0, "seed": 2027, "schedule": False, "command_period_s": 4.0,
                      "vx": [-0.4, 1.0], "vy": [-0.3, 0.3], "wz": [-0.8, 0.8], "stand_probability": 0.15,
                      "push_force_max_N": 60.0, "push_interval_s": 3.0, "push_duration_s": 0.1,
                      "init_noise_rad": 0.02, "nconmax": 64, "njmax": 256},
            "model": {"xml_sha256": "c" * 64, "config_sha256": "d" * 64, "physics_dt_s": 0.002, "policy_dt_s": 0.02},
            "engine": {"mujoco": "3.11.0", "mujoco_warp": "3.11.0", "warp": "1.18.0", "torch": "2.14.1",
                       "device": "test", "cuda_graph": True},
            "metrics": {"falls": falls, "nonfinite_worlds": 0, "tracking_samples": 30000,
                        "tracking_rmse": {"vx": 0.1, "vy": 0.2, "wz": 0.3}},
            "performance": {"physics_steps": 10000000}}


def series(candidate="candidate", baseline="bhuman-official"):
    rounds = []
    for index, pair in enumerate(((candidate, baseline), (baseline, candidate)), 1):
        rounds.append({"round": index, "status": "PASS", "failed_checks": [],
                       "assignment": dict(zip(("5", "70"), pair)),
                       "teams": {t: {"pack_id": p, "goals": 0, "fall_episodes_sampled": 0}
                                 for t, p in zip(("5", "70"), pair)}})
    return league._aggregate(candidate, baseline, rounds, 120, 2, completed=True)


def test_valid_comparisons_and_real_regressions():
    assert gates.gate_isaac(isaac(), isaac())["status"] == "PASS"
    degraded = isaac()
    degraded["segments"]["forward"]["tracking_rmse_settled_vx_vy_wz"][0] = 0.3
    assert gates.gate_isaac(degraded, isaac())["status"] == "FAIL"
    assert gates.gate_mjwarp(mj(falls=42), mj())["status"] == "PASS"
    assert gates.gate_mjwarp(mj(falls=80), mj())["status"] == "FAIL"
    degraded = mj()
    degraded["metrics"]["tracking_rmse"]["wz"] = 1.0
    assert gates.gate_mjwarp(degraded, mj())["status"] == "FAIL"
    assert gates.gate_series(series(), "candidate", "bhuman-official")["status"] == "PASS"


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(segments={}),
    lambda r: r.pop("evaluator_sha256"),
    lambda r: r.update(executed_steps=100),
    lambda r: r.update(finite_checks_pass=False),
    lambda r: r.update(num_envs=0),
    lambda r: r.update(seed=True),
    lambda r: r["segments"]["forward"].update(tracking_rmse_settled_vx_vy_wz=[float("nan"), 0, 0]),
    lambda r: r["segments"]["forward"].update(tracking_rmse_settled_vx_vy_wz=[-1, 0, 0]),
    lambda r: r["segments"]["forward"].update(command_vx_vy_wz=[0, 0, 0]),
    lambda r: r["segments"]["forward"].update(steps=99),
    lambda r: r["termination_events_total"].update(non_timeout_reset=1),
])
def test_incomplete_isaac_evidence_never_passes_even_against_itself(mutate):
    result = isaac()
    mutate(result)
    assert gates.gate_isaac(result, copy.deepcopy(result))["status"] == "INSUFFICIENT"


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(status="FAILED"),
    lambda r: r.pop("evaluator_sha256"),
    lambda r: r["setup"].update(worlds=0),
    lambda r: r["metrics"].update(falls=-1),
    lambda r: r["metrics"].update(falls=1001),
    lambda r: r["metrics"].update(tracking_samples=0),
    lambda r: r["metrics"].pop("tracking_samples"),
    lambda r: r["metrics"].update(tracking_rmse={}),
    lambda r: r["metrics"]["tracking_rmse"].update(vx=float("inf")),
    lambda r: r["metrics"].update(nonfinite_worlds=1),
    lambda r: r["performance"].update(physics_steps=1),
])
def test_incomplete_mujoco_evidence_never_passes_even_against_itself(mutate):
    result = mj()
    mutate(result)
    assert gates.gate_mjwarp(result, copy.deepcopy(result))["status"] == "INSUFFICIENT"


@pytest.mark.parametrize("field,value", [("seed", 42), ("num_envs", 4), ("source_sha256", "1" * 64),
                                         ("evaluator_sha256", "2" * 64), ("zero_command_mode", "different")])
def test_isaac_mismatched_conditions_are_not_comparable(field, value):
    other = isaac()
    other[field] = value
    assert gates.gate_isaac(isaac(), other)["status"] == "INSUFFICIENT"


def test_other_policies_and_models_cannot_supply_promotion_evidence():
    assert gates.gate_isaac(isaac(), isaac(), candidate_hash="9" * 64)["status"] == "INSUFFICIENT"
    assert gates.gate_mjwarp(mj(), mj(), candidate_hash="9" * 64)["status"] == "INSUFFICIENT"
    other = mj()
    other["model"]["xml_sha256"] = "9" * 64
    assert gates.gate_mjwarp(mj(), other)["status"] == "INSUFFICIENT"


def test_series_needs_completion_swapped_sides_and_consistent_totals():
    complete = series()
    partial = league._aggregate("candidate", "bhuman-official", complete["rounds"][:1], 120, 2)
    assert partial["status"] == "INCOMPLETE" and not partial["completed"]
    partial["status"] = "PASS"  # A label cannot override incomplete evidence.
    assert gates.gate_series(partial, "candidate", "bhuman-official")["status"] == "INSUFFICIENT"
    for mutate in (lambda r: r.pop("requested_rounds"),
                   lambda r: r["rounds"][1].update(assignment=r["rounds"][0]["assignment"]),
                   lambda r: r["totals"]["candidate"].update(fall_episodes_sampled=1),
                   lambda r: r["rounds"][0]["teams"]["5"].pop("fall_episodes_sampled")):
        result = copy.deepcopy(complete)
        mutate(result)
        assert gates.gate_series(result, "candidate", "bhuman-official")["status"] == "INSUFFICIENT"


def test_interrupted_series_persists_incomplete_progress(state, monkeypatch):
    monkeypatch.setattr(packs, "load", lambda identifier: {"id": identifier})
    rounds = series()["rounds"]
    calls = []

    def simulated_match(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError("test interruption before second result")
        return {"status": "PASS", "score": {"5": 0, "70": 0}, "teams": rounds[0]["teams"],
                "checks": {"runtime": True}}

    monkeypatch.setattr(match, "run_match", simulated_match)
    with pytest.raises(RuntimeError, match="test interruption"):
        league.run_series(SimpleNamespace(flash=lambda *args: None), "candidate", "bhuman-official", rounds=2)
    saved = util.read_json(next(paths.RUNS.glob("series/*/series.json")))
    assert saved["status"] == "INCOMPLETE" and saved["requested_rounds"] == 2
    assert saved["rounds_played"] == 1 and not saved["completed"]


def test_controller_rebuild_invalidates_arena_even_when_executable_is_unchanged(state):
    source = state / "fake-source"
    (source / "Config").mkdir(parents=True)
    target = arena.Arena("test", source=source)
    target.binary.parent.mkdir(parents=True)
    target.binary.write_bytes(b"unchanged-executable-fixture")
    controller = target.binary.parent / "libSimulatedRobot.so"
    controller.write_bytes(b"controller-v1")
    util.write_json(target.state_path, {"source_manifest_sha256": util.manifest_digest({}),
                                       "binary_sha256": util.sha256_file(target.binary),
                                       "controller_sha256": util.sha256_file(controller)})
    assert target.freshness()["status"] == "FRESH"
    controller.write_bytes(b"controller-v2")
    result = target.freshness()
    assert result["status"] == "STALE" and result["controller_changed"] and not result["binary_changed"]


def atlas_run(directory, labels, digest, thresholds=None, replicas=24):
    """Synthetic one-axis fragility sweep on a shared world table (see tests/test_atlas.py)."""
    import numpy as np

    directory.mkdir(parents=True)
    levels = [0, 2, 4, 6, 8, 10, 12, 14]
    rows = {"axis": [], "level_index": [], "level": [], "replica": [], "direction_rad": [], "command_index": [], "sign": []}
    for li, level in enumerate(levels):
        for r in range(replicas):
            for key, value in (("axis", "push"), ("level_index", li), ("level", float(level)), ("replica", r),
                               ("direction_rad", 0.0), ("command_index", 0), ("sign", 1.0)):
                rows[key].append(value)
    n = len(rows["axis"])
    design = {"schema": "forge.atlas-design/1", "seed": 1, "axes": ["push"], "worlds": n, "rows": rows,
              "axis_specs": {"push": {"label": "push", "unit": "N·s", "levels": levels, "failure": "fall", "margin": "value"}},
              "timeline": {"seconds": 8.0, "command_at_s": 1.0, "push_at_s": 3.0, "push_duration_s": 0.1},
              "commands": [["stand", [0, 0, 0]]]}
    util.write_json(directory / "design.json", design)
    jitter = np.random.default_rng(3).normal(0, 1.0, n)
    policies = {}
    for label in labels:
        threshold = (thresholds or {}).get(label, 7.0)
        fell = (np.asarray(rows["level"]) + jitter > threshold).astype(int).tolist()
        policies[label] = {"fell": fell, "nonfinite": 0, "policy": "x.onnx", "policy_sha256": digest,
                           "linear_progress_m": [0.0] * n, "expected_linear_m": [0.0] * n,
                           "yaw_progress_rad": [0.0] * n, "expected_yaw_rad": [0.0] * n,
                           "track_sq": [[0.0, 0.0, 0.0]] * n, "track_n": [0] * n, "push_phase": [None] * n}
    util.write_json(directory / "raw.json", {"schema": "forge.atlas-raw/1", "status": "COMPLETED", "parity_mode": False,
                                            "evaluator_sha256": "e" * 64, "policies": policies,
                                            "design_sha256": util.sha256_file(directory / "design.json")})
    return directory


def test_assess_binds_pack_identity_and_saves_replayable_evidence(state, monkeypatch):
    from forge import atlas

    monkeypatch.setattr(atlas, "REQUIRED_AXES", ("push",))
    official = packs.ensure_baseline()
    onnx = paths.BH_LOCAL / official["components"]["walk"]["official_file"]
    digest = util.sha256_file(onnx)
    tri = {"verdict": "PASS", "results": {case: {"eager_vs_script_maxabs": 0.0, "eager_vs_ort_maxabs": 0.0,
                                                "eager_vs_script_ok": True, "eager_vs_ort_ok": True}
                                         for case in ("random_batch1", "random_batch4")}}
    provenance = {"checkpoint_sha256": "a" * 64, "tri_check": tri,
                  "export_manifest": {"checkpoint_sha256": "a" * 64, "onnx": {"sha256": digest}, "tri_check": tri}}
    candidate = packs.create("verified-fixture", {"walk": str(onnx)}, provenance=provenance)
    fragility = atlas_run(state / "atlas-ok", [candidate["id"], packs.BASELINE_ID], digest)
    missing = gates.assess(candidate["id"], isaac(), isaac(training.OFFICIAL_WALK_SHA256), mj(digest), mj(digest),
                           series(candidate["id"]))
    assert missing["gates"]["G2F_fragility"]["status"] == "INSUFFICIENT" and missing["verdict"] == "INSUFFICIENT_EVIDENCE"
    report = gates.assess(candidate["id"], isaac(), isaac(training.OFFICIAL_WALK_SHA256), mj(digest), mj(digest),
                          series(candidate["id"]), atlas_run=fragility)
    assert report["verdict"] == "SIM_QUALIFIED" and report["gates"]["G2F_fragility"]["status"] == "PASS"
    weaker = atlas_run(state / "atlas-weak", [candidate["id"], packs.BASELINE_ID], digest,
                       thresholds={candidate["id"]: 3.0, packs.BASELINE_ID: 8.0})
    failed = gates.assess(candidate["id"], isaac(), isaac(training.OFFICIAL_WALK_SHA256), mj(digest), mj(digest),
                          series(candidate["id"]), atlas_run=weaker)
    assert failed["gates"]["G2F_fragility"]["status"] == "FAIL" and failed["verdict"] == "NOT_QUALIFIED"
    foreign = atlas_run(state / "atlas-foreign", [candidate["id"], packs.BASELINE_ID], "9" * 64)
    assert gates.gate_fragility(foreign, candidate["id"], packs.BASELINE_ID, candidate_hash=digest,
                                baseline_hash=digest)["status"] == "INSUFFICIENT"
    saved = json.loads(Path(report["path"]).read_text())
    assert saved["rule_version"] == gates.RULE_VERSION
    assert util.sha256_bytes(saved["evidence"]["canonical_json"].encode()) == saved["evidence"]["sha256"]
    assert json.loads(saved["evidence"]["canonical_json"])["candidate_pack"]["id"] == candidate["id"]
    unrelated = gates.assess(candidate["id"], isaac("7" * 64), isaac(training.OFFICIAL_WALK_SHA256),
                             mj(digest), mj(digest), series(candidate["id"]), atlas_run=fragility)
    assert unrelated["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert unrelated["path"] != report["path"] and Path(report["path"]).read_text() == json.dumps(saved, ensure_ascii=False, indent=2) + "\n"


@pytest.fixture
def manager(state, monkeypatch):
    monkeypatch.setattr(jobs.JobManager, "_external_busy", lambda self: set())
    manager = jobs.JobManager(db_path=paths.DB_PATH, autostart=False)
    yield manager
    manager.shutdown()


def test_match_flash_and_http_reservation_share_resources(manager, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":test")
    for kind, params in (("match", {"vision": "cpu"}), ("flash", {"pack_id": "x", "team": 5})):
        assert {"arena", "simlock"} <= set(manager.preview(kind, params)["resources"])
    job_id = manager.submit("flash", {"pack_id": "x", "team": 5})
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("conflicting job started"))
    with manager.reserve({"arena", "simlock"}):
        manager._schedule()
        assert manager.get(job_id)["status"] == "queued"
        with pytest.raises(jobs.JobError):
            with manager.reserve({"arena"}):
                pass
    assert manager._held == {}


def test_stale_queue_snapshot_cannot_resurrect_cancelled_job(manager, monkeypatch):
    job_id = manager.submit("flash", {"pack_id": "x", "team": 5})
    stale = manager.get(job_id)
    manager.cancel(job_id)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("cancelled job started"))
    manager._start(stale)
    assert manager.get(job_id)["status"] == "cancelled"


def test_shutdown_stops_owned_process_tree_and_marks_queue_interrupted(state, monkeypatch):
    import psutil

    marker = state / "child.pid"
    script = state / "owned.py"
    script.write_text("import signal, subprocess, sys, time\n"
                      "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], start_new_session=True)\n"
                      "def stop(*args):\n    child.wait(timeout=10)\n    sys.exit(0)\n"
                      "signal.signal(signal.SIGTERM, stop)\n"
                      f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
                      "time.sleep(120)\n")
    monkeypatch.setattr(jobs, "FORGE_CLI", [])
    monkeypatch.setitem(jobs.JOB_TYPES, "probe", {"builder": lambda p: ([sys.executable, str(script)], {"arena"})})
    monkeypatch.setattr(jobs.JobManager, "_external_busy", lambda self: set())
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    manager = jobs.JobManager(db_path=paths.DB_PATH)
    child_pid = None
    try:
        running = manager.submit("probe", {})
        queued = manager.submit("probe", {})
        deadline = time.monotonic() + 5
        while not (marker.is_file() and marker.read_text()) and time.monotonic() < deadline:
            time.sleep(0.02)
        child_pid = int(marker.read_text())
        manager.shutdown()
        assert manager.get(running)["status"] == manager.get(queued)["status"] == "interrupted"
        assert not manager._procs and not manager._held and not manager._thread.is_alive()
        assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None
        with pytest.raises(jobs.JobError):
            manager.submit("probe", {})
    finally:
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait(timeout=5)
        if child_pid and psutil.pid_exists(child_pid):
            try:
                psutil.Process(child_pid).kill()
            except psutil.NoSuchProcess:
                pass


def test_simulation_lock_blocks_other_threads_and_external_launchers(state):
    outcomes = []

    def compete():
        try:
            with locking.simulation_lock():
                outcomes.append("entered")
        except RuntimeError:
            outcomes.append("busy")

    with locking.simulation_lock():
        with locking.simulation_lock():
            worker = threading.Thread(target=compete)
            worker.start()
            worker.join(timeout=2)
    assert outcomes == ["busy"]
    with paths.BH_SIM_LOCK.open("a") as external:
        fcntl.flock(external, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(arena.ArenaError, match="共享"):
            arena.Arena().flash(5, "anything")
    with locking.simulation_lock():
        pass


@pytest.mark.parametrize("encode_exit", [0, 1])
def test_recording_retains_and_hashes_source_frames_on_success_or_failure(state, monkeypatch, encode_exit):
    directory = state / "recorded"
    (directory / "frames").mkdir(parents=True)
    frame = directory / "frames/frame-000001.jpg"
    frame.write_bytes(b"original-capture-fixture")
    original = frame.read_bytes()

    def encode(command, **kwargs):
        if encode_exit == 0:
            Path(command[-1]).write_bytes(b"encoded-viewing-copy")
        return SimpleNamespace(returncode=encode_exit)

    monkeypatch.setattr(subprocess, "run", encode)
    result = match.encode_recording(directory, 1)
    assert result["encoded"] is (encode_exit == 0)
    assert frame.read_bytes() == original and result["source_frames_retained"]
    assert util.read_json(directory / "frames-manifest.json")["sha256"][frame.name] == util.sha256_file(frame)
    # A gap in numbered frames is incomplete even if the count matches.
    frame.rename(frame.with_name("frame-000002.jpg"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("incomplete capture encoded"))
    assert not match.encode_recording(directory, 1)["complete"]


def test_pipeline_rejects_result_from_failed_evaluator_and_skips_stale_baseline(state, monkeypatch):
    evidence = state / "mj.json"
    util.write_json(evidence, mj())
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=f"RESULT {evidence}\n", stderr="failed"))
    assert pipeline._stress("fixture", 1, 20, 60, 2027, "test", None) is None
    training_root = state / "training"
    monkeypatch.setattr(paths, "TRAINING", training_root)
    old = isaac(training.OFFICIAL_WALK_SHA256)
    old["num_envs"] = 4
    util.write_json(training_root / "runs/20991231_walk_eval_s2027/results.json", old)
    current = isaac(training.OFFICIAL_WALK_SHA256)
    util.write_json(training_root / "runs/20261022_walk_eval_s2027/results.json", current)
    monkeypatch.setattr(training, "evaluate_walk", lambda *a, **k: pytest.fail("compatible baseline was not reused"))
    reused = pipeline._official_isaac_eval(2027, None, isaac())
    assert reused["reused"] and reused["results"]["num_envs"] == 8


def test_http_mutations_reserve_arena_resources_and_honor_target(state, monkeypatch):
    from fastapi.testclient import TestClient
    from forge import server

    monkeypatch.setattr(jobs.JobManager, "_external_busy", lambda self: set())
    app = server.create_app(start_jobs=False)
    with TestClient(app, base_url="http://127.0.0.1:8920") as client:
        headers = {"X-Forge-Token": app.state.token}
        with app.state.manager.reserve({"arena"}):
            assert client.post("/api/flash", json={"team": 5, "pack_id": "fixture"}, headers=headers).status_code == 409
            assert client.post("/api/arena/init", json={"arena": "codelab"}, headers=headers).status_code == 409
        monkeypatch.setattr(arena.Arena, "materialize", lambda self, refresh=False: {"name": self.name, "refresh": refresh})
        util.write_json(paths.ARENAS / "codelab/arena.json", {"source": str(paths.BH_LOCAL)})
        response = client.post("/api/arena/init", json={"arena": "codelab", "refresh": True}, headers=headers)
        assert response.status_code == 200 and response.json() == {"name": "codelab", "refresh": True}
