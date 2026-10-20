#!/usr/bin/env python3
"""Additional long-match evidence from the existing per-robot audit log."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run", type=Path)
args = parser.parse_args()
run = args.run.resolve()
result = json.loads((run / "result.json").read_text())
execution = json.loads((run / "execution.json").read_text())
episodes = defaultdict(list)
open_episode = {}
transitions = []
previous_state = None
last_game = None
playing_seconds = 0.0
sim_s = 0.0
for line in (run / "console.log").read_text().splitlines():
    match = re.match(r"AUDIT (\w+) (.*)", line)
    if not match:
        continue
    kind = match[1]
    row = dict(re.findall(r"(\w+)=([^\s]+)", match[2]))
    if kind in ["physics", "game"]:
        sim_s = int(row["tick"]) * 0.002
    if kind == "game":
        if last_game and last_game["state"] == "3":
            playing_seconds += (int(row["tick"]) - int(last_game["tick"])) * 0.002
        state = (row["state"], row["score_a"], row["score_b"], row["first_half"])
        if state != previous_state:
            transitions.append({"sim_s": sim_s, **row})
        previous_state, last_game = state, row
    elif kind == "motion":
        identity = row["team"] + ":" + row["player"]
        phase = int(row["phase"])
        if phase in [3, 4]:
            if identity not in open_episode:
                open_episode[identity] = {"start_sim_s_approx": sim_s, "observed_phases": [], "recovered": False}
            episode = open_episode[identity]
            if phase not in episode["observed_phases"]:
                episode["observed_phases"].append(phase)
        elif phase in [1, 2] and row["stable"] == "1" and identity in open_episode:
            episode = open_episode.pop(identity)
            episode.update(recovered=True, recovered_sim_s_approx=sim_s,
                           duration_s_approx=sim_s - episode["start_sim_s_approx"], recovered_phase=phase)
            episodes[identity].append(episode)
for identity, episode in open_episode.items():
    episodes[identity].append(episode)
resources = json.loads((run / "resources.json").read_text()) if (run / "resources.json").exists() else []
resource_summary = {}
if len(resources) > 1:
    elapsed = resources[-1]["monitor_wall_s"] - resources[0]["monitor_wall_s"]
    resource_summary = {"sample_count": len(resources), "monitor_span_wall_s": elapsed,
                        "mean_cpu_core_equivalents_during_monitor": (resources[-1]["cpu_s"] - resources[0]["cpu_s"]) / elapsed,
                        "peak_process_rss_mib": max(x["rss_mib"] for x in resources),
                        "peak_total_gpu_memory_mib": max(x.get("gpu_total_memory_mib", 0) for x in resources),
                        "median_total_gpu_utilization_percent": statistics.median(x.get("gpu_utilization_percent", 0) for x in resources),
                        "max_gpu_temperature_c": max(x.get("gpu_temperature_c", 0) for x in resources)}
summary = {"run_dir": str(run), "status_from_launcher": result["status"],
           "simulated_seconds": result["requested_simulation_s"], "wall_seconds": execution["wall_s"],
           "real_time_factor": result["requested_simulation_s"] / execution["wall_s"],
           "playing_seconds_approx": playing_seconds, "final_game": last_game,
           "transitions": transitions, "fall_getup_episodes_sampled": dict(episodes),
           "all_observed_episodes_recovered": (not open_episode) if any(episodes.values()) else None,
           "recovery_exercised": any(episodes.values()),
           "all_robots_end_stable_stand_or_walk": all(int(x["last_motion"]["phase"]) in [1, 2] and x["last_motion"]["stable"] == "1" for x in result["robots"].values()),
           "resources": resource_summary,
           "limits": ["Motion phase episodes are sampled at 2 Hz; times are approximate, with roughly 0.5 s resolution.",
                      "Cumulative fall/getup/finite counters are collected every available motion frame.",
                      "GPU utilization/memory include the desktop and other GPU users; RSS is this SimRobot process only.",
                      "Total simulation time includes INITIAL, READY, SET, PLAYING and other referee states, not just active play.",
                      "Wall time includes simulator startup, shutdown, and spectator capture; subsequent MP4 encoding is excluded."]}
(run / "long-analysis.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
