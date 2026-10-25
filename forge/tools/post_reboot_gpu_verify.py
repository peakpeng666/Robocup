#!/usr/bin/env python3
"""One saved verification after an explicitly authorized host reboot; no hardware robot IO."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

FORGE = Path(__file__).resolve().parents[1]


def execute(command, output, timeout):
    proc = subprocess.run(command, cwd=FORGE, capture_output=True, text=True, timeout=timeout)
    output.write_text(proc.stdout + proc.stderr)
    return {'command': command, 'exit_code': proc.returncode, 'log': str(output)}


def verify(checkpoint):
    checkpoint = Path(checkpoint).resolve(strict=True)
    before = json.loads((checkpoint / 'reboot-checkpoint.json').read_text())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if boot == before['boot_id']:
        return {'status': 'WAITING_FOR_REBOOT', 'reason': 'Current boot is the saved faulty boot; no GPU work launched.'}
    output = checkpoint / 'after-reboot' / datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True)
    report = {'schema': 'forge.post-reboot-verification/1', 'status': 'FAIL', 'boot_id': boot,
              'previous_boot_id': before['boot_id'], 'output': str(output), 'robot_connected': False,
              'display': os.environ.get('DISPLAY'), 'checks': {}}
    python = str(Path.home() / '.venvs/forge/bin/python')
    try:
        core = execute([python, '-B', str(FORGE / 'tools/check_gpu_recovery.py'), '--output', str(output / 'core')],
                       output / 'core.log', 120)
        report['checks']['cuda_compute'] = core
        if core['exit_code'] != 0:
            raise RuntimeError('CUDA driver/compute check failed; no further GPU work launched')
        gym_code = '''import isaacgym,json,torch
x=torch.full((128,128),2.,device='cuda')
y=x@x
torch.cuda.synchronize()
ok=bool(torch.all(y==512).item())
print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,'passed':ok}))
raise SystemExit(0 if ok else 1)
'''
        env_sh = FORGE.parent / 'bhuman/k1-training/scripts/env.sh'
        report['checks']['bh_gym_compute'] = execute(
            ['bash', '-c', 'source "$0" && exec "$BH_PY" -B -c "$1"', str(env_sh), gym_code],
            output / 'bh-gym.log', 120)
        sim_code = '''import json,sys
from pathlib import Path
from forge import arena,match,packs,util
out=Path(sys.argv[1])
a=arena.Arena('gpu-recovery-'+util.stamp())
a.materialize();a.flash(5,packs.BASELINE_ID);a.flash(70,packs.BASELINE_ID)
r=match.run_match(a,seconds=30,case='motion-basic-v1',vision='cuda',record=True,timeout=180,tag='gpu-recovery-official')
log=(Path(r['run'])/'console.log').read_text()
observed='AUDIT network provider=CUDA' in log
report={'run':r['run'],'execution_status':r['execution_status'],'quality_status':r['status'],'cuda_provider_observed':observed,'protected':match.foundation_contract()}
(out/'simrobot-result.json').write_text(json.dumps(report,indent=2)+'\\n')
print(json.dumps(report))
raise SystemExit(0 if r['execution_status']=='PASS' and observed else 1)
'''
        report['checks']['simrobot_cuda_camera'] = execute([python, '-B', '-c', sim_code, str(output)],
                                                          output / 'simrobot.log', 240)
        if all(v['exit_code'] == 0 for v in report['checks'].values()):
            report['status'] = 'PASS'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        (checkpoint / 'gpu-after-reboot-latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        entry = Path(before['startup_entry'])
        marker = 'X-Forge-Recovery-Id=' + before['recovery_id']
        if entry.is_file() and marker in entry.read_text():
            saved = entry.read_text()
            (output / 'startup-entry-before-disable.desktop').write_text(saved)
            entry.write_text(saved + '\nHidden=true\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--startup-delay', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.startup_delay <= 30:
        parser.error('startup delay must be within 0..30 seconds')
    if args.startup_delay:
        time.sleep(args.startup_delay)
    result = verify(args.checkpoint)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] in ('PASS', 'WAITING_FOR_REBOOT') else 1)
