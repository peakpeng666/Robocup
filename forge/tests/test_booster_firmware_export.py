"""Firmware numeric-dump parsing and conversion tests; no vendor code is run."""
import importlib.util
from pathlib import Path
import struct

import numpy as np
import pytest


SPEC = importlib.util.spec_from_file_location(
    "booster_firmware_export", Path(__file__).parents[1] / "tools/export_booster_firmware.py")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def record(name, values):
    values = np.asarray(values, dtype="<f8")
    return (struct.pack("<i", len(name)) + name.encode("ascii")
            + struct.pack("<ii", *values.shape) + values.tobytes(order="C"))


def identity_actor():
    tensors = {}
    previous = 690
    for layer, outputs in zip((0, 2, 4, 6), (512, 256, 128, 20)):
        weight = np.zeros((outputs, previous), dtype=np.float64)
        weight[0, 0] = 1
        tensors[f"actor.{layer}.weight"] = weight
        tensors[f"actor.{layer}.bias"] = np.zeros((outputs, 1))
        previous = outputs
    for name, value in (("_mean", 0), ("_var", 1), ("_std", 1)):
        tensors[f"obs_normalizer.{name}"] = np.full((1, 690), value, dtype=np.float64)
    tensors["obs_normalizer.count"] = np.zeros((1, 1))
    return tensors


def test_dump_preserves_serialized_row_order_and_record_boundaries():
    values = np.array([[1.25, -2.5, 3.75], [4.5, 5.25, -6.5]])
    data = record("actor.0.weight", values) + record("actor.0.bias", [[7.25], [-8.5]])
    tensors, layout = exporter.parse_dump(data)
    np.testing.assert_array_equal(tensors["actor.0.weight"], values)
    np.testing.assert_array_equal(tensors["actor.0.bias"], [[7.25], [-8.5]])
    assert layout[0]["storage"] == "row-major"
    assert layout[-1]["offset"] + layout[-1]["bytes"] == len(data)


@pytest.mark.parametrize("data", [
    b"", b"\x01", struct.pack("<i", -1), struct.pack("<i", 129),
    record("a", [[1]])[:-1], record("a", [[1]]) + b"\x00",
    record("a", [[1]]) + record("a", [[2]]),
    record("a", [[float("nan")]]), record("a", [[float("inf")]]),
    struct.pack("<i", 1) + b"a" + struct.pack("<ii", 4097, 1),
])
def test_malformed_or_nonfinite_dump_is_rejected(data):
    with pytest.raises(ValueError):
        exporter.parse_dump(data)


def test_nonidentity_normalizer_is_not_silently_ignored():
    tensors = identity_actor()
    tensors["obs_normalizer._mean"][0, 7] = 0.1
    with pytest.raises(ValueError, match="normalizer"):
        exporter.validate_actor(tensors)


def test_unrecognized_tensor_is_not_silently_ignored():
    tensors = identity_actor()
    tensors["extra"] = np.ones((1, 1))
    with pytest.raises(ValueError, match="exactly the 12"):
        exporter.validate_actor(tensors)


def test_onnx_keeps_negative_elu_branch_and_linear_output():
    import onnxruntime as ort

    tensors = identity_actor()
    tensors["actor.6.bias"][0, 0] = -2
    model = exporter.make_onnx(tensors)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    session = ort.InferenceSession(model.SerializeToString(), options, providers=["CPUExecutionProvider"])
    for value in (-2.0, 0.0, 3.0):
        obs = np.zeros((1, 690), dtype=np.float32)
        obs[0, 0] = value
        expected = value
        for _ in range(3):
            expected = np.expm1(expected) if expected < 0 else expected
        expected -= 2
        actual = session.run(None, {"observations": obs})[0]
        np.testing.assert_allclose(actual[0, 0], expected, atol=2e-6)
        np.testing.assert_array_equal(actual[0, 1:], np.zeros(19))
        np.testing.assert_allclose(actual, exporter.numpy_actor(tensors, obs), atol=2e-6)
