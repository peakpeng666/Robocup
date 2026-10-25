#!/usr/bin/env python3
"""Save a timestamped GPU recovery check; never change the driver or reboot."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

FORGE = Path(__file__).resolve().parents[1]


def check(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'forge.gpu-recovery/1', 'status': 'FAIL',
              'at': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
              'driver_changed': False, 'robot_connected': False}
    for name, command in {
        'nvidia_smi': ['nvidia-smi', '--query-gpu=name,driver_version,gpu_recovery_action', '--format=csv,noheader'],
        'kernel': ['journalctl', '-k', '-b', '--no-pager'],
    }.items():
        proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
        (output / (name + '.log')).write_text(proc.stdout + proc.stderr)
        report[name] = {'exit_code': proc.returncode}
        if name == 'nvidia_smi':
            report[name]['summary'] = proc.stdout.strip()
    try:
        lib = ctypes.CDLL('libcuda.so.1')
        report['cuInit'] = lib.cuInit(0)
    except Exception as exc:
        report['cuInit_error'] = str(exc)
    code = '''import json,torch
torch.set_float32_matmul_precision('highest')
torch.manual_seed(16010)
cpu=torch.randn(256,256,dtype=torch.float32)
gpu=cpu.to('cuda')
actual=(gpu@gpu.T).cpu()
torch.cuda.synchronize()
reference=cpu@cpu.T
error=(actual-reference).abs().max().item()
ok=torch.allclose(actual,reference,atol=0.002,rtol=0.0001)
print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,'device':torch.cuda.get_device_name(0),'max_abs_error':error,'passed':ok}))
raise SystemExit(0 if ok else 1)
'''
    python = Path.home() / '.venvs/forge-mjlab/bin/python'
    proc = subprocess.run([str(python), '-B', '-c', code], capture_output=True, text=True, timeout=60)
    (output / 'torch-compute.log').write_text(proc.stdout + proc.stderr)
    report['torch_compute'] = {'exit_code': proc.returncode}
    if proc.returncode == 0:
        report['torch_compute']['result'] = json.loads(proc.stdout.strip())
    if report.get('cuInit') == 0 and proc.returncode == 0:
        report['status'] = 'PASS'
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d_%H%M%S_%f')
    result = check(args.output or FORGE / 'runs/gpu-recovery' / stamp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] == 'PASS' else 1)
