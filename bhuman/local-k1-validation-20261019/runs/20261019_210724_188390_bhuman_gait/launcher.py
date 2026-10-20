#!/usr/bin/env python3
"""Run the public B-Human K1 controller in local SimRobot, with bounded evidence."""
import argparse
from collections import defaultdict
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
REPO = BASE / "bhuman-local"
OFFICIAL = BASE.parent / "BHumanCodeRelease"
SIM = REPO / "Build/Linux/SimRobot/Release/SimRobot"


def digest(path):
    with path.open("rb") as stream:
        value = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def model_contract():
    paths = [
        "Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
        "Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
        "Config/Robots/Default/K1/walkingEngine.cfg",
        "Config/Robots/Default/K1/motorParameters.cfg",
        "Config/Robots/SimulatedK1/walkingEngine.cfg",
        "Config/Robots/SimulatedK1/motorParameters.cfg",
        "Config/Robots/SimulatedK1/odometryDataPreviewProvider.cfg",
        "Config/Locations/MField/setupPosesProvider.cfg",
        "Config/NeuralNets/Walk/K1_walk.onnx",
        "Config/NeuralNets/Walk/K1_kick_inner.onnx",
        "Config/NeuralNets/Walk/K1_kick_inner_soft.onnx",
        "Config/NeuralNets/GetUpEngine/K1.onnx",
        "Config/NeuralNets/GetUpEngine/K1_fast_standup.onnx",
        "Config/Scenes/Includes/K1/K1.rsi3",
        "Config/Robots/Default/K1/cameraResolution.cfg",
        "Config/NeuralNets/RobotBallPerceptor/ball_robot_544.onnx",
        "Config/NeuralNets/RobotBallPerceptor/ball_robot_640.onnx",
        "Src/Modules/Perception/MultiPerceptors/RobotBallPerceptor.cpp",
        "Src/Modules/Perception/MultiPerceptors/RobotBallPerceptor.h",
    ]
    result = {}
    for rel in paths:
        actual, expected = digest(REPO / rel), digest(OFFICIAL / rel)
        if actual != expected:
            raise RuntimeError("Public B-Human contract differs: " + rel)
        result[rel] = actual
    return result


def motion_command(motion, x=0, y=0, rotation=0):
    # The public Config/Scenes/Plots/Walk.con MotionRequest format.
    return (
        f"set representation:MotionRequest motion = {motion}; "
        f"walkSpeed = {{ rotation = {rotation}; translation = {{ x = {x}; y = {y}; }}; }}; "
        "walkTarget = { rotation = 0deg; translation = { x = 0; y = 0; }; }; "
        "keepTargetRotation = false; obstacleAvoidance = { avoidance = { x = 0; y = 0; }; path = []; }; "
        "targetOfInterest = []; sideWalkingRequest = allowed; shouldInterceptBall = false; "
        "shouldWalkOutOfBallLine = false; targetDirection = 0deg; kickType = rlKickDynamic; "
        "kickLength = 0; alignPrecisely = normal; odometryData = { rotation = 0; translation = { x = 0; y = 0; }; }; "
        "ballEstimate = { position = { x = 4000; y = 0; }; velocity = { x = 0; y = 0; }; radius = 50; "
        "covariance = { cols = [ { elems = [ 1, 0 ]; }, { elems = [ 0, 1 ]; } ]; }; }; "
        "ballEstimateTimestamp = 0; ballTimeWhenLastSeen = 0;"
    )


def summarize(run, mode, steps, exit_code):
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
    roster = ["robot5"] if mode == "gait" else ["robot1", "robot2", "robot3", "robot21", "robot22", "robot23"]
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
            "path_m_from_2hz_samples": sum(math.hypot(float(b["x_mm"])-float(a["x_mm"]), float(b["y_mm"])-float(a["y_mm"])) for a, b in zip(p, p[1:])) / 1000,
            "max_sampled_abs_roll_pitch_rad": max((max(abs(float(x["roll_rad"])), abs(float(x["pitch_rad"]))) for x in p), default=None),
            "all_samples_near_arena": bool(p) and all(abs(float(x["x_mm"])) < 10000 and abs(float(x["y_mm"])) < 7000 for x in p),
            "first_pose": p[0] if p else None, "last_pose": p[-1] if p else None,
        }
    games = records["game"]
    contacts = [x for x in records["contact"] if ".robots.robot" in x.get("robot", "")]
    ball_travel = sum(math.hypot(float(b["ball_x_mm"])-float(a["ball_x_mm"]), float(b["ball_y_mm"])-float(a["ball_y_mm"])) for a, b in zip(games, games[1:])) / 1000
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
    if mode == "gait":
        poses = physics["robot5"]
        for label, start, end in [("forward", 1000, 5000), ("left", 5000, 8000), ("turn", 8000, 12000), ("settled_stop", 13000, 15000)]:
            part = [p for p in poses if start <= int(p["tick"]) <= end]
            forward = left = yaw = 0.0
            for a, b in zip(part, part[1:]):
                dx, dy = (float(b["x_mm"])-float(a["x_mm"]))/1000, (float(b["y_mm"])-float(a["y_mm"]))/1000
                angle = float(a["yaw_rad"])
                forward += math.cos(angle)*dx + math.sin(angle)*dy
                left += -math.sin(angle)*dx + math.cos(angle)*dy
                yaw += math.remainder(float(b["yaw_rad"])-angle, 2*math.pi)
            gait_segments[label] = {"samples": len(part), "forward_m": forward, "left_m": left, "yaw_change_rad": yaw,
                                    "net_displacement_m": math.hypot(float(part[-1]["x_mm"])-float(part[0]["x_mm"]), float(part[-1]["y_mm"])-float(part[0]["y_mm"]))/1000 if len(part)>1 else None}
        checks.update({"no_fall_or_getup": robots["robot5"]["fall_frames"] == robots["robot5"]["getup_frames"] == 0,
                       "robot_traveled_over_1m": robots["robot5"]["path_m_from_2hz_samples"] > 1,
                       "all_gait_commands_dispatched": {1000, 5000, 8000, 12000}.issubset({int(x["tick"]) for x in records["command"]}),
                       "forward_response": gait_segments["forward"]["forward_m"] > 1.0,
                       "side_response": gait_segments["left"]["left_m"] > 0.3,
                       "turn_response": gait_segments["turn"]["yaw_change_rad"] > 0.3,
                       "settled_stop_under_10cm": gait_segments["settled_stop"]["net_displacement_m"] is not None and gait_segments["settled_stop"]["net_displacement_m"] < 0.1})
    else:
        checks.update({"ready_set_playing_observed": {1, 2, 3}.issubset({int(x["state"]) for x in games}),
                       "six_active_robots": bool(games) and all(int(x["robots"]) == 6 for x in games),
                       "all_robots_remain_near_arena": all(x["all_samples_near_arena"] for x in robots.values()),
                       "initialization_before_ready": any(int(x["state"]) == 0 and int(x["tick"]) >= 1000 for x in games)
                                                      and any(x.get("tick") == "1500" for x in records["command"]),
                       "robot_ball_contact_observed": bool(contacts), "ball_moved_over_30cm": ball_travel > 0.3,
                       "ball_percept_observed": sum(x["ball_seen_samples"] for x in robots.values()) > 0})
    result = {"status": "PASS" if all(checks.values()) else "FAIL", "mode": mode,
              "scope": "Public B-Human K1 controller in normal 3D SimRobot; local simulation only; not a full regulation match or hardware qualification",
              "requested_simulation_s": steps * 0.002, "checks": checks, "robots": robots,
              "game_states": sorted({int(x["state"]) for x in games}), "last_game": games[-1] if games else None,
              "ball_contacts_logged": len(contacts), "ball_path_m_from_2hz_samples": ball_travel, "errors": errors[:20],
              "gait_segments": gait_segments,
              "measurement_note": "Joint/pose finite counters run each available frame; trajectories sampled at 2 Hz. Ball path includes automatic-referee placement. Contacts are rate-limited at 10 Hz."}
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["gait", "match"])
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--build", choices=["Release", "Develop"], default="Release")
    parser.add_argument("--vision", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--ort-threads", type=int, help="Default: 8 for CPU vision, 1 for CUDA vision")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--unthrottled", action="store_true", help="Remove the official real-time pacing limit; physics timestep and cameras stay unchanged")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--record", action="store_true", help="Capture only SimRobot's own 3D framebuffer, then encode MP4")
    parser.add_argument("--timeout", type=int, help="Wall-clock timeout in seconds")
    args = parser.parse_args()
    seconds = args.seconds if args.seconds is not None else (30 if args.mode == "gait" else 120)
    if not (30 if args.mode == "gait" else 60) <= seconds <= 1800:
        parser.error("gait needs 30..1800 seconds; match needs 60..1800 seconds")
    if args.ort_threads is not None and not 1 <= args.ort_threads <= 32:
        parser.error("--ort-threads must be 1..32")
    if args.vision == "cuda" and args.build != "Release":
        parser.error("CUDA vision is currently validated for the Release build only")
    sim = REPO / "Build/Linux/SimRobot" / args.build / "SimRobot"
    if args.record and args.headless:
        parser.error("--record requires the simulator's visible 3D view")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not os.environ.get("DISPLAY"):
        parser.error("An X11/OpenGL display is required, including for normal camera rendering")
    if args.record and not shutil.which("ffmpeg"):
        parser.error("ffmpeg is required for recording")
    # Team message ports are shared on this host; serialize our launchers.
    lock = (BASE / ".bhuman-sim.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("Another local B-Human launcher is running; finish it first")
    protected = model_contract()
    stamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d_%H%M%S_%f")
    run = BASE / "runs" / (stamp + "_bhuman_" + args.mode)
    run.mkdir()
    for name in ["xdg-config", "xdg-cache", "frames"]:
        (run / name).mkdir()
    schedule = run / "schedule.txt"
    if args.mode == "gait":
        commands = [(0, "robot robot5"), (0, motion_command("stand")),
                    (1000, motion_command("walkAtRelativeSpeed", x=0.35)),
                    (5000, motion_command("walkAtRelativeSpeed", y=0.3)),
                    (8000, motion_command("walkAtRelativeSpeed", rotation=0.25)),
                    (12000, motion_command("stand"))]
        schedule.write_text("\n".join(str(tick) + " " + cmd for tick, cmd in commands) + "\n")
    else:
        # SetupPoses placement arrives asynchronously from robot debug responses.
        # Allow INITIAL to settle before the referee starts READY.
        schedule.write_text("1500 gc ready\n")
    if args.unthrottled:
        schedule.write_text("0 dt off\n" + schedule.read_text())
    scene = REPO / "Config/Scenes/K1" / ("BHumanLocalGait.ros3" if args.mode == "gait" else "BHumanLocalMatch.ros3")
    command = [str(sim)] + (["-noWindow"] if args.headless else []) + [str(scene)]
    env = dict(os.environ)
    env.update(BH_AUDIT="1", BH_AUDIT_STEPS=str(seconds * 500), BH_SIM_SCHEDULE=str(schedule),
               XDG_CONFIG_HOME=str(run / "xdg-config"), XDG_CACHE_HOME=str(run / "xdg-cache"),
               QT_QPA_PLATFORM="xcb", OMP_NUM_THREADS="2")
    for key in ["BH_SIM_VIEW", "BH_SIM_CAPTURE", "BH_ORT_THREADS", "BH_ORT_SPIN", "BH_PROFILE", "BH_VISION_CUDA", "BH_VISION_CAPTURE_INPUT"]:
        env.pop(key, None)
    env["LD_LIBRARY_PATH"] = str(REPO / "Util/onnxruntime/lib/Linux") + ":" + env.get("LD_LIBRARY_PATH", "")
    env["BH_ORT_THREADS"] = str(args.ort_threads or (1 if args.vision == "cuda" else 8))
    env["BH_ORT_SPIN"] = "0"
    runtime = {"vision": args.vision, "ort_threads": int(env["BH_ORT_THREADS"]), "ort_spin": 0, "real_time_pacing": not args.unthrottled}
    if args.vision == "cuda":
        from runtime_env import cuda_environment
        runtime.update(cuda_environment(env))
    if args.profile:
        env["BH_PROFILE"] = "1"
    if not args.headless:
        env["BH_SIM_VIEW"] = "RoboCup.robots.robot5" if args.mode == "gait" else "RoboCup"
    if args.record:
        env["BH_SIM_CAPTURE"] = str(run / "frames")
    metadata = {"schema": 2, "runtime": runtime, "recording": args.record, "build": args.build, "command": command, "cwd": str(REPO), "seconds": seconds, "mode": args.mode,
                "scenario": "Default", "launcher_sha256": digest(Path(__file__)),
                "official_source": "bhuman/BHumanCodeRelease@2e3374ba896da8288607f9a1881b876642fe18b8",
                "unchanged_public_files_sha256": protected, "simulator_sha256": digest(sim),
                "controller_sha256": digest(sim.parent / "libSimulatedRobot.so"),
                "scene_sha256": digest(scene), "schedule_sha256": digest(schedule),
                "scene_console_sha256": digest(scene.with_suffix(".con")),
                "robot_connected": False, "perception_mode": "normal rendered camera, not oracle or 2D"}
    (run / "launch.json").write_text(json.dumps(metadata, indent=2) + "\n")
    shutil.copy2(__file__, run / "launcher.py")
    shutil.copy2(BASE / "scripts/runtime_env.py", run / "runtime_env.py")
    shutil.copy2(scene, run / scene.name)
    shutil.copy2(scene.with_suffix(".con"), run / scene.with_suffix(".con").name)
    print("Run directory: " + str(run), flush=True)
    started = time.monotonic()
    timeout = args.timeout or seconds * 12 + 180
    with (run / "console.log").open("w") as log:
        proc = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (run / "pid.txt").write_text(str(proc.pid) + "\n")
        try:
            code = proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = 124
    (run / "execution.json").write_text(json.dumps({"exit_code": code, "wall_s": time.monotonic()-started, "timeout_s": timeout}, indent=2) + "\n")
    result = summarize(run, args.mode, seconds * 500, code)
    execution = json.loads((run / "execution.json").read_text())
    result["performance"] = {"wall_s": execution["wall_s"], "real_time_factor": seconds / execution["wall_s"],
                             "includes_startup_and_capture": True, "encoding_excluded": True}
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.record:
        frames = sorted((run / "frames").glob("frame-*.png"))
        video = run / ("bhuman-k1-" + args.mode + ".mp4")
        if len(frames) != seconds * 10:
            result["checks"]["complete_frame_capture"] = False
        else:
            with (run / "encode.log").open("w") as log:
                completed = subprocess.run(["ffmpeg", "-nostdin", "-y", "-framerate", "10", "-start_number", "1", "-i", str(run / "frames/frame-%06d.png"),
                                            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)], stdout=log, stderr=subprocess.STDOUT)
            result["checks"]["complete_frame_capture"] = completed.returncode == 0
            if completed.returncode == 0:
                result["video"] = str(video)
        result["status"] = "PASS" if all(result["checks"].values()) else "FAIL"
        (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(run / "result.json"), "video": result.get("video")}, ensure_ascii=False, indent=2))
    (BASE / ("last-bhuman-" + args.mode + ".json")).write_text(json.dumps({"run_dir": str(run), "status": result["status"]}, indent=2) + "\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
