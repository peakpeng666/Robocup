"""Behavioural tests of K1 Forge against the real B-Human tree (read-only) and temp state.

Run: ~/.venvs/forge/bin/python -m pytest -q forge/tests
Nothing here starts SimRobot, Isaac Gym or a build; Forge state goes to tmp directories.
"""
import json
from pathlib import Path

import pytest

from forge import arena as arena_mod, bhconfig, builds, contracts, jobs, match, packs, paths, util

BH_CONFIG = paths.BH_LOCAL / "Config"
OFFICIAL_WALK = paths.BH_LOCAL / "Config/NeuralNets/Walk/K1_walk.onnx"
OFFICIAL_KICK = paths.BH_LOCAL / "Config/NeuralNets/Walk/K1_kick_inner.onnx"


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PACKS", tmp_path / "packs")
    monkeypatch.setattr(paths, "ARENAS", tmp_path / "arena")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "STATE", tmp_path / "run")
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "forge.db")
    monkeypatch.setattr(paths, "VARIANTS", tmp_path / "variants")
    monkeypatch.setattr(paths, "BH_SIM_LOCK", tmp_path / ".bhuman-sim.lock")
    return tmp_path


# ------------------------------------------------------------------ configuration semantics

def test_every_bhuman_cfg_parses():
    files = sorted(BH_CONFIG.rglob("*.cfg"))
    assert len(files) > 150
    for path in files:
        bhconfig.CfgDocument.load(path)


def test_cfg_patch_is_format_preserving_and_strict():
    document = bhconfig.CfgDocument.load(BH_CONFIG / "Robots/SimulatedK1/walkingEngine.cfg")
    patched = document.patched({"walkNeuronalNetworkParameters.modelName": "forge/p/walk.onnx"})
    changed = [(a, b) for a, b in zip(document.text.splitlines(), patched.splitlines()) if a != b]
    assert changed == [("  modelName = K1_walk.onnx;", "  modelName = forge/p/walk.onnx;")]
    with pytest.raises(bhconfig.CfgError):
        document.patched({"walkNeuronalNetworkParameters.doesNotExist": "1"})
    # Expressions such as "xPosOwnGoalLine + 1000" are single scalars.
    behaviour = bhconfig.CfgDocument.load(BH_CONFIG / "Behavior/FreeKicks/opponentCornerKick.cfg")
    assert behaviour.get("preconditions.ballXLE") == "xPosOwnGoalLine + 1000"


def test_search_path_order_matches_settings_cpp():
    order = bhconfig.search_path(BH_CONFIG, "SimulatedK1", "K1", "MField", "Forge_T5")
    names = [p.relative_to(BH_CONFIG).as_posix() for p in order]
    assert names == ["Robots/SimulatedK1", "Locations/MField/K1", "Locations/MField", "Scenarios/Forge_T5/K1",
                     "Scenarios/Forge_T5", "Robots/Default/K1", "Robots/Default", "Locations/Default/K1",
                     "Locations/Default", "Scenarios/Default/K1", "Scenarios/Default", "."]
    resolved = bhconfig.resolve(BH_CONFIG, "walkingEngine.cfg", robot_name="SimulatedK1")
    assert resolved == BH_CONFIG / "Robots/SimulatedK1/walkingEngine.cfg"


# ------------------------------------------------------------------ contracts and packs

def test_official_networks_satisfy_contracts_and_slots_are_not_interchangeable():
    for slot, contract in contracts.CONTRACTS.items():
        if contract.official_file:
            assert contracts.check(slot, paths.BH_LOCAL / contract.official_file)["contract"] == contract.id
    with pytest.raises(contracts.ContractError):
        contracts.check("walk", OFFICIAL_KICK)


def test_pack_is_content_addressed_and_contract_checked(state):
    first = packs.create("demo", {"walk": str(OFFICIAL_WALK)})
    again = packs.create("demo", {"walk": str(OFFICIAL_WALK)})
    assert first["id"] == again["id"] and first["id"].startswith("demo-")
    assert packs.verify(first["id"])["status"] == "PASS"
    with pytest.raises(contracts.ContractError):
        packs.create("wrong-slot", {"walk": str(OFFICIAL_KICK)})
    with pytest.raises(packs.PackError):
        packs.create("not-flashable", {"getup": str(paths.BH_LOCAL / "Config/NeuralNets/GetUpEngine/K1.onnx")})
    stored = packs.pack_dir(first["id"]) / "files/walk.onnx"
    stored.write_bytes(stored.read_bytes()[:-1] + b"\0")
    assert packs.verify(first["id"])["status"] == "FAIL"


def test_baseline_pack_mirrors_official_release(state):
    baseline = packs.ensure_baseline()
    assert baseline["kind"] == "baseline"
    assert baseline["components"]["walk"]["sha256"] == util.sha256_file(paths.BH_OFFICIAL / "Config/NeuralNets/Walk/K1_walk.onnx")
    assert packs.effective_patches(baseline) == {}


# ------------------------------------------------------------------ arena flashing

@pytest.fixture()
def arena(state):
    a = arena_mod.Arena("test")
    a.materialize()
    return a


def test_baseline_flash_is_byte_identical_to_original_layout(arena):
    for team in arena_mod.TEAM_NUMBERS:
        arena.flash(team, packs.BASELINE_ID)
    report = arena.verify()
    assert report["status"] == "PASS", report["checks"]
    assert report["checks"]["T5_baseline_byte_identical"] and report["checks"]["T70_baseline_byte_identical"]
    assert not (arena.config / "Robots/SimulatedK1/walkingEngine.cfg").exists()


def test_candidate_flash_changes_only_declared_files(arena):
    candidate = packs.create("cand", {"walk": str(OFFICIAL_WALK)},
                             {"walkingEngine.cfg": {"configuredParameters.fastWalkSpeed.maxSpeed.translation.x": "2100"}})
    arena.flash(5, candidate["id"])
    arena.flash(70, packs.BASELINE_ID)
    report = arena.verify()
    assert report["status"] == "PASS", report["checks"]
    assert report["teams"]["5"]["differs"] == ["walkingEngine.cfg"]
    assert report["teams"]["5"]["networks"]["walk"]["model_name"] == f"forge/{candidate['id']}/walk.onnx"
    assert report["teams"]["70"]["differs"] == []


def test_tampering_and_stale_source_are_detected(arena):
    for team in arena_mod.TEAM_NUMBERS:
        arena.flash(team, packs.BASELINE_ID)
    target = arena.config / "Scenarios/Forge_T70/K1/motorParameters.cfg"
    target.write_text(target.read_text().replace("p = 80", "p = 81", 1))
    report = arena.verify()
    assert report["status"] == "FAIL"
    assert report["teams"]["70"]["undeclared_differences"] == ["motorParameters.cfg"]
    stray = arena.config / "Robots/Default/K1/extra.cfg"
    stray.write_text("x = 1;\n")
    assert arena.verify()["checks"]["untouched_outside_generated"] is False


def test_scene_declares_one_scenario_per_team(arena):
    scene, console = arena.write_scene("unit")
    text = scene.read_text()
    assert '<Compound name="Forge_T5"/>' in text and '<Compound name="Forge_T70"/>' in text
    assert '<Compound name="MField"/>' in text
    assert console.read_text().startswith("call Game3v3M")


# ------------------------------------------------------------------ evidence parsing

def test_match_readback_counts_network_loads(tmp_path, state):
    packs.ensure_baseline()
    candidate = packs.create("cand", {"walk": str(OFFICIAL_WALK)})
    run = tmp_path / "match"
    run.mkdir()
    cfg = tmp_path / "arena/x/Config"
    lines = []
    for _ in range(3):
        lines.append(f"AUDIT network provider=CPU model={cfg}/NeuralNets/Walk/forge/{candidate['id']}/walk.onnx")
        lines.append(f"AUDIT network provider=CPU model={cfg}/NeuralNets/Walk/K1_walk.onnx")
    for _ in range(6):
        lines.append(f"AUDIT network provider=CPU model={cfg}/NeuralNets/Walk/K1_kick_inner.onnx")
        lines.append(f"AUDIT network provider=CPU model={cfg}/NeuralNets/Walk/K1_kick_inner_soft.onnx")
    (run / "console.log").write_text("\n".join(lines) + "\n")
    teams = {"5": {"pack_id": candidate["id"]}, "70": {"pack_id": packs.BASELINE_ID}}
    result = match.summarize(run, 1000, 0, teams, cfg)
    assert result["network_readback"]["ok"] is True
    swapped = {"5": {"pack_id": packs.BASELINE_ID}, "70": {"pack_id": packs.BASELINE_ID}}
    assert match.summarize(run, 1000, 0, swapped, cfg)["network_readback"]["ok"] is False
    assert match.summarize(run, 1000, 0, teams, tmp_path / "elsewhere")["network_readback"]["ok"] is False


def test_recorded_arena_match_passes_offline_reanalysis():
    runs = sorted((Path(__file__).resolve().parents[1] / "runs/matches").glob("*/result.json"))
    if not runs:
        pytest.skip("no recorded match yet")
    run = runs[0].parent
    launch = json.loads((run / "launch.json").read_text())
    teams = {t: {"pack_id": v["pack_id"]} for t, v in launch["teams"].items()}
    result = match.summarize(run, launch["seconds"] * 500, 0, teams, Path(launch["arena_root"]) / "Config")
    assert result["network_readback"]["ok"]
    assert result["checks"]["camera_perception_rate_at_least_50hz"]


# ------------------------------------------------------------------ builds, jobs and server

def test_existing_arm_program_passes_static_verification():
    elf = paths.BH_LOCAL / "Build/Linux/Booster/Release/bhuman"
    if not elf.exists():
        pytest.skip("no Booster build present")
    report = builds.verify_arm_elf(elf)
    assert report["status"] == "PASS", report["checks"]
    assert "rt/low_state" in report["details"]["sdk_topic_markers"]
    host = builds.verify_arm_elf(paths.SIMROBOT_RELEASE)
    assert host["status"] == "FAIL" and not host["checks"]["aarch64"]


def test_job_whitelist_and_parameter_validation(state):
    manager = jobs.JobManager(db_path=paths.DB_PATH, autostart=False)
    with pytest.raises(jobs.JobError):
        manager.preview("shell", {"cmd": "rm -rf /"})
    with pytest.raises(jobs.JobError):
        manager.preview("train", {"envs": 100000})
    with pytest.raises(jobs.JobError):
        manager.preview("export", {"checkpoint": "/etc/passwd", "name": "x"})
    with pytest.raises(jobs.JobError):
        manager.preview("flash", {"team": 6, "pack_id": "x"})
    with pytest.raises(jobs.JobError):
        manager.preview("build", {"variant": "../../etc"})
    spec = manager.preview("train", {"envs": 64, "iterations": 3})
    assert spec["resources"] == ["gpu"] and spec["argv"][-1].isdigit()
    job_id = manager.submit("flash", {"team": 5, "pack_id": "bhuman-official"})
    assert manager.get(job_id)["status"] == "queued"
    assert manager.cancel(job_id) and manager.get(job_id)["status"] == "cancelled"
    restarted = jobs.JobManager(db_path=paths.DB_PATH, autostart=False)
    assert restarted.get(job_id)["status"] == "cancelled"


def test_server_requires_token_host_and_origin(state):
    from fastapi.testclient import TestClient

    from forge import server

    app = server.create_app(start_jobs=False)
    client = TestClient(app, base_url="http://127.0.0.1:8920")
    assert client.get("/api/contracts").status_code == 401
    headers = {"X-Forge-Token": app.state.token}
    assert client.get("/api/contracts", headers=headers).status_code == 200
    assert client.get("/api/contracts", headers={**headers, "host": "evil.example"}).status_code == 403
    response = client.post("/api/jobs", json={"type": "flash", "params": {"team": 5, "pack_id": "x"}},
                           headers={**headers, "origin": "http://evil.example"})
    assert response.status_code == 403
    response = client.post("/api/jobs/preview", json={"type": "rm", "params": {}}, headers=headers)
    assert response.status_code == 400
    assert client.get("/api/matches/..%2F..%2Fetc", headers=headers).status_code == 404


def test_gates_never_pass_without_evidence(state):
    from forge import gates

    candidate = packs.create("cand", {"walk": str(OFFICIAL_WALK)})
    report = gates.assess(candidate["id"])
    assert report["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert report["gates"]["L5_hardware"]["status"] == "NOT_VERIFIED"
    setup = {"worlds": 1000, "seed": 1}
    worse = gates.gate_mjwarp({"setup": setup, "metrics": {"falls": 80, "tracking_rmse": {}}},
                              {"setup": setup, "metrics": {"falls": 40, "tracking_rmse": {}}})
    same = gates.gate_mjwarp({"setup": setup, "metrics": {"falls": 42, "tracking_rmse": {}}},
                             {"setup": setup, "metrics": {"falls": 40, "tracking_rmse": {}}})
    assert worse["status"] == same["status"] == "INSUFFICIENT"
    other = gates.gate_mjwarp({"setup": {"worlds": 10}, "metrics": {"falls": 0}}, {"setup": setup, "metrics": {"falls": 0}})
    assert other["status"] == "INSUFFICIENT"


def test_cfg_with_values_inserts_missing_scalar():
    document = bhconfig.CfgDocument.load(BH_CONFIG / "Robots/SimulatedK1/walkingEngine.cfg")
    text = document.with_values({"walkNeuronalNetworkParameters.actionFilterAlpha": "0.3",
                                 "walkNeuronalNetworkParameters.modelName": "x.onnx"})
    again = bhconfig.CfgDocument(text)
    assert again.get("walkNeuronalNetworkParameters.actionFilterAlpha") == "0.3"
    assert again.get("walkNeuronalNetworkParameters.modelName") == "x.onnx"
    assert again.get("walkNeuronalNetworkParameters.numOutput") == "13"


def test_code_module_pack_requires_module_in_program(arena):
    module = {"ForgeWalkingEngine": {"replaces": "WalkingEngine", "cfg": "forgeWalkingEngine.cfg",
                                     "params": {"walkNeuronalNetworkParameters.actionFilterAlpha": "0.3"}}}
    pack = packs.create("module", {}, {}, "", {}, module)
    with pytest.raises(arena_mod.ArenaError):
        arena.flash(5, pack["id"])  # bhuman-local's program does not contain ForgeWalkingEngine
    with pytest.raises(packs.PackError):
        packs.create("bad", {}, {}, "", {}, {"ForgeWalkingEngine": {"replaces": "WalkingEngine", "cfg": "wrong.cfg"}})


def test_variant_patch_inside_git_work_tree_really_applies(state):
    patch = Path(__file__).resolve().parents[1] / "patches/0001-forge-walking-engine.patch"
    if not patch.is_file():
        pytest.skip("patch not generated")
    variant = builds.create_variant("unit-patch", [str(patch)])
    assert len([p for p in variant["files_changed_vs_base"] if p.startswith("Src/")]) == 2
    assert variant["schema"] == "forge.variant/2"
    assert (builds.variant_root("unit-patch") / "Src/Modules/MotionControl/ForgeWalkingEngine/ForgeWalkingEngine.cpp").is_file()
    change = arena_mod.variant_change_class(builds.variant_root("unit-patch"))
    assert change["additive"] and not change["modified_existing"]


def test_cancel_stops_grandchildren_in_their_own_session(tmp_path):
    import subprocess
    import sys
    import time

    import psutil

    script = tmp_path / "spawn.py"
    marker = tmp_path / "child.pid"
    script.write_text(
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], start_new_session=True)\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(600)\n")
    parent = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
    for _ in range(100):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.05)
    grandchild = int(marker.read_text())
    assert psutil.pid_exists(grandchild)
    jobs.JobManager._terminate(parent)
    time.sleep(0.2)
    assert not psutil.pid_exists(grandchild) or psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE
