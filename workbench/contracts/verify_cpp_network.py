"""Check actual production C++ IN/OUT against the retained TorchScript and ONNX."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
import onnxruntime as ort


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', type=Path, required=True)
    ap.add_argument('--export-dir', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    inputs, outputs = {}, {}
    with a.csv.open() as stream:
        for row in csv.reader(stream):
            if row[0] == 'IN':
                inputs[row[2]] = [float(x) for x in row[3:]]
            elif row[0] == 'OUT':
                outputs[row[2]] = [float(x) for x in row[3:16]]
    assert len(inputs) >= 500 and inputs.keys() == outputs.keys(), 'missing paired production calls'
    x = np.array(list(inputs.values()), dtype=np.float32)
    actual = np.array([outputs[k] for k in inputs], dtype=np.float32)
    assert x.shape == (len(inputs), 344) and actual.shape == (len(inputs), 13)
    manifest = json.loads((a.export_dir / 'K1_actor_manifest.json').read_text())
    script = a.export_dir / 'K1_actor.pt'
    assert sha(script) == manifest['torchscript']['sha256']
    assert sha(a.model) == manifest['onnx']['sha256'], 'reference export and production ONNX identities differ'
    torch.set_num_threads(1)
    model = torch.jit.load(str(script), map_location='cpu').eval()
    with torch.inference_mode():
        scripted = model(torch.from_numpy(x)).numpy()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 1
    session = ort.InferenceSession(str(a.model), sess_options=opts, providers=['CPUExecutionProvider'])
    predicted = session.run(None, {session.get_inputs()[0].name: x})[0]
    checks = {}
    for name, y in [('torchscript', scripted), ('onnxruntime_cpu', predicted)]:
        checks[name] = {'pass': bool(np.isfinite(y).all() and np.isfinite(actual).all() and np.allclose(y, actual, atol=1e-5, rtol=1e-4)),
                        'max_absolute_error': float(np.abs(y - actual).max())}
    report = {'status': 'PASS' if all(v['pass'] for v in checks.values()) else 'FAIL',
              'samples': len(x), 'input_dim': 344, 'output_dim': 13, 'atol': 1e-5, 'rtol': 1e-4,
              'csv_sha256': sha(a.csv), 'onnx_sha256': sha(a.model), 'torchscript_sha256': sha(script),
              'checks': checks, 'scope': 'Actual desktop C++ IN/OUT; not ARM/CompiledNN/hardware execution'}
    a.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
