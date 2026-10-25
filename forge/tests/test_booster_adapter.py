"""Foreign-gait contracts and per-robot evidence, using CPU ONNX and temporary state.

These tests do not start SimRobot, install a controller, or modify retained evidence.
The small generated models are test doubles, never vendor firmware or useful gaits.
"""
import copy

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from forge import arena, bhconfig, contracts, match, packs, paths, util


MODULE = "BoosterDeployWalkingEngine"
MODULE_CFG = "boosterDeployWalkingEngine.cfg"
FW_PRIMARY = "booster_fw16_walk"
FW_AUXILIARIES = ("booster_fw16_side", "booster_fw16_turn")
FW_SWITCHER = "walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher"


@pytest.fixture
def state(tmp_path, monkeypatch):
    for key, relative in {"PACKS": "packs", "ARENAS": "arenas", "RUNS": "runs",
                          "STATE": "state", "DB_PATH": "forge.db", "VARIANTS": "variants",
                          "BH_SIM_LOCK": ".sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    return tmp_path


def synthetic_policy(path, inputs=690, outputs=20, offset=0.0):
    """A valid, tiny dynamic-batch Slice/Add graph with controllable bad outputs."""
    initializers = [numpy_helper.from_array(np.array(value, dtype=np.int64), name)
                    for name, value in (("starts", [0]), ("ends", [outputs]), ("axes", [1]))]
    initializers.append(numpy_helper.from_array(np.array([offset], dtype=np.float32), "offset"))
    graph = helper.make_graph([
        helper.make_node("Slice", ["observations", "starts", "ends", "axes"], ["first_joints"]),
        helper.make_node("Add", ["first_joints", "offset"], ["actions"]),
    ], "synthetic-only-not-vendor-policy",
        [helper.make_tensor_value_info("observations", TensorProto.FLOAT, [None, inputs])],
        [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [None, outputs])], initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return path


def bindings():
    return {MODULE: {"replaces": "WalkingEngine", "cfg": MODULE_CFG,
                     "params": {"walkNeuronalNetworkParameters.numInput": "690",
                                "walkNeuronalNetworkParameters.numOutput": "20"}}}


@pytest.fixture
def candidate(state):
    model = synthetic_policy(state / "synthetic-690x20.onnx")
    return packs.create("synthetic-booster-test", {"booster_walk": str(model)}, modules=bindings())


def test_foreign_slot_accepts_its_contract_and_rejects_bhuman_contract(state):
    model = synthetic_policy(state / "foreign.onnx")
    checked = contracts.check("booster_walk", model)
    assert checked["contract"] == "booster.deploy.k1.walk.690x20"
    assert checked["ort_smoke"]["batch"] == 4
    assert "CPU" in checked["ort_smoke"]["runtime"]
    with pytest.raises(contracts.ContractError, match="344"):
        contracts.check("walk", model)
    with pytest.raises(contracts.ContractError, match="690"):
        contracts.check("booster_walk", synthetic_policy(state / "bhuman.onnx", 344, 13))


@pytest.mark.parametrize("inputs,outputs", [(689, 20), (690, 19), (690, 21)])
def test_foreign_dimensions_are_not_silently_adapted(state, inputs, outputs):
    with pytest.raises(contracts.ContractError):
        contracts.check("booster_walk", synthetic_policy(state / "wrong.onnx", inputs, outputs))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_foreign_model_must_produce_finite_cpu_outputs(state, value):
    with pytest.raises(contracts.ContractError, match="数值无效"):
        contracts.check("booster_walk", synthetic_policy(state / "nonfinite.onnx", offset=value))


@pytest.mark.parametrize("components,modules", [
    ({"booster_walk": "not-read.onnx"}, {}),
    ({}, bindings()),
    ({"walk": "a.onnx", "booster_walk": "b.onnx"}, bindings()),
    ({"booster_walk": "a.onnx"}, {**bindings(), "OtherWalkingEngine": {
        "replaces": "WalkingEngine", "cfg": "otherWalkingEngine.cfg"}}),
])
def test_foreign_network_requires_exactly_one_matching_consumer(state, components, modules):
    with pytest.raises(packs.PackError):
        packs.create("invalid-binding", components, modules=modules)
    assert not paths.PACKS.exists()


def test_foreign_pack_hash_covers_model_and_module_selection(candidate, state):
    assert packs.verify(candidate["id"])["status"] == "PASS"
    assert packs.motion_slots(candidate) == ("booster_walk", "kick", "kick_soft")
    assert packs.motion_slots(packs.ensure_baseline()) == ("walk", "kick", "kick_soft")
    stored = packs.pack_dir(candidate["id"]) / "files/booster_walk.onnx"
    synthetic_policy(stored, offset=0.125)
    changed = packs.verify(candidate["id"])
    assert changed["status"] == "FAIL"
    assert not changed["checks"]["booster_walk_hash"]
    assert changed["checks"]["booster_walk_contract"]


@pytest.mark.parametrize("mutation", ["parameter", "missing-module"])
def test_manifest_tampering_is_rejected_even_with_original_model(candidate, mutation):
    changed = copy.deepcopy(candidate)
    if mutation == "parameter":
        changed["modules"][MODULE]["params"]["walkNeuronalNetworkParameters.numOutput"] = "13"
    else:
        changed["modules"] = {}
    util.write_json(packs.pack_dir(candidate["id"]) / "pack.json", changed)
    report = packs.verify(candidate["id"])
    assert report["status"] == "FAIL" and not report["checks"]["content_identity"]
    if mutation == "missing-module":
        assert not report["checks"]["consumer_bindings"]


def test_static_team_flash_keeps_official_opponent_and_reads_adapter_cfg(candidate, monkeypatch):
    test_arena = arena.Arena("isolated-adapter-test")
    test_arena.materialize()
    with pytest.raises(arena.ArenaError, match="没有模块"):
        test_arena.flash(70, candidate["id"])
    # Only the source-module presence check is stubbed: no claim of compiled C++ execution.
    monkeypatch.setattr(test_arena, "has_module", lambda module: module == MODULE)
    test_arena.flash(5, packs.BASELINE_ID)
    test_arena.flash(70, candidate["id"])
    report = test_arena.verify()
    assert report["status"] == "PASS", report["checks"]
    assert report["checks"]["T5_baseline_byte_identical"]
    baseline = report["teams"]["5"]["networks"]
    foreign = report["teams"]["70"]["networks"]
    assert set(baseline) == {"walk", "kick", "kick_soft"}
    assert set(foreign) == {"booster_walk", "kick", "kick_soft"}
    assert foreign["booster_walk"]["model_name"] == f"forge/{candidate['id']}/booster_walk.onnx"
    assert foreign["booster_walk"]["sha256"] == candidate["components"]["booster_walk"]["sha256"]
    for slot in ("kick", "kick_soft"):
        assert baseline[slot]["sha256"] == foreign[slot]["sha256"]
    cfg = test_arena.config / "Scenarios/Forge_T70/K1" / MODULE_CFG
    doc = bhconfig.CfgDocument.load(cfg)
    assert doc.get("walkNeuronalNetworkParameters.numInput") == "690"
    assert doc.get("walkNeuronalNetworkParameters.numOutput") == "20"
    cfg.write_text(doc.patched({"walkNeuronalNetworkParameters.modelName": "K1_walk.onnx"}))
    report = test_arena.verify()
    assert not report["checks"]["T70_networks_match_pack"]
    assert report["checks"]["T5_baseline_byte_identical"]


@pytest.fixture
def runtime_evidence(candidate, state):
    """A full six-robot audit fixture that passes all existing summary checks."""
    packs.ensure_baseline()
    root = state / "config"
    run = state / "match"
    run.mkdir()
    model_name = f"forge/{candidate['id']}/booster_walk.onnx"
    lines = []
    for name, (team, player) in match.match_roster().items():
        for slot in ("walk", "kick", "kick_soft"):
            model = model_name if team == 70 and slot == "walk" else {
                "walk": "K1_walk.onnx", "kick": "K1_kick_inner.onnx",
                "kick_soft": "K1_kick_inner_soft.onnx"}[slot]
            lines.append(f"AUDIT network provider=CPU model={root}/NeuralNets/Walk/{model}")
        if team == 70:
            lines.append(f"AUDIT forge_module name={MODULE} team={team} player={player} model={model_name}")
            lines.append(f"AUDIT booster_policy name={MODULE} team={team} player={player} inferences=25 nonfinite_total=0")
        for tick in range(1, 11):
            lines.append(f"AUDIT physics robot={name} tick={tick} x_mm=0 y_mm=0 yaw_rad=0 "
                         f"roll_rad=0 pitch_rad=0 image_time={tick * 17} nonfinite_total=0")
            lines.append(f"AUDIT motion team={team} player={player} tick={tick} walk_frames={tick} "
                         "fall_frames=0 getup_frames=0 nonfinite_total=0")
        lines.extend([
            f"AUDIT perception team={team} player={player} image_time=0 frames=0 width=544 height=448 ball_status=1",
            f"AUDIT perception team={team} player={player} image_time=1000 frames=60 width=544 height=448 ball_status=1",
            f"AUDIT cognition team={team} player={player} skill=2",
        ])
    for tick, game_state in enumerate((1, 2, 3), 1):
        lines.append(f"AUDIT game tick={tick} state={game_state} robots=6 score_a=0 score_b=0 ball_x_mm=0 ball_y_mm=0")
    lines.append("AUDIT completed steps=1000")
    teams = {"5": {"pack_id": packs.BASELINE_ID}, "70": {"pack_id": candidate["id"]}}

    def summarize(modified=None, team_selection=None):
        (run / "console.log").write_text("\n".join(lines if modified is None else modified) + "\n")
        return match.summarize(run, 1000, 0, teams if team_selection is None else team_selection, root)

    return lines, summarize


def test_runtime_proves_three_distinct_candidate_robots_and_official_opponent(runtime_evidence):
    _, summarize = runtime_evidence
    report = summarize()
    assert report["status"] == "PASS", report["checks"]
    readback = report["network_readback"]
    assert readback["modules"]["instances_ok"]
    assert len(readback["foreign_policy_execution"]["instances"]) == 3
    assert {r["team"] for r in readback["modules"]["instances"]} == {"70"}
    switched = {"5": {"pack_id": packs.BASELINE_ID}, "70": {"pack_id": packs.BASELINE_ID}}
    assert summarize(team_selection=switched)["status"] == "FAIL"


@pytest.mark.parametrize("kind", ["forge_module", "booster_policy"])
def test_repeated_player_cannot_impersonate_three_candidate_robots(runtime_evidence, kind):
    lines, summarize = runtime_evidence
    changed = [line.replace("player=2", "player=1").replace("player=3", "player=1")
               if line.startswith(f"AUDIT {kind} ") else line for line in lines]
    report = summarize(changed)
    assert report["status"] == "FAIL" and not report["checks"]["runtime_network_readback"]


@pytest.mark.parametrize("mutation", ["missing", "zero", "missing-inference", "nonfinite", "malformed",
                                        "wrong-team", "wrong-model"])
def test_loaded_model_without_valid_per_robot_execution_cannot_pass(runtime_evidence, mutation):
    lines, summarize = runtime_evidence
    changed = []
    for line in lines:
        if line.startswith("AUDIT booster_policy ") and "player=3 " in line:
            if mutation == "missing":
                continue
            line = {"zero": line.replace("inferences=25", "inferences=0"),
                    "missing-inference": line.replace("inferences=25 ", ""),
                    "nonfinite": line.replace("nonfinite_total=0", "nonfinite_total=1"),
                    "malformed": line.replace("nonfinite_total=0", "nonfinite_total=nan"),
                    "wrong-team": line.replace("team=70", "team=5")}.get(mutation, line)
        if mutation == "wrong-model" and line.startswith("AUDIT forge_module ") and "player=3 " in line:
            line = line.split(" model=", 1)[0] + " model=K1_walk.onnx"
        changed.append(line)
    report = summarize(changed)
    assert report["status"] == "FAIL" and not report["checks"]["runtime_network_readback"]


def test_nonfinite_history_cannot_be_erased_by_a_later_clean_counter(runtime_evidence):
    lines, summarize = runtime_evidence
    bad = f"AUDIT booster_policy name={MODULE} team=70 player=1 inferences=5 nonfinite_total=1"
    assert not summarize([bad, *lines])["checks"]["runtime_network_readback"]


def test_missing_nonfinite_evidence_is_not_assumed_clean(runtime_evidence):
    lines, summarize = runtime_evidence
    changed = [line.replace(" nonfinite_total=0", "") if line.startswith("AUDIT booster_policy ")
               and "player=3 " in line else line for line in lines]
    assert not summarize(changed)["checks"]["runtime_network_readback"]


def test_negative_cumulative_error_counter_is_invalid_evidence(runtime_evidence):
    lines, summarize = runtime_evidence
    changed = [line.replace("nonfinite_total=0", "nonfinite_total=-1")
               if line.startswith("AUDIT booster_policy ") and "player=3 " in line else line for line in lines]
    assert not summarize(changed)["checks"]["runtime_network_readback"]


def firmware_bindings(switcher="true"):
    result = bindings()
    if switcher is not None:
        result[MODULE]["params"][FW_SWITCHER] = switcher
    return result


@pytest.fixture
def firmware_candidate(state):
    components = {
        slot: str(synthetic_policy(state / f"{slot}.onnx", offset=index / 8))
        for index, slot in enumerate((FW_PRIMARY, *FW_AUXILIARIES))
    }
    return packs.create("synthetic-firmware-three-actor", components,
                        modules=firmware_bindings())


@pytest.mark.parametrize("slot", FW_AUXILIARIES)
def test_firmware_auxiliary_models_enforce_the_full_body_contract(state, slot):
    valid = contracts.check(slot, synthetic_policy(state / "valid.onnx"))
    assert valid["inputs"][0]["dims"][-1] == 690
    assert valid["outputs"][0]["dims"][-1] == 20
    with pytest.raises(contracts.ContractError, match="690"):
        contracts.check(slot, synthetic_policy(state / "wrong.onnx", 344, 13))
    with pytest.raises(contracts.ContractError, match="数值无效"):
        contracts.check(slot, synthetic_policy(state / "nan.onnx", offset=float("nan")))


@pytest.mark.parametrize("slots,modules", [
    ((FW_PRIMARY, FW_AUXILIARIES[0]), firmware_bindings()),
    ((FW_PRIMARY, FW_AUXILIARIES[1]), firmware_bindings()),
    ((FW_PRIMARY,), firmware_bindings()),
    (FW_AUXILIARIES, firmware_bindings()),
    (("booster_walk", *FW_AUXILIARIES), firmware_bindings()),
    (("walk", *FW_AUXILIARIES), firmware_bindings()),
    ((FW_PRIMARY, *FW_AUXILIARIES), {}),
    ((FW_PRIMARY, *FW_AUXILIARIES), firmware_bindings("false")),
    ((FW_PRIMARY, *FW_AUXILIARIES), firmware_bindings(None)),
])
def test_firmware_auxiliaries_require_complete_explicit_switcher_binding(state, slots, modules):
    # Binding validation must reject these before any file reads or pack creation.
    with pytest.raises(packs.PackError):
        packs.create("invalid-firmware-switcher", {slot: "not-read.onnx" for slot in slots},
                     modules=modules)
    assert not paths.PACKS.exists()


def test_firmware_pack_records_every_loaded_actor_and_hashes_each(firmware_candidate):
    assert packs.motion_slots(firmware_candidate) == (
        FW_PRIMARY, "kick", "kick_soft", *FW_AUXILIARIES)
    assert packs.verify(firmware_candidate["id"])["status"] == "PASS"
    side = packs.pack_dir(firmware_candidate["id"]) / "files/booster_fw16_side.onnx"
    synthetic_policy(side, offset=0.625)
    changed = packs.verify(firmware_candidate["id"])
    assert changed["status"] == "FAIL"
    assert not changed["checks"]["booster_fw16_side_hash"]
    assert changed["checks"]["booster_fw16_side_contract"]
    assert changed["checks"]["booster_fw16_turn_hash"]


def test_firmware_switcher_manifest_tampering_invalidates_binding(firmware_candidate):
    changed = copy.deepcopy(firmware_candidate)
    changed["modules"][MODULE]["params"][FW_SWITCHER] = "false"
    util.write_json(packs.pack_dir(changed["id"]) / "pack.json", changed)
    report = packs.verify(changed["id"])
    assert report["status"] == "FAIL"
    assert not report["checks"]["consumer_bindings"]
    assert not report["checks"]["content_identity"]


@pytest.mark.parametrize("slot", FW_AUXILIARIES)
def test_firmware_auxiliary_path_cannot_override_the_registered_component(state, slot):
    modules = firmware_bindings()
    modules[MODULE]["params"][contracts.CONTRACTS[slot].cfg_key] = "unregistered.onnx"
    with pytest.raises(packs.PackError, match="不能手动覆盖"):
        packs.create("conflicting-actor-path", {
            name: "not-read.onnx" for name in (FW_PRIMARY, *FW_AUXILIARIES)}, modules=modules)
    assert not paths.PACKS.exists()


def test_firmware_auxiliary_names_are_injected_into_only_the_new_module(
        firmware_candidate, monkeypatch):
    test_arena = arena.Arena("isolated-firmware-switcher-test")
    test_arena.materialize()
    monkeypatch.setattr(test_arena, "has_module", lambda module: module == MODULE)
    test_arena.flash(5, packs.BASELINE_ID)
    baseline_cfg = test_arena.config / "Scenarios/Forge_T5/K1/walkingEngine.cfg"
    baseline_digest = util.sha256_file(baseline_cfg)
    test_arena.flash(70, firmware_candidate["id"])
    report = test_arena.verify()
    assert report["status"] == "PASS", report["checks"]
    assert report["checks"]["T5_baseline_byte_identical"]
    assert util.sha256_file(baseline_cfg) == baseline_digest
    foreign = report["teams"]["70"]["networks"]
    assert set(foreign) == {FW_PRIMARY, "kick", "kick_soft", *FW_AUXILIARIES}
    cfg_root = test_arena.config / "Scenarios/Forge_T70/K1"
    module_path = cfg_root / MODULE_CFG
    module = bhconfig.CfgDocument.load(module_path)
    official_consumer_text = (cfg_root / "walkingEngine.cfg").read_text()
    assert module.get(FW_SWITCHER) == "true"
    for slot in FW_AUXILIARIES:
        key = contracts.CONTRACTS[slot].cfg_key
        assert module.get(key) == f"forge/{firmware_candidate['id']}/{slot}.onnx"
        assert key.rsplit(".", 1)[-1] not in official_consumer_text
        assert foreign[slot]["sha256"] == firmware_candidate["components"][slot]["sha256"]
    # A valid but wrong side/turn file must fail static identity read-back.
    side_key = contracts.CONTRACTS[FW_AUXILIARIES[0]].cfg_key
    turn_key = contracts.CONTRACTS[FW_AUXILIARIES[1]].cfg_key
    module_path.write_text(module.patched({side_key: module.get(turn_key)}))
    report = test_arena.verify()
    assert not report["checks"]["T70_networks_match_pack"]
    assert report["checks"]["T5_baseline_byte_identical"]


@pytest.fixture
def firmware_runtime_evidence(runtime_evidence, firmware_candidate):
    lines, summarize = runtime_evidence
    original_primary = next(line.split(" model=", 1)[1] for line in lines
                            if line.startswith("AUDIT forge_module "))
    primary = f"forge/{firmware_candidate['id']}/{FW_PRIMARY}.onnx"
    modified = [line.replace(original_primary, primary) for line in lines]
    modified = [line + " selected=side forward_inferences=10 side_inferences=10 turn_inferences=5"
                if line.startswith("AUDIT booster_policy ") else line for line in modified]
    primary_load = next(line for line in modified
                        if line.startswith("AUDIT network ") and primary in line)
    for slot in FW_AUXILIARIES:
        modified.extend([primary_load.replace(FW_PRIMARY, slot)] * 3)
    teams = {"5": {"pack_id": packs.BASELINE_ID},
             "70": {"pack_id": firmware_candidate["id"]}}

    def summarize_firmware(changed=None):
        return summarize(modified if changed is None else changed, team_selection=teams)

    return modified, summarize_firmware


def test_firmware_runtime_requires_three_loads_of_each_actor_and_official_opponent(
        firmware_runtime_evidence, firmware_candidate):
    _, summarize = firmware_runtime_evidence
    report = summarize()
    assert report["status"] == "PASS", report["checks"]
    readback = report["network_readback"]
    assert readback["observed_loads"]["/NeuralNets/Walk/K1_walk.onnx"] == 3
    for slot in (FW_PRIMARY, *FW_AUXILIARIES):
        suffix = f"/NeuralNets/Walk/forge/{firmware_candidate['id']}/{slot}.onnx"
        assert readback["expected_loads"][suffix] == 3
        assert readback["observed_loads"][suffix] == 3
    assert readback["modules"]["instances_ok"]
    assert len(readback["foreign_policy_execution"]["instances"]) == 3


@pytest.mark.parametrize("mutation", ["missing-count", "negative-count", "wrong-sum", "invalid-selected"])
def test_firmware_requires_consistent_per_policy_execution_counts(firmware_runtime_evidence, mutation):
    lines, summarize = firmware_runtime_evidence
    changed = list(lines)
    index = next(i for i, line in enumerate(changed)
                 if line.startswith("AUDIT booster_policy ") and "player=2 " in line)
    line = changed[index]
    changed[index] = {
        "missing-count": line.replace(" side_inferences=10", ""),
        "negative-count": line.replace("side_inferences=10", "side_inferences=-1"),
        "wrong-sum": line.replace("side_inferences=10", "side_inferences=9"),
        "invalid-selected": line.replace("selected=side", "selected=unregistered"),
    }[mutation]
    report = summarize(changed)
    assert report["status"] == "FAIL"
    assert not report["checks"]["runtime_network_readback"]
    # An additional valid report may not erase the malformed record.
    assert not summarize(changed + [line])["checks"]["runtime_network_readback"]


@pytest.mark.parametrize("slot", FW_AUXILIARIES)
@pytest.mark.parametrize("mutation", ["missing", "extra", "outside-arena"])
def test_incomplete_or_foreign_auxiliary_runtime_loads_fail(
        firmware_runtime_evidence, slot, mutation):
    lines, summarize = firmware_runtime_evidence
    changed = list(lines)
    index = next(i for i, line in enumerate(changed)
                 if line.startswith("AUDIT network ") and f"/{slot}.onnx" in line)
    if mutation == "missing":
        changed.pop(index)
    elif mutation == "extra":
        changed.append(changed[index])
    else:
        changed[index] = changed[index].replace(" model=", " model=/outside-arena")
    report = summarize(changed)
    assert report["status"] == "FAIL"
    assert not report["checks"]["runtime_network_readback"]


@pytest.fixture
def isolated_mapping_evidence(runtime_evidence, state):
    """A separately registered pack and matching per-player low/regular evidence."""
    lines, summarize = runtime_evidence
    original_primary = next(line.split(" model=", 1)[1] for line in lines
                            if line.startswith("AUDIT forge_module "))
    modules = bindings()
    modules[MODULE]["params"]["walkNeuronalNetworkParameters.boosterUseLowStiffnessMapping"] = "true"
    policy = synthetic_policy(state / "isolated-mapping.onnx", offset=.25)
    isolated = packs.create("synthetic-isolated-pd", {"booster_walk": str(policy)}, modules=modules)
    assert packs.verify(isolated["id"])["status"] == "PASS"
    primary = f"forge/{isolated['id']}/booster_walk.onnx"
    modified = [line.replace(original_primary, primary) for line in lines]
    for player in (1, 2, 3):
        for time, phase, mode, mapping in ((100, "stand", "walk", "low"),
                                           (200, "walk", "walk", "low"),
                                           (300, "walk", "kick", "regular"),
                                           (400, "walk", "walk", "low")):
            modified.append(f"AUDIT booster_mapping team=70 player={player} time_ms={time} "
                            f"phase={phase} mode={mode} mapping={mapping}")
    teams = {"5": {"pack_id": packs.BASELINE_ID}, "70": {"pack_id": isolated["id"]}}

    def summarize_isolated(changed=None):
        return summarize(modified if changed is None else changed, team_selection=teams)

    return modified, summarize_isolated


def test_isolated_mapping_requires_each_candidate_to_walk_low_and_kick_regular(isolated_mapping_evidence):
    _, summarize = isolated_mapping_evidence
    report = summarize()
    assert report["status"] == "PASS", report["checks"]
    mapping = report["network_readback"]["motor_mapping"]
    assert mapping["ok"]
    assert mapping["expected_isolated_players"] == [("70", "1"), ("70", "2"), ("70", "3")]
    assert len(mapping["observed"]) == 12


def test_isolated_mapping_does_not_require_a_kick_that_never_occurred(isolated_mapping_evidence):
    lines, summarize = isolated_mapping_evidence
    no_kicks = [line for line in lines if not (line.startswith("AUDIT booster_mapping ") and "mode=kick" in line)]
    assert summarize(no_kicks)["status"] == "PASS"


@pytest.mark.parametrize("mutation", ["missing-player", "duplicate-player", "walk-regular", "kick-low",
                                       "missing-mapping", "invalid-mode", "invalid-phase", "kick-in-stand"])
def test_incomplete_or_wrong_motor_mapping_fails_even_after_valid_rows(isolated_mapping_evidence, mutation):
    lines, summarize = isolated_mapping_evidence
    modified = []
    changed_one = False
    for line in lines:
        if line.startswith("AUDIT booster_mapping ") and "player=3 " in line:
            if mutation == "missing-player":
                continue
            if mutation == "duplicate-player":
                line = line.replace("player=3", "player=1")
            elif not changed_one:
                if mutation == "walk-regular" and "mode=walk" in line:
                    line = line.replace("mapping=low", "mapping=regular")
                    changed_one = True
                elif mutation == "kick-low" and "mode=kick" in line:
                    line = line.replace("mapping=regular", "mapping=low")
                    changed_one = True
                elif mutation == "missing-mapping":
                    line = line.replace(" mapping=low", "")
                    changed_one = True
                elif mutation == "invalid-mode":
                    line = line.replace("mode=walk", "mode=getUp")
                    changed_one = True
                elif mutation == "invalid-phase":
                    line = line.replace("phase=stand", "phase=getUp")
                    changed_one = True
                elif mutation == "kick-in-stand" and "mode=kick" in line:
                    line = line.replace("phase=walk", "phase=stand")
                    changed_one = True
        modified.append(line)
    report = summarize(modified)
    assert report["status"] == "FAIL"
    assert not report["checks"]["runtime_network_readback"]
    assert not report["network_readback"]["motor_mapping"]["ok"]
    assert all(value for name, value in report["checks"].items() if name != "runtime_network_readback")


@pytest.mark.parametrize("identity", ["team=5 player=1", "team=70 player=9", "team=999 player=1"])
def test_unexpected_mapping_identity_is_not_silently_filtered(isolated_mapping_evidence, identity):
    lines, summarize = isolated_mapping_evidence
    extra = f"AUDIT booster_mapping {identity} time_ms=500 phase=walk mode=walk mapping=low"
    report = summarize([*lines, extra])
    assert not report["checks"]["runtime_network_readback"]
    assert not report["network_readback"]["motor_mapping"]["ok"]
    assert len(report["network_readback"]["motor_mapping"]["observed"]) == 13


def test_nonisolated_adapter_may_emit_regular_mapping_but_not_low(runtime_evidence):
    lines, summarize = runtime_evidence
    regular = [f"AUDIT booster_mapping team=70 player={player} time_ms=100 phase=walk mode=walk mapping=regular"
               for player in (1, 2, 3)]
    assert summarize([*lines, *regular])["status"] == "PASS"
    report = summarize([*lines, *regular, regular[0].replace("mapping=regular", "mapping=low")])
    assert not report["network_readback"]["motor_mapping"]["ok"]
