"""SimRobot experiment contracts; temporary state and disposable CPU children only."""
import copy
import math
import os
import signal
import sys
import time

import pytest

from forge import arena, jobs, match, packs, paths, runtime, scenarios, strategies, util, validation


@pytest.fixture
def state(tmp_path, monkeypatch):
    for key, relative in {"PACKS": "packs", "STRATEGIES": "strategies", "ARENAS": "arena", "RUNS": "runs",
                          "STATE": "run", "DB_PATH": "forge.db", "VARIANTS": "variants", "BH_SIM_LOCK": ".sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    util.write_json(paths.ARENAS / "main/arena.json", {"source": str(paths.BH_LOCAL)})
    return tmp_path


def profile():
    return strategies.create("search-test", strategies.PRESETS["earlier-ball-search"]["cfg_patches"])


@pytest.mark.parametrize("patches", [
    {"walkingEngine.cfg": {"x": "1"}},
    {"behaviorParameters.cfg": {"ballSearchThresholdTeam": "30001"}},
    {"behaviorParameters.cfg": {"ballSearchThresholdTeam": "1; other = 0"}},
    {"behaviorParameters.cfg": {"ballSearchThresholdTeam": 100}},
    {"behaviorParameters.cfg": {"unknown": "100"}},
])
def test_strategy_scope_is_behavior_only(state, patches):
    with pytest.raises(ValueError):
        strategies.create("invalid", patches)
    assert not paths.STRATEGIES.exists()


def test_strategy_identity_detects_manifest_tampering(state):
    first = profile()
    assert profile()["id"] == first["id"]
    changed = copy.deepcopy(first)
    changed["cfg_patches"]["behaviorParameters.cfg"]["ballSearchThresholdTeam"] = "4000"
    util.write_json(strategies.directory(first["id"]) / "strategy.json", changed)
    with pytest.raises(ValueError, match="哈希"):
        strategies.load(first["id"])


def test_compose_changes_behavior_and_preserves_official_networks(state):
    strategy = profile()
    combined = strategies.compose(packs.BASELINE_ID, strategy["id"])
    assert combined["components"] == {}
    assert combined["modules"] == {}
    assert packs.effective_patches(combined) == strategy["cfg_patches"]
    assert combined["provenance"]["composition"]["motion_pack_id"] == packs.BASELINE_ID
    assert packs.verify(combined["id"])["status"] == "PASS"
    changed = copy.deepcopy(combined)
    changed["cfg_patches"]["behaviorParameters.cfg"]["ballSearchThresholdTeam"] = "4000"
    util.write_json(packs.pack_dir(combined["id"]) / "pack.json", changed)
    assert packs.verify(combined["id"])["status"] == "FAIL"


def test_strategy_plan_balances_jersey_and_kickoff(state):
    planned = validation.plan("strategy", strategy_id=profile()["id"], repetitions=2)
    assert planned["case_count"] == 8 and planned["simulation_seconds"] == 960
    for repeat in (1, 2):
        assert {(c["candidate_team"], c["kickoff_team"]) for c in planned["cases"] if c["repeat"] == repeat} == {
            (5, 5), (5, 70), (70, 5), (70, 70)}
    assert planned["motion_pack"] == packs.BASELINE_ID and not planned["robot_connected"]


def test_motion_plan_is_one_variable_and_counterbalances_order(state):
    planned = validation.plan("motion", repetitions=2)
    assert [c["role"] for c in planned["cases"]] == ["baseline", "candidate", "candidate", "baseline"]
    assert all(c["seconds"] == 30 for c in planned["cases"])
    with pytest.raises(ValueError, match="官方策略"):
        validation.plan("motion", strategy_id=profile()["id"])
    mixed = strategies.compose(packs.BASELINE_ID, profile()["id"])
    with pytest.raises(ValueError, match="非运控"):
        validation.plan("motion", motion_pack=mixed["id"])


def test_module_candidate_requires_a_matching_program_before_launch(state):
    candidate = packs.create("code-test", {}, modules={"ForgeWalkingEngine": {
        "replaces": "WalkingEngine", "cfg": "forgeWalkingEngine.cfg", "params": {"actionFilterAlpha": "0.3"}}})
    with pytest.raises(ValueError, match="不包含候选模块"):
        validation.plan("motion", motion_pack=candidate["id"], source_arena="main")
    assert not (paths.RUNS / "validations").exists()


def test_runtime_parameter_readback_requires_actual_values(tmp_path):
    output = tmp_path / "parameters.cfg"
    expected = [{"robot": "robot5", "output": str(output), "values": {"timeout": "1500", "angle": "180deg"}}]
    assert strategies.verify_runtime(expected)["ok"] is False
    output.write_text("timeout = 2000; angle = 3.14159;\n")
    assert strategies.verify_runtime(expected)["files"][0]["mismatches"] == ["timeout"]
    output.write_text("timeout = 1500; angle = 3.14159;\n")
    report = strategies.verify_runtime(expected)
    assert report["ok"] and report["files"][0]["actual"]["timeout"] == "1500"
    assert strategies.verify_runtime([])["ok"] is False


def test_fixed_command_metrics_use_robot_frame_and_unwrap_angles():
    samples = [[1000, 0, 0, math.pi / 2], [5000, 0, 2000, math.pi / 2],
               [8000, -1000, 2000, math.pi / 2], [10000, -1000, 2000, 3.0],
               [12000, -1000, 2000, -3.0], [13000, -1000, 2000, -3.0], [15000, -1000, 2000, -3.0]]
    metrics = scenarios.motion_metrics(samples)
    assert metrics["forward"]["forward_m"] == pytest.approx(2)
    assert metrics["left"]["left_m"] == pytest.approx(1)
    assert metrics["turn"]["yaw_change_rad"] == pytest.approx(2 * math.pi - 3 - math.pi / 2)
    result = {"robots": {"robot5": {"trajectory": samples, "fall_frames": 0, "getup_frames": 0}}}
    commands = [{"tick": t, "text": c} for t, c in scenarios.motion_plan()]
    assert all(scenarios.motion_checks(result, commands).values())
    assert scenarios.motion_checks(result, commands[:-1])["all_motion_commands_dispatched"] is False
    line = f"AUDIT command tick=1000 text={scenarios.motion_plan()[2][1]}"
    assert match.parse_audit([line])["command"][0]["text"] == scenarios.motion_plan()[2][1]


def motion_result(forward=5):
    return {"status": "PASS", "checks": {key: True for key in (
        "process_exit_zero", "completed_requested_steps", "runtime_network_readback", "runtime_behavior_parameters", "no_console_errors")},
        "motion_segments": {"forward": {"forward_m": forward}, "left": {"left_m": 2},
                            "turn": {"yaw_change_rad": 4}, "settled_stop": {"net_displacement_m": 0.001}}}


def test_motion_verdict_separates_performance_from_missing_evidence():
    rows = [{"case": {"role": "baseline"}, "result": motion_result()},
            {"case": {"role": "candidate"}, "result": motion_result(3.4)}]
    assert validation._motion_comparison(rows, 1)["verdict"] == "REGRESSION_OBSERVED"
    rows[1]["result"] = motion_result()
    assert validation._motion_comparison(rows, 1)["verdict"] == "NO_REGRESSION_OBSERVED"
    rows[1]["result"]["checks"]["runtime_behavior_parameters"] = False
    assert validation._motion_comparison(rows, 1)["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert validation._motion_comparison(rows[:1], 1)["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_strategy_aggregation_follows_candidate_across_teams():
    def stats(goals, against):
        return {"goals": goals, "goals_against": against, "ball_contacts": 10, "fall_episodes_sampled": 0,
                "ball_seen_samples": 20, "skill_samples": {s: 1 for s in scenarios.SKILLS}}
    rows = [{"case": {"id": str(i), "candidate_team": team, "kickoff_team": kickoff},
             "result": {"status": "PASS", "teams": {str(team): stats(1, 0), str(75 - team): stats(0, 1)}}}
            for i, (team, kickoff) in enumerate(((5, 5), (70, 5), (70, 70), (5, 70)))]
    report = validation._strategy_comparison(rows, 4)
    assert report["record"] == {"win": 4, "draw": 0, "loss": 0}
    assert report["totals"]["candidate"]["goals"] == 4
    assert report["verdict"] == "READY_FOR_REVIEW"
    rows[0]["result"]["status"] = "FAIL"
    assert validation._strategy_comparison(rows, 4)["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_silent_process_is_timed_out_and_reaped(tmp_path):
    start = time.monotonic()
    result = runtime.stream_process([sys.executable, "-c", "import time; time.sleep(20)"],
                                    cwd=tmp_path, env=dict(os.environ), directory=tmp_path, timeout=0.25)
    assert result["timed_out"] and result["exit_code"] == 124 and time.monotonic() - start < 5
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid.txt").read_text()), 0)


def test_stream_process_retains_unterminated_output(tmp_path):
    lines = []
    result = runtime.stream_process([sys.executable, "-c", "print('first'); print('last', end='')"],
                                    cwd=tmp_path, env=dict(os.environ), directory=tmp_path, timeout=5, on_line=lines.append)
    assert result["exit_code"] == 0 and not result["timed_out"]
    assert lines == ["first\n", "last"] and (tmp_path / "console.log").read_text() == "first\nlast"


def test_cancel_flushes_interrupted_validation_and_restores_signal(state, monkeypatch):
    monkeypatch.setattr(arena.Arena, "materialize", lambda self: os.kill(os.getpid(), signal.SIGTERM))
    handler = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt, match="SIGTERM"):
        validation.run("motion")
    report = util.read_json(next((paths.RUNS / "validations").glob("*/validation.json")))
    assert report["status"] == "INTERRUPTED" and report["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert signal.getsignal(signal.SIGTERM) == handler


def test_arena_refresh_and_reselection_retain_prior_configuration(state):
    a = arena.Arena("preserved")
    a.materialize()
    a.flash(5, packs.BASELINE_ID)
    before = util.read_json(a.flash_dir / "T5.json")
    config = (a.config / "Scenarios/Forge_T5/K1/walkingEngine.cfg").read_bytes()
    a.flash(5, packs.BASELINE_ID)
    saved = next((paths.RUNS / "flash-history").iterdir())
    assert (saved / "scenario/K1/walkingEngine.cfg").read_bytes() == config
    assert util.read_json(saved / "receipt.json") == before
    a.materialize(refresh=True)
    archived = next((paths.RUNS / "arena-archives").iterdir())
    assert (archived / "Config/Scenarios/Forge_T5/K1/walkingEngine.cfg").read_bytes() == config


def test_validation_job_uses_simulator_resources_and_explicit_arguments(state, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":test")
    argv, resources = jobs._build_validation({"mode": "strategy", "motion_pack": packs.BASELINE_ID,
                                             "strategy_id": strategies.BASELINE_ID, "source_arena": "codelab", "record": False})
    assert resources == {"arena", "simlock", "display", "gpu"}
    assert argv[:2] == ["validate", "strategy"] and "--no-record" in argv
    assert argv[argv.index("--arena") + 1] == "codelab"


def test_http_validation_is_authenticated_and_bad_plans_are_rejected(state):
    from fastapi.testclient import TestClient
    from forge import server

    app = server.create_app(start_jobs=False)
    with TestClient(app, base_url="http://127.0.0.1:8920") as client:
        assert client.get("/api/validations").status_code == 401
        client.headers.update({"X-Forge-Token": app.state.token})
        created = client.post("/api/strategies", json={"preset": "earlier-ball-search"})
        assert created.status_code == 200
        planned = client.post("/api/validations/preview", json={"mode": "strategy", "strategy_id": created.json()["id"]})
        assert planned.status_code == 200 and planned.json()["case_count"] == 4
        assert client.post("/api/validations/preview", json={"mode": "motion", "motion_pack": "missing"}).status_code == 400
        assert client.post("/api/strategies", json={"cfg_patches": {"threads.cfg": {"x": "1"}}}).status_code == 400
        assert client.get("/api/validations/missing").status_code == 404
    with pytest.raises(ValueError):
        validation.load_run("../escape")
