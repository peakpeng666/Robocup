"""Motion bridge: K1 low-level contract, audit, ROS 2 shim codecs, verdicts, ledger, jobs and API.

Read-only on the retained B-Human / booster_deploy / SDK / firmware sources; every written
state lives in a temporary directory.  No simulator, robot, network or DDS is used.
"""
import json
import math

import pytest

from forge import jobs, paths
from forge.bridge import analysis, contract, lessons
from forge.bridge import lowlevel as L

SHIM = paths.FORGE / "sim/rosshim"


@pytest.fixture
def state(tmp_path, monkeypatch):
    for key, relative in {"PACKS": "packs", "ARENAS": "arena", "RUNS": "runs", "STATE": "run",
                          "DB_PATH": "forge.db", "VARIANTS": "variants", "BH_SIM_LOCK": ".bhuman-sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    monkeypatch.setattr(analysis, "RUNS", tmp_path / "runs/bridge")
    return tmp_path


# ------------------------------------------------------------------ contract
def test_joint_names_from_every_stack_map_onto_one_serial_order():
    assert len(L.JOINTS) == L.MOTORS == 22
    for index, sdk, deploy, bhuman, mjcf, _ in L.JOINTS:
        names = {L.canonical(sdk, "sdk"), L.canonical(deploy, "deploy"), L.canonical(bhuman, "bhuman"),
                 L.canonical(mjcf, "mjcf")}
        assert names == {L.CANONICAL[index]}
    assert [L.CANONICAL[i] for i in L.PARALLEL_INDICES] == ["l_ankle_pitch", "l_ankle_roll", "r_ankle_pitch", "r_ankle_roll"]
    assert set(L.POLICY20) <= {row[2] for row in L.JOINTS} and len(set(L.POLICY20)) == 20


def test_message_layout_matches_booster_interface_files():
    for name, expected in L.MESSAGES.items():
        fields, constants = L.parse_msg(contract.MSG_DIR / "msg" / f"{name}.msg")
        assert fields == expected, name
    assert L.parse_msg(contract.MSG_DIR / "msg/LowCmd.msg")[1] == L.LOWCMD_CONSTANTS
    assert all(entry["ok"] for entry in contract.messages().values())


def test_audit_of_retained_sources_finds_known_divergences_and_no_contract_break():
    result = contract.audit()
    assert result["verdict"] == "CONSISTENT_WITH_DIVERGENCES"
    assert all(check["ok"] for check in result["orders"].values())
    assert all(check["ok"] for check in result["policy_orders"].values())
    findings = {f["id"]: f for f in result["findings"]}
    assert not [f for f in result["findings"] if f["severity"] == "critical"]
    # B-Human's own SimRobot vs real-robot table differs only in ankle roll stiffness.
    rows = findings["gain-bhuman_sim_regular-vs-bhuman_real_regular"]["detail"]["rows"]
    assert {(r["joint"], r["field"], r["a"], r["b"]) for r in rows} == {
        ("l_ankle_roll", "p", 65.0, 25.0), ("r_ankle_roll", "p", 65.0, 25.0)}
    assert "firmware-ankle-kd-real-vs-sim" in findings
    assert len(findings["deploy-effort-clip"]["detail"]) == 12
    assert "l_elbow_yaw" in {r["joint"] for r in findings["limits-sim-wider"]["detail"]}
    assert all(fact["present"] for fact in result["code_facts"])
    assert result["firmware"]["custom_mode_ankle"] == L.FIRMWARE["custom_mode_ankle"]
    assert result["sdk"]["loco_api"]["kChangeMode"] == 2000 and result["sdk"]["modes"]["kCustom"] == 3


def test_audit_reports_order_drift_as_contract_break(monkeypatch):
    mapping = contract.bhuman_joint_mapping()
    mapping[14], mapping[15] = mapping[15], mapping[14]
    monkeypatch.setattr(contract, "bhuman_joint_mapping", lambda: mapping)
    result = contract.audit()
    assert result["verdict"] == "CONTRACT_BROKEN"
    broken = [f for f in result["findings"] if f["severity"] == "critical"]
    assert [f["id"] for f in broken] == ["order-bhuman_boosterProvider_jointMapping"]
    assert {m["index"] for m in broken[0]["detail"]} == {14, 15}


def test_low_cmd_validation():
    good = {"cmd_type": L.CMD_TYPE_SERIAL, "motor_cmd": [{"q": 0.0, "dq": 0.0, "tau": 0.0, "kp": 10.0, "kd": 1.0, "weight": 1.0}
                                                         for _ in range(L.MOTORS)]}
    assert L.validate_low_cmd(good) == []
    bad = json.loads(json.dumps(good))
    bad["cmd_type"] = L.CMD_TYPE_PARALLEL
    bad["motor_cmd"][3]["kd"] = -1.0
    bad["motor_cmd"][5]["q"] = 2.0          # left elbow yaw upper limit is 0.1745 rad
    bad["motor_cmd"][7]["q"] = math.nan
    problems = L.validate_low_cmd(bad)
    assert "cmd_type is not SERIAL" in problems
    assert any("joint 3: negative gain" in p for p in problems)
    assert any("joint 5: target" in p for p in problems)
    assert any("joint 7: non-finite" in p for p in problems)
    assert L.validate_low_cmd({"cmd_type": 1, "motor_cmd": []}) == ["motor_cmd has 0 entries, expected 22"]


# ------------------------------------------------------------------ ROS 2 shim
def test_shim_codecs_round_trip_with_float32_semantics(monkeypatch):
    monkeypatch.syspath_prepend(str(SHIM))
    import forge_bus
    from booster_interface.msg import LowCmd, LowState, MotorCmd, MotorState, RemoteControllerState

    state = LowState()
    state.imu_state.rpy, state.imu_state.gyro, state.imu_state.acc = [0.1, -0.2, 3.0], [0.5, 0, 0], [0, 0, 9.81]
    state.motor_state_serial = [MotorState(q=i / 7, dq=-i, tau_est=1.5, temperature=41) for i in range(L.MOTORS)]
    state.motor_state_parallel = [MotorState(q=i) for i in range(L.MOTORS)]
    back = forge_bus.decode_low_state(forge_bus.encode_low_state(state, seq=9, sim_time=1.25))
    assert back._forge_seq == 9 and back._forge_sim_time == 1.25
    assert back.motor_state_serial[3].q == pytest.approx(3 / 7, rel=1e-7) and back.motor_state_serial[3].q != 3 / 7
    assert back.motor_state_serial[3].temperature == 41 and len(back.motor_state_parallel) == L.MOTORS
    command = LowCmd()
    command.cmd_type = LowCmd.CMD_TYPE_SERIAL
    command.motor_cmd.extend(MotorCmd(q=0.25, kp=100.0, kd=2.0) for _ in range(L.MOTORS))
    decoded = forge_bus.decode_low_cmd(forge_bus.encode_low_cmd(command, 4))
    assert decoded.cmd_type == 1 and decoded.motor_cmd[21].kp == 100.0 and len(decoded.motor_cmd) == L.MOTORS
    remote = forge_bus.decode_remote(forge_bus.encode_remote(RemoteControllerState(x=True, ly=-0.3125)))
    assert remote.x is True and remote.ly == -0.3125
    with pytest.raises(ValueError):
        forge_bus.decode_low_cmd(forge_bus.encode_low_state(state))


def test_shim_inproc_bus_hooks_services_and_depth_one(monkeypatch):
    monkeypatch.syspath_prepend(str(SHIM))
    import forge_bus
    import rclpy
    from booster_interface.msg import LowCmd
    from booster_interface.srv import RpcService
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    bus = forge_bus.set_bus(forge_bus.InProcBus())
    received, calls = [], []
    bus.hooks["/joint_ctrl"] = received.append

    def service(request):
        calls.append((request.msg.api_id, request.msg.body))
        response = RpcService.Response()
        response.msg.status, response.msg.body = 0, json.dumps({"current_mode": 3})
        return response

    bus.services["booster_rpc_service"] = service
    rclpy.init()
    node = rclpy.create_node("test")
    publisher = node.create_publisher(LowCmd, "joint_ctrl", QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
    assert publisher.get_subscription_count() == 1
    publisher.publish(LowCmd(cmd_type=1))
    assert received and received[0].cmd_type == 1
    client = node.create_client(RpcService, "booster_rpc_service")
    assert client.wait_for_service(timeout_sec=0.1)
    request = RpcService.Request()
    request.msg.api_id, request.msg.body = 2018, ""
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future)
    assert json.loads(future.result().msg.body)["current_mode"] == 3 and calls == [(2018, "")]
    seen = []
    node.create_subscription(LowCmd, "/joint_ctrl", lambda msg: seen.append(msg.cmd_type), QoSProfile(depth=1))
    publisher.publish(LowCmd(cmd_type=0))
    publisher.publish(LowCmd(cmd_type=1))
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.spin_once(0.0)
    executor.spin_once(0.0)
    assert seen == [1]  # KEEP_LAST depth 1: only the newest sample is delivered
    forge_bus.set_bus(None)


# ------------------------------------------------------------------ verdicts
def _pair(stack="booster_deploy", *, delta=0.001, position=0.03, fell=False, ref_fall=None, error=None):
    return {"stack": stack, "variant": "v", "reference": {"kind": "ref", "first_fall_s": ref_fall},
            "bridge": {"fell": fell, "error": error},
            "comparison": {"max_segment_velocity_delta": delta, "max_position_delta_m": position,
                           "final_position_delta_m": position, "first_over_1cm_s": 9.0, "first_over_5cm_s": None,
                           "segments": {}}}


def test_identity_verdicts_are_conservative():
    assert analysis.identity_verdict(_pair(position=0.004))["verdict"] == "EXACT"
    assert analysis.identity_verdict(_pair())["verdict"] == "FAITHFUL"
    assert analysis.identity_verdict(_pair(delta=0.05))["verdict"] == "DIVERGENT"
    assert analysis.identity_verdict(_pair(fell=True))["verdict"] == "DIVERGENT"
    assert analysis.identity_verdict(_pair(ref_fall=3.0))["verdict"] == "DIVERGENT"
    assert analysis.identity_verdict(_pair(error="boom"))["verdict"] == "INSUFFICIENT_EVIDENCE"


def _gap_row(controller, axis, level, seed, *, fell=False, forward=0.5, turn=0.5):
    segments = {"forward": {"command": [0.5, 0, 0], "mean_velocity": [forward, 0, 0]},
                "turn": {"command": [0, 0, 0.5], "mean_velocity": [0, 0, turn]}}
    return {"controller": controller, "axis": axis, "level": level, "seed": seed, "fell": fell,
            "fall_s": 3.0 if fell else None, "segments": segments, "error": None}


def _gaps():
    axes = {"latency_ms": {"levels": [0, 20, 40, 80], "reference": 20},
            "kp_low": {"levels": [1, 0.8, 0.6, 0.5], "reference": 0.8},
            "push_ns": {"levels": [0, 10, 20], "reference": 15}}
    rows = []
    for seed in range(2):
        for level in axes["latency_ms"]["levels"]:
            rows.append(_gap_row("ext", "latency_ms", level, seed, fell=level >= 80))
            rows.append(_gap_row("onboard-gait", "latency_ms", level, seed))
        for level in axes["kp_low"]["levels"]:
            rows.append(_gap_row("ext", "kp_low", level, seed, forward=0.2 if level <= 0.6 else 0.5))
            rows.append(_gap_row("onboard-gait", "kp_low", level, seed, fell=level <= 0.8 and seed == 1))
        for level in axes["push_ns"]["levels"]:
            if not (level == 20 and seed == 1):
                rows.append(_gap_row("ext", "push_ns", level, seed))
            rows.append(_gap_row("onboard-gait", "push_ns", level, seed))
    return {"controllers": ["ext", "onboard-gait"], "onboard_controllers": ["onboard-gait"],
            "transport_axes": ["latency_ms"], "axes": axes, "rows": rows, "stall_fraction": 0.5}


def test_gap_margins_monotone_stalls_not_applicable_and_reference():
    table = analysis.gap_margins(_gaps())["table"]
    ext, onboard = table["ext"], table["onboard-gait"]
    assert ext["latency_ms"]["margin"] == 40 and ext["latency_ms"]["first_failure"] == 80
    assert ext["latency_ms"]["status"] == "COVERS_REFERENCE" and ext["latency_ms"]["headroom"] == pytest.approx(2.0)
    # A stall (forward speed below half the command) is a functional failure on a decreasing axis.
    assert ext["kp_low"]["margin"] == 0.8 and ext["kp_low"]["first_failure"] == 0.6
    assert ext["kp_low"]["direction"] == "decreasing" and ext["kp_low"]["cells"][2]["stalls"] == 2
    assert ext["push_ns"]["status"] == "COVERS_REFERENCE" and ext["push_ns"]["censored"]
    assert onboard["latency_ms"]["status"] == "NOT_APPLICABLE"
    assert onboard["kp_low"]["margin"] == 1 and onboard["kp_low"]["status"] == "BELOW_REFERENCE"
    missing = _gaps()
    missing["rows"] = [r for r in missing["rows"] if not (r["axis"] == "push_ns" and r["level"] == 10)]
    assert analysis.gap_margins(missing)["table"]["ext"]["push_ns"]["status"] == "INSUFFICIENT_EVIDENCE"


def _write_run(root, *, protocol_ok=True, errors=None, session_status="PASS"):
    run = root / "runs/bridge/20261023_120000_000000_fixture"
    (run / "session").mkdir(parents=True)
    scenarios = [{"id": "P1-normal-session", "status": "PASS" if protocol_ok else "FAIL", "checks": {}},
                 {"id": "P3-fall-during-custom", "status": "PASS", "checks": {},
                  "observed": {"policy_safety_stop": True, "exit_mode_after_stop": "walking", "rpc": []}}]
    raw = {"schema": "forge.bridge-raw/1", "environment": {"robot_connected": False},
           "virtual_k1": {"assumptions": ["a"]}, "errors": errors or {},
           "experiments": {"identity": {"pairs": [_pair(), _pair("bhuman")]}, "protocol": {"scenarios": scenarios},
                           "gaps": _gaps()}}
    (run / "raw.json").write_text(json.dumps(raw))
    (run / "session/session.json").write_text(json.dumps({"status": session_status,
                                                          "prime_to_first_policy_command_ms": 118.0}))
    return run


def test_analyze_overall_verdicts_and_robot_scope(state):
    run = _write_run(state)
    result = analysis.analyze(run)
    assert result["overall"] == "SIM_BRIDGE_VERIFIED" and result["real_robot"] == "UNVERIFIED"
    assert result["verdicts"] == {"identity": "BRIDGE_FAITHFUL", "protocol": "PASS", "session": "PASS", "gaps": "COMPLETE"}
    assert {f["id"] for f in result["findings"]} == {"deploy-fall-exit-mode", "deploy-prime-gap"}
    assert analysis.list_runs()[0]["overall"] == "SIM_BRIDGE_VERIFIED"
    assert analysis.analyze(_write_run(state / "b", protocol_ok=False))["overall"] == "SIM_BRIDGE_ISSUES"
    assert analysis.analyze(_write_run(state / "c", errors={"gaps": {"error": "x"}}))["overall"] == "INSUFFICIENT_EVIDENCE"
    with pytest.raises(analysis.BridgeError):
        analysis.load("../etc")


def test_lessons_ledger_is_valid_and_links_to_evidence(state):
    assert lessons.validate() == []
    ledger = json.loads(lessons.LEDGER.read_text())
    ids = [lesson["id"] for lesson in ledger["lessons"]]
    assert len(ids) == len(set(ids)) >= 20
    run = analysis.analyze(_write_run(state))
    loaded = lessons.load(run, contract.audit())
    fall = next(x for x in loaded["lessons"] if x["id"] == "deploy-fall-exits-to-walking")
    assert fall["status"] == "verified_in_sim"
    assert next(e for e in fall["evidence"] if e["kind"] == "bridge")["supported"] is True
    ankle = next(x for x in loaded["lessons"] if x["id"] == "bhuman-ankle-roll-sim-vs-real")
    assert next(e for e in ankle["evidence"] if e["kind"] == "audit")["supported"] is True
    broken = json.loads(json.dumps(ledger))
    broken["lessons"][0]["evidence"].append({"kind": "code", "path": "does/not/exist.py"})
    broken["lessons"][1]["status"] = "proven"
    problems = lessons.validate(broken)
    assert any("evidence file missing" in p for p in problems) and any("status" in p for p in problems)


def test_bridge_job_builder_is_whitelisted(state):
    manager = jobs.JobManager(db_path=state / "forge.db", autostart=False)
    try:
        spec = manager.preview("bridge", {"experiments": ["identity", "gaps"], "seeds": 2, "session": False,
                                          "controllers": ["booster-deploy"]})
        argv = spec["argv"][spec["argv"].index("bridge"):]
        assert argv[:4] == ["bridge", "run", "--experiments", "identity,gaps"]
        assert "--no-session" in argv and "booster-deploy" in argv and spec["resources"] == ["cpu_heavy"]
        for bad in ({"experiments": ["shell"]}, {"experiments": [], "session": False}, {"seeds": 99},
                    {"controllers": ["rm -rf"]}):
            with pytest.raises(jobs.JobError):
                manager.preview("bridge", bad)
    finally:
        manager.shutdown()


def test_bridge_api_endpoints(state):
    from fastapi.testclient import TestClient

    from forge import server

    run = _write_run(state)
    analysis.analyze(run)
    app = server.create_app(start_jobs=False)
    client = TestClient(app, base_url="http://127.0.0.1:8920")
    headers = {"X-Forge-Token": app.state.token}
    assert client.get("/api/bridge/runs", headers=headers).json()[0]["id"] == run.name
    detail = client.get(f"/api/bridge/runs/{run.name}", headers=headers).json()
    assert detail["overall"] == "SIM_BRIDGE_VERIFIED" and detail["real_robot"] == "UNVERIFIED"
    assert client.get("/api/bridge/runs/..%2F..%2Fetc", headers=headers).status_code == 404
    assert client.get(f"/api/bridge/runs/{run.name}/paths", headers=headers).json() == {}
    assert client.get("/api/bridge/contract", headers=headers).json()["verdict"] == "CONSISTENT_WITH_DIVERGENCES"
    ledger = client.get("/api/bridge/lessons", headers=headers).json()
    assert ledger["problems"] == [] and ledger["counts"]["verified_in_sim"] >= 1
    assert client.get("/api/bridge/contract").status_code in (401, 403)


# ------------------------------------------------------------------ cross-simulator
def _segments(forward=2.8, left=0.4, yaw=3.6, drift=0.001):
    return {"forward": {"forward_m": forward, "left_m": 0.0, "yaw_change_rad": 0.003},
            "left": {"forward_m": 0.1, "left_m": left, "yaw_change_rad": 0.05},
            "turn": {"forward_m": 0.1, "left_m": 0.1, "yaw_change_rad": yaw},
            "settled_stop": {"net_displacement_m": drift, "forward_m": 0.0, "left_m": 0.0, "yaw_change_rad": 0.0}}


def test_crosssim_compare_agreement_gap_and_weight_identity():
    crosssim = {"controllers": {
        "booster-deploy": {"metrics": _segments(forward=2.7, left=0.8, yaw=4.1), "fell": False, "error": None,
                           "controller": {"checkpoint_sha256": "c" * 64}},
        "firmware-gait": {"metrics": _segments(forward=3.5, left=0.35, yaw=3.4), "fell": False, "error": None,
                          "controller": {"actors": {"a.onnx": "1" * 64, "b.onnx": "2" * 64}}}}}
    references = {"booster-deploy": {"run": "r1", "motion_segments": _segments(), "export_checkpoint_sha256": "c" * 64,
                                     "components": {"booster_walk": "x" * 64}, "fall_frames": 0},
                  "firmware-gait": {"run": "r2", "motion_segments": _segments(forward=3.59, left=0.31, yaw=3.37),
                                    "components": {"booster_fw16_walk": "1" * 64, "booster_fw16_side": "2" * 64},
                                    "fall_frames": 0}}
    rows = analysis.crosssim_compare(crosssim, references)["rows"]
    deploy = rows["booster-deploy"]
    assert deploy["same_weights"] is True and deploy["verdict"] == "MODEL_GAP"
    assert deploy["segments"]["forward"]["agrees"] and not deploy["segments"]["left"]["agrees"]
    assert deploy["segments"]["left"]["relative"] == pytest.approx(1.0)
    assert rows["firmware-gait"]["verdict"] == "CONSISTENT" and rows["firmware-gait"]["same_weights"] is True
    references["booster-deploy"]["export_checkpoint_sha256"] = "d" * 64
    assert analysis.crosssim_compare(crosssim, references)["rows"]["booster-deploy"]["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_simrobot_reference_must_be_a_matching_motion_run(state, tmp_path):
    motion = state / "runs/motion/20261023_000000_000000_fixture"
    motion.mkdir(parents=True)
    pack = {"id": "p", "components": {"booster_walk": {"sha256": "s" * 64}},
            "provenance": {"export": {"checkpoint_sha256": "c" * 64}}}
    (motion / "launch.json").write_text(json.dumps({"pack_snapshots": {"5": pack}}))
    (motion / "result.json").write_text(json.dumps({"case": "motion-basic-v1", "execution_status": "PASS",
                                                    "motion_segments": _segments(), "robots": {"robot5": {"fall_frames": 0}}}))
    ref = analysis.simrobot_reference("booster-deploy", motion)
    assert ref["export_checkpoint_sha256"] == "c" * 64 and ref["components"] == {"booster_walk": "s" * 64}
    with pytest.raises(analysis.BridgeError):
        analysis.simrobot_reference("firmware-gait", motion)  # wrong pack components for this controller
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(analysis.BridgeError):
        analysis.simrobot_reference("booster-deploy", outside)
    (motion / "result.json").write_text(json.dumps({"case": "match", "execution_status": "PASS"}))
    with pytest.raises(analysis.BridgeError):
        analysis.simrobot_reference("booster-deploy", motion)
