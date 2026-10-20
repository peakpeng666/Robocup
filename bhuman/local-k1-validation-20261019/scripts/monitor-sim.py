#!/usr/bin/env python3
"""Read resource counters of one already launched local SimRobot process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run", type=Path)
args = parser.parse_args()
pid = int((args.run / "pid.txt").read_text())
process = Path("/proc") / str(pid)
initial = (process / "stat").read_text().rsplit(")", 1)[1].split()[19]
maps = (process / "maps").read_text()
(args.run / "loaded-runtime-libraries.txt").write_text("\n".join(sorted({line.split()[-1] for line in maps.splitlines()
    if any(token in line for token in ["onnxruntime", "nvidia/", "libSimulatedRobot", "libSimRobotCore3"])})) + "\n")
samples = []
started = time.monotonic()
while time.monotonic() - started < 1200:
    try:
        fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[19] != initial:
            break
        row = {"monitor_wall_s": time.monotonic() - started,
               "cpu_s": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
               "rss_mib": int(fields[21]) * os.sysconf("SC_PAGE_SIZE") / 2**20,
               "threads": int(fields[17])}
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
        if gpu.returncode == 0:
            values = [float(x.strip()) for x in gpu.stdout.strip().split(",")]
            row.update(gpu_utilization_percent=values[0], gpu_total_memory_mib=values[1], gpu_temperature_c=values[2])
        samples.append(row)
        (args.run / "resources.json").write_text(json.dumps(samples, indent=2) + "\n")
    except (FileNotFoundError, ProcessLookupError):
        break
    time.sleep(5)
print(json.dumps({"resource_samples": len(samples), "run_dir": str(args.run)}))
