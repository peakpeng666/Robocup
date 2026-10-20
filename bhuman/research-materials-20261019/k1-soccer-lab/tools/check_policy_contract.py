#!/usr/bin/env python3
"""Inspect the upstream walk ONNX tensor contract without any robot connection.

Requires an independently installed onnxruntime. The production B-Human wrapper
conceals the ONNX batch dimension; its rank()==1 assertion is consistent with a
physical ONNX shape [batch,344], not evidence of a different graph interface.
Tensor shape alone does not validate normalization, history, joint order or gains.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    try:
        import onnxruntime as ort
    except ImportError:
        parser.error("install onnxruntime in an isolated environment before using this optional check")
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    def shape_ok(shape, last):
        return len(shape) == 2 and shape[-1] == last and (shape[0] == 1 or isinstance(shape[0], str) or shape[0] is None)
    valid = (len(inputs) == 1 and len(outputs) == 1 and shape_ok(inputs[0].shape, 344)
             and shape_ok(outputs[0].shape, 13) and inputs[0].type == outputs[0].type == "tensor(float)")
    print(json.dumps({"sha256":hashlib.sha256(args.model.read_bytes()).hexdigest(), "valid_tensor_shape":valid,
                      "inputs":[{"name":v.name,"shape":v.shape,"type":v.type} for v in inputs],
                      "outputs":[{"name":v.name,"shape":v.shape,"type":v.type} for v in outputs],
                      "limit":"shape check only; not authorization for hardware deployment"}, indent=2))
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
