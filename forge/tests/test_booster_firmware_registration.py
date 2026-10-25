"""Registration validation and motor-map boundaries, without creating real packs."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "booster_firmware_registration", Path(__file__).parents[1] / "tools/register_booster_firmware.py")
registration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registration)
PREFIX = "walkNeuronalNetworkParameters."


def write_json(path, data):
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def context(tmp_path, monkeypatch):
    sources = {"forward": "exported_policy_k1.bin", "side": "exported_policy_k1_side.bin",
               "turn": "exported_policy_k1_turn.bin"}
    evidence = {}
    for role, filename in sources.items():
        source, output = tmp_path / filename, tmp_path / f"{role}.onnx"
        source.write_bytes(f"synthetic-source-{role}".encode())
        output.write_bytes(f"synthetic-onnx-{role}".encode())
        evidence[role] = write_json(tmp_path / f"{role}.json", {
            "firmware_version": "1.6.0.10", "numeric_validation": {"passed": True},
            "input_shape": [1, 690], "output_shape": [1, 20],
            "source_model": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "output_path": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        })
    settings = write_json(tmp_path / "settings.json", {
        "modules": {"BoosterDeployWalkingEngine": {
            "replaces": "WalkingEngine", "cfg": "boosterDeployWalkingEngine.cfg", "params": {
                PREFIX + "numInput": "690", PREFIX + "numOutput": "20",
                PREFIX + "boosterUseFirmwareSwitcher": "true",
                PREFIX + "boosterSideModelName": "untrusted-manual-side.onnx",
                PREFIX + "boosterTurnModelName": "untrusted-manual-turn.onnx",
            }}},
        "joint_order": [side + part for side in ("l", "r") for part in (
            "ShoulderPitch", "ShoulderRoll", "ElbowPitch", "ElbowYaw", "HipPitch", "HipRoll",
            "HipYaw", "KneePitch", "AnklePitch", "AnkleRoll")],
    })
    official = tmp_path / "official"
    motor = official / "Config/Robots/SimulatedK1/motorParameters.cfg"
    motor.parent.mkdir(parents=True)
    joints = ["headYaw", "headPitch", "waistYaw", *json.loads(settings.read_text())["joint_order"]]
    regular = "\n".join(f"{j} = {{p = {i + 30}; d = 4; maxTorque = 50;}};" for i, j in enumerate(joints))
    low = "\n".join(f"{j} = {{p = 1; d = 1; maxTorque = 1;}};" for j in joints)
    motor.write_text(f"controlParameters = {{regular = {{{regular}}}; low = {{{low}}};}};")
    monkeypatch.setattr(registration.paths, "BH_OFFICIAL", official)
    calls = []

    def capture(name, components, cfg_patches, scope, provenance, modules):
        # Exercise the real component/module binding validator without writing a pack.
        registration.packs.validate_bindings(components, modules)
        result = dict(name=name, components=components, cfg_patches=cfg_patches, scope=scope,
                      provenance=provenance, modules=modules)
        calls.append(result)
        return result

    monkeypatch.setattr(registration.packs, "create", capture)
    return evidence, settings, motor, calls


def register(context, paired=True):
    evidence, settings, _, _ = context
    args = (evidence["side"], evidence["turn"]) if paired else ()
    return registration.register(evidence["forward"], settings, "synthetic-registration-test", *args)


def test_original_three_argument_call_disables_switcher_and_drops_manual_paths(context):
    result = register(context, paired=False)
    assert set(result["components"]) == {"booster_fw16_walk"}
    params = result["modules"]["BoosterDeployWalkingEngine"]["params"]
    assert params[PREFIX + "boosterUseFirmwareSwitcher"] == "false"
    assert PREFIX + "boosterSideModelName" not in params
    assert PREFIX + "boosterTurnModelName" not in params
    assert result["provenance"]["export"] == result["provenance"]["exports"]["forward"]
    assert not result["provenance"]["firmware_selector"]["enabled"]


def test_pair_enables_three_immutable_slots_and_keeps_all_source_evidence(context):
    _, settings, _, _ = context
    before = settings.read_bytes()
    result = register(context)
    assert set(result["components"]) == {"booster_fw16_walk", "booster_fw16_side", "booster_fw16_turn"}
    params = result["modules"]["BoosterDeployWalkingEngine"]["params"]
    assert params[PREFIX + "boosterUseFirmwareSwitcher"] == "true"
    assert not {PREFIX + "boosterSideModelName", PREFIX + "boosterTurnModelName"} & set(params)
    assert set(result["provenance"]["exports"]) == {"forward", "side", "turn"}
    assert set(result["provenance"]["export_evidence"]) == {"forward", "side", "turn"}
    assert result["provenance"]["firmware_selector"]["enabled"]
    assert not result["provenance"]["firmware_selector"]["outer_force_turn_override_reproduced"]
    assert settings.read_bytes() == before


def test_foreign_gait_low_map_preserves_regular_head_and_waist(context):
    _, _, original, _ = context
    before = original.read_bytes()
    result = register(context)
    params = result["modules"]["BoosterDeployWalkingEngine"]["params"]
    assert params[PREFIX + "boosterUseLowStiffnessMapping"] == "true"
    changes = result["cfg_patches"]["motorParameters.cfg"]
    assert all(key.startswith("controlParameters.low.") for key in changes)
    assert changes["controlParameters.low.lShoulderPitch.p"] == "20"
    assert changes["controlParameters.low.lShoulderPitch.d"] == "2.5"
    assert changes["controlParameters.low.lHipPitch.p"] == "100"
    assert changes["controlParameters.low.lHipPitch.maxTorque"] == "35"
    assert changes["controlParameters.low.lAnkleRoll.p"] == "50"
    document = registration.bhconfig.CfgDocument.load(original)
    patched = registration.bhconfig.CfgDocument(document.with_values(changes))
    for key, scalar in document.scalars.items():
        if key.startswith("controlParameters.regular."):
            assert patched.get(key) == scalar.text
    for joint in ("headYaw", "headPitch", "waistYaw"):
        for field in ("p", "d", "maxTorque"):
            assert patched.get(f"controlParameters.low.{joint}.{field}") == document.get(
                f"controlParameters.regular.{joint}.{field}")
    assert original.read_bytes() == before
    assert result["provenance"]["motor_control"]["regular_mapping_modified"] is False
    assert result["provenance"]["motor_control"]["requires_simulated_fast_getup_disabled"] is True


@pytest.mark.parametrize("missing", ["side", "turn"])
def test_partial_pair_rejected_before_pack_creation(context, missing):
    evidence, settings, _, calls = context
    with pytest.raises(ValueError, match="together"):
        registration.register(evidence["forward"], settings, "test",
                              None if missing == "side" else evidence["side"],
                              None if missing == "turn" else evidence["turn"])
    assert not calls


@pytest.mark.parametrize("role", ["forward", "side", "turn"])
@pytest.mark.parametrize("field,value", [
    ("firmware_version", "1.7.2"), ("input_shape", [1, 450]), ("output_shape", [1, 12]),
    ("numeric_validation", {"passed": False}), ("numeric_validation", {"passed": "true"}),
    ("source_model", "exported_policy_wrong.bin"),
])
def test_each_actor_contract_is_checked(context, role, field, value):
    evidence, _, _, calls = context
    data = json.loads(evidence[role].read_text())
    data[field] = value
    write_json(evidence[role], data)
    with pytest.raises(ValueError, match="verified firmware"):
        register(context)
    assert not calls


@pytest.mark.parametrize("role", ["forward", "side", "turn"])
@pytest.mark.parametrize("which", ["source_model", "output_path"])
def test_modified_original_or_export_is_rejected_before_creation(context, role, which):
    evidence, _, _, calls = context
    path = Path(json.loads(evidence[role].read_text())[which])
    path.write_bytes(path.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        register(context)
    assert not calls


def test_body_overlay_cannot_include_head_or_omit_a_joint(context):
    _, settings, _, calls = context
    data = json.loads(settings.read_text())
    data["joint_order"][0] = "headYaw"
    write_json(settings, data)
    with pytest.raises(ValueError, match="20 K1 body joints"):
        register(context)
    assert not calls
