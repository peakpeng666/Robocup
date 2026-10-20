"""Run finite official PPO training jobs sequentially and retain GPU telemetry."""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--name', default='local_benchmark')
parser.add_argument('--task', default='Isaac-Ant-Direct-v0')
parser.add_argument('--envs', type=int, default=4096)
parser.add_argument('--torch-threads', type=int, default=1)
parser.add_argument('--kit-threads', type=int, default=8)
parser.add_argument('--iterations', type=int, default=40)
parser.add_argument('--timeout', type=int, default=600)
args = parser.parse_args()
lab_root = Path(__file__).resolve().parents[2]
out = lab_root / 'logs' / 'local_benchmarks' / (time.strftime('%Y%m%d_%H%M%S') + '_' + args.name)
out.mkdir(parents=True, exist_ok=False)
log_path = out / f'{args.name}.log'
env = os.environ.copy()
env.update(ISAACLAB_TORCH_THREADS=str(args.torch_threads), ISAACLAB_KIT_THREADS=str(args.kit_threads))
command = [str(lab_root / 'lab.sh'), 'train', '--task', args.task, '--num_envs', str(args.envs),
           '--max_iterations', str(args.iterations), '--seed', '42', '--run_name', args.name]
samples = []
started = time.monotonic()
with log_path.open('w') as log:
    proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)
    try:
        while proc.poll() is None:
            if time.monotonic() - started > args.timeout:
                raise TimeoutError(f'Run exceeded {args.timeout} seconds')
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                values = result.stdout.strip().splitlines()[0].split(',')
                try:
                    gpu, mem, temp, watts = map(float, values)
                    samples.append({'elapsed_s': round(time.monotonic()-started, 2), 'gpu_pct': gpu,
                                    'memory_mib': mem, 'temperature_c': temp, 'power_w': watts})
                except ValueError:
                    pass
            time.sleep(1)
    except BaseException:
        import signal
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        raise
text = re.sub(r'\x1b\[[0-9;]*m', '', log_path.read_text(errors='replace'))
speeds = [int(v) for v in re.findall(r'Computation:\s+(\d+)\s+steps/s', text)]
measured = speeds[5:] if len(speeds)>5 else speeds
result = {'name':args.name, 'task':args.task, 'num_envs':args.envs,
          'torch_threads':args.torch_threads, 'kit_threads':args.kit_threads,
          'iterations':args.iterations, 'seed':42, 'exit_code':proc.returncode,
          'wall_s':round(time.monotonic()-started, 2), 'iteration_steps_per_s':speeds,
          'median_steps_per_s':statistics.median(measured) if measured else None,
          'mean_steps_per_s':round(statistics.mean(measured)) if measured else None,
          'max_gpu_utilization_pct':max((s['gpu_pct'] for s in samples), default=None),
          'max_gpu_memory_mib':max((s['memory_mib'] for s in samples), default=None),
          'max_gpu_temperature_c':max((s['temperature_c'] for s in samples), default=None),
          'gpu_samples':samples, 'log':str(log_path)}
(out / f'{args.name}.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'gpu_samples','iteration_steps_per_s'}}, indent=2), flush=True)
raise SystemExit(proc.returncode if proc.returncode else (0 if speeds else 2))
