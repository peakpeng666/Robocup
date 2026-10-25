#!/usr/bin/env python3
"""Gait-mode audit summary for probe runs, ported from run-bhuman-k1.py summarize().

Parses a run directory's console.log AUDIT records and writes result.json with
the same gait check items as the baseline launcher, so a probe-off run can be
compared check-by-check against the baseline result.json. Stdlib only.

Usage: gait_audit.py <run_dir> <seconds> <exit_code>
"""
from collections import defaultdict
import json
import math
import re
import sys


def summarize(run_dir, seconds, exit_code):
    from pathlib import Path
    run = Path(run_dir)
    steps = seconds * 500
    lines = (run / "console.log").read_text(errors="replace").splitlines()
    records = defaultdict(list)
    for line in lines:
        match = re.match(r"AUDIT (\w+) (.*)", line)
        if match:
            records[match[1]].append(dict(re.findall(r"(\w+)=([^\s]+)", match[2])))
    physics = defaultdict(list)
    motion = defaultdict(list)
    perception = defaultdict(list)
    cognition = defaultdict(list)
    for row in records["physics"]:
        physics[row["robot"]].append(row)
    for name, target in [("motion", motion), ("perception", perception), ("cognition", cognition)]:
        for row in records[name]:
            target[(row.get("team"), row.get("player"))].append(row)
    roster = ["robot5"]
    robots = {}
    for name in roster:
        number = int(name[5:])
        identity = ("5", str(number)) if number < 20 else ("70", str(number - 20))
        p, m, v, c = physics[name], motion[identity], perception[identity], cognition[identity]
        camera_span = (int(v[-1]["image_time"]) - int(v[0]["image_time"])) / 1000 if len(v) > 1 else 0
        perceived_hz = (int(v[-1]["frames"]) - int(v[0]["frames"])) / camera_span if camera_span > 0 else 0
        longest_tilt_s = 0.0
        tilt_start = None
        for pose in p:
            tick = int(pose["tick"])
            if max(abs(float(pose["roll_rad"])), abs(float(pose["pitch_rad"]))) > 0.85:
                if tilt_start is None:
                    tilt_start = tick
                longest_tilt_s = max(longest_tilt_s, (tick - tilt_start) * 0.002)
            else:
                tilt_start = None
        robots[name] = {
            "physics_samples": len(p), "motion_samples": len(m),
            "perception_hz_over_sim_time": perceived_hz,
            "camera_sizes": sorted({(int(x["width"]), int(x["height"])) for x in v if "width" in x}),
            "longest_sampled_tilt_over_0_85rad_s": longest_tilt_s,
            "last_motion": m[-1] if m else None,
            "unique_camera_timestamps_sampled": len({x["image_time"] for x in p}),
            "perception_samples": len(v), "ball_seen_samples": sum(x["ball_status"] == "1" for x in v),
            "cognition_samples": len(c), "skills": sorted({int(x["skill"]) for x in c}),
            "walk_frames": max((int(x["walk_frames"]) for x in m), default=0),
            "fall_frames": max((int(x["fall_frames"]) for x in m), default=0),
            "getup_frames": max((int(x["getup_frames"]) for x in m), default=0),
            "nonfinite_physics_total": max((int(x["nonfinite_total"]) for x in p), default=0),
            "nonfinite_motion_total": max((int(x["nonfinite_total"]) for x in m), default=0),
            "path_m_from_2hz_samples": sum(math.hypot(float(b["x_mm"]) - float(a["x_mm"]), float(b["y_mm"]) - float(a["y_mm"])) for a, b in zip(p, p[1:])) / 1000,
            "max_sampled_abs_roll_pitch_rad": max((max(abs(float(x["roll_rad"])), abs(float(x["pitch_rad"]))) for x in p), default=None),
            "all_samples_near_arena": bool(p) and all(abs(float(x["x_mm"])) < 10000 and abs(float(x["y_mm"])) < 7000 for x in p),
            "first_pose": p[0] if p else None, "last_pose": p[-1] if p else None,
        }
    games = records["game"]
    errors = [line for line in lines if any(marker in line for marker in ["AUDIT ERROR", "Syntax Error", "Syntax error:", "Not allowed in this game state", "Assertion failed", "Segmentation fault"])]
    gait_segments = {}
    checks = {
        "process_exit_zero": exit_code == 0,
        "completed_requested_steps": any(int(x.get("steps", -1)) == steps for x in records["completed"]),
        "no_console_errors": not errors,
        "all_robots_reported": all(x["physics_samples"] >= 10 and x["motion_samples"] >= 10 for x in robots.values()),
        "all_robots_have_camera_perception_cognition": all(x["unique_camera_timestamps_sampled"] >= 10 and x["perception_samples"] > 0 and x["cognition_samples"] > 0 for x in robots.values()),
        "finite_all_recorded_frames": all(x["nonfinite_physics_total"] == 0 and x["nonfinite_motion_total"] == 0 for x in robots.values()),
        "all_robots_execute_walk": all(x["walk_frames"] > 500 for x in robots.values()),
    }
    launch = json.loads((run / "launch.json").read_text()) if (run / "launch.json").exists() else {}
    if launch.get("schema", 1) >= 2:
        vision_networks = [x for x in records["network"] if "/RobotBallPerceptor/" in x.get("model", "")]
        motion_networks = [x for x in records["network"] if any(part in x.get("model", "") for part in ["/Walk/", "/GetUpEngine/"])]
        provider = "CUDA" if launch["runtime"]["vision"] == "cuda" else "CPU"
        checks.update({"normal_camera_resolution": all(x["camera_sizes"] == [(544, 448)] for x in robots.values()),
                       "camera_perception_rate_at_least_50hz": all(50 <= x["perception_hz_over_sim_time"] <= 65 for x in robots.values()),
                       "vision_provider_matches_request": len(vision_networks) == len(roster) and all(x["provider"] == provider for x in vision_networks),
                       "motion_policies_still_cpu": len(motion_networks) >= len(roster) and all(x["provider"] == "CPU" for x in motion_networks),
                       "no_sampled_tilt_stuck_over_30s": all(x["longest_sampled_tilt_over_0_85rad_s"] <= 30 for x in robots.values())})
    poses = physics["robot5"]
    for label, start, end in [("forward", 1000, 5000), ("left", 5000, 8000), ("turn", 8000, 12000), ("settled_stop", 13000, 15000)]:
        part = [p for p in poses if start <= int(p["tick"]) <= end]
        forward = left = yaw = 0.0
        for a, b in zip(part, part[1:]):
            dx, dy = (float(b["x_mm"]) - float(a["x_mm"])) / 1000, (float(b["y_mm"]) - float(a["y_mm"])) / 1000
            angle = float(a["yaw_rad"])
            forward += math.cos(angle) * dx + math.sin(angle) * dy
            left += -math.sin(angle) * dx + math.cos(angle) * dy
            yaw += math.remainder(float(b["yaw_rad"]) - angle, 2 * math.pi)
        gait_segments[label] = {"samples": len(part), "forward_m": forward, "left_m": left, "yaw_change_rad": yaw,
                                "net_displacement_m": math.hypot(float(part[-1]["x_mm"]) - float(part[0]["x_mm"]), float(part[-1]["y_mm"]) - float(part[0]["y_mm"])) / 1000 if len(part) > 1 else None}
    checks.update({"no_fall_or_getup": robots["robot5"]["fall_frames"] == robots["robot5"]["getup_frames"] == 0,
                   "robot_traveled_over_1m": robots["robot5"]["path_m_from_2hz_samples"] > 1,
                   "all_gait_commands_dispatched": {1000, 5000, 8000, 12000}.issubset({int(x["tick"]) for x in records["command"]}),
                   "forward_response": gait_segments["forward"]["forward_m"] > 1.0,
                   "side_response": gait_segments["left"]["left_m"] > 0.3,
                   "turn_response": gait_segments["turn"]["yaw_change_rad"] > 0.3,
                   "settled_stop_under_10cm": gait_segments["settled_stop"]["net_displacement_m"] is not None and gait_segments["settled_stop"]["net_displacement_m"] < 0.1})
    result = {"status": "PASS" if all(checks.values()) else "FAIL", "mode": "gait",
              "scope": "Instrumented probe copy of the public B-Human K1 controller in normal 3D SimRobot; local simulation only",
              "requested_simulation_s": steps * 0.002, "checks": checks, "robots": robots,
              "game_states": sorted({int(x["state"]) for x in games}), "last_game": games[-1] if games else None,
              "errors": errors[:20],
              "gait_segments": gait_segments,
              "measurement_note": "Joint/pose finite counters run each available frame; trajectories sampled at 2 Hz."}
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: gait_audit.py <run_dir> <seconds> <exit_code>")
    outcome = summarize(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
    print(json.dumps({"status": outcome["status"], "checks": outcome["checks"]}, ensure_ascii=False, indent=2))
    sys.exit(0 if outcome["status"] == "PASS" else 1)
