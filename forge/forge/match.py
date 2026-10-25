"""Team-vs-team SimRobot matches in an arena, with per-team evidence.

The launch environment, referee schedule, lock and recording follow the validated
launcher ``bhuman/local-k1-validation-20261019/scripts/run-bhuman-k1.py``; the only
difference is ``cwd = arena root`` so the flashed per-team configuration is loaded.
Normal rendered-camera perception is kept (no oracle percepts, no 2D mode).
"""
from __future__ import annotations

import importlib.util
import math
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from . import arena as arena_mod, packs, paths, recovery, runtime as runtime_mod, scenarios, strategies, util
from .locking import exclusive_simulation

FIRST_TEAM_ROBOTS = ("robot1", "robot2", "robot3")
SECOND_TEAM_ROBOTS = ("robot21", "robot22", "robot23")
ROBOTS_PER_TEAM = len(FIRST_TEAM_ROBOTS)
OFFICIAL_MOTION_SUFFIX = {"walk": "/NeuralNets/Walk/K1_walk.onnx", "kick": "/NeuralNets/Walk/K1_kick_inner.onnx",
                          "kick_soft": "/NeuralNets/Walk/K1_kick_inner_soft.onnx"}
PROTECTED = [
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


class MatchError(RuntimeError):
    pass


def foundation_contract() -> dict:
    """The validated launcher's protection: bhuman-local equals the official release."""
    result = {}
    for relative in PROTECTED:
        local, official = util.sha256_file(paths.BH_LOCAL / relative), util.sha256_file(paths.BH_OFFICIAL / relative)
        if local != official:
            raise MatchError("bhuman-local 与官方发布不一致: " + relative)
        result[relative] = local
    return result


def _cuda_environment(env):
    spec = importlib.util.spec_from_file_location("bh_runtime_env", paths.BH_VALIDATION / "scripts/runtime_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cuda_environment(env)


@exclusive_simulation(MatchError)
def run_match(arena: arena_mod.Arena, seconds: int = 120, record: bool = True, unthrottled: bool = True,
              vision: str = "cuda", timeout: int | None = None, tag: str = "match", on_line=None,
              case: str = "match", kickoff_team: int | None = None, behavior_readback: bool = False) -> dict:
    if case not in ("match", scenarios.MOTION_ID, recovery.RECOVERY_ID):
        raise MatchError("未知的 SimRobot 验证场景")
    if ((case == "match" and not 60 <= seconds <= 1800)
            or (case == scenarios.MOTION_ID and seconds != 30)
            or (case == recovery.RECOVERY_ID and seconds != 60)):
        raise MatchError("比赛时长需在 60..1800 秒；固定指令运控场景为 30 秒；前后跌倒恢复场景为 60 秒")
    if kickoff_team is not None and kickoff_team not in arena_mod.TEAM_NUMBERS:
        raise MatchError("开球队号无效")
    if vision not in ("cuda", "cpu"):
        raise MatchError("vision 必须是 cuda 或 cpu")
    if not os.environ.get("DISPLAY"):
        raise MatchError("缺少 DISPLAY：正常相机渲染需要 X11/OpenGL，不能静默降级为真值或 2D")
    if record and not shutil.which("ffmpeg"):
        raise MatchError("录像需要 ffmpeg")
    flash_report = arena.verify()
    if flash_report["status"] != "PASS":
        raise MatchError("刷写回读校验未通过，拒绝开赛: "
                         + ", ".join(k for k, v in flash_report["checks"].items() if not v))
    protected = foundation_contract()
    change = arena_mod.variant_change_class(arena.source)
    flash_report["variant_change"] = change
    if not change.get("baseline_compatible", change["additive"]):
        raise MatchError("该源码变体修改了已有源码（" + ", ".join(change["modified_existing"][:5]) + "）：两队共享同一控制器库，"
                         "未满足基线兼容守卫。仅允许新增模块，或源码内固定 hash 审核通过的默认关闭仿真扩展。")
    return _run_locked(arena, seconds, record, unthrottled, vision, timeout, tag, protected, flash_report, on_line,
                       case, kickoff_team, behavior_readback)


def _run_locked(arena, seconds, record, unthrottled, vision, timeout, tag, protected, flash_report, on_line,
                case="match", kickoff_team=None, behavior_readback=False):
    is_motion = case == scenarios.MOTION_ID
    is_recovery = case == recovery.RECOVERY_ID
    single_robot = is_motion or is_recovery
    run = paths.RUNS / ("recovery" if is_recovery else "motion" if is_motion else "matches") / f"{util.stamp()}_{util.safe_name(tag, 32)}"
    run.mkdir(parents=True)
    for name in ("xdg-config", "xdg-cache", "frames"):
        (run / name).mkdir()
    scene, console = arena.write_motion_scene(run.name) if single_robot else arena.write_scene(run.name)
    roster = {"robot5": (5, 5)} if single_robot else match_roster()
    schedule = run / "schedule.txt"
    commands = recovery.plan() if is_recovery else scenarios.motion_plan() if is_motion else [(1500, "gc ready")]
    if unthrottled:
        commands.insert(0, (0, "dt off"))
    if kickoff_team is not None:
        commands.insert(0, (0, "gc kickOff " + ("firstTeam" if kickoff_team == 5 else "secondTeam")))
    expected_parameters = []
    if behavior_readback:
        requests, expected_parameters = strategies.runtime_requests(arena, run, roster)
        commands.extend(requests)
    commands.sort(key=lambda item: item[0])
    schedule.write_text("".join(f"{tick} {command}\n" for tick, command in commands))
    simulator = arena.binary
    command = [str(simulator), str(scene)]
    env = dict(os.environ)
    env.update(BH_AUDIT="1", BH_AUDIT_STEPS=str(seconds * 500), BH_SIM_SCHEDULE=str(schedule),
               XDG_CONFIG_HOME=str(run / "xdg-config"), XDG_CACHE_HOME=str(run / "xdg-cache"),
               QT_QPA_PLATFORM="xcb", OMP_NUM_THREADS="2")
    for key in ("BH_SIM_VIEW", "BH_SIM_CAPTURE", "BH_ORT_THREADS", "BH_ORT_SPIN", "BH_PROFILE", "BH_VISION_CUDA",
                "BH_VISION_CAPTURE_INPUT", "BH_SIM_CAPTURE_FORMAT"):
        env.pop(key, None)
    env["LD_LIBRARY_PATH"] = str(arena.source / "Util/onnxruntime/lib/Linux") + ":" + env.get("LD_LIBRARY_PATH", "")
    env["BH_ORT_THREADS"] = "1" if vision == "cuda" else "8"
    env["BH_ORT_SPIN"] = "0"
    runtime = {"vision": vision, "ort_threads": int(env["BH_ORT_THREADS"]), "real_time_pacing": not unthrottled}
    if vision == "cuda":
        runtime.update(_cuda_environment(env))
    env["BH_SIM_VIEW"] = "RoboCup"
    if record:
        env["BH_SIM_CAPTURE"] = str(run / "frames")
        env["BH_SIM_CAPTURE_FORMAT"] = "jpeg"
    active_teams = {team for team, player in roster.values()}
    teams = {str(t): r for t, r in arena.flashed().items() if t in active_teams}
    launch = {
        "schema": "forge.match/1", "run": str(run), "arena": arena.name, "arena_root": str(arena.root),
        "command": command, "cwd": str(arena.root), "seconds": seconds, "runtime": runtime, "recording": record,
        "teams": {t: {"pack_id": r["pack_id"], "pack_kind": r["pack_kind"], "scenario": r["scenario"]}
                  for t, r in teams.items()},
        "source": str(arena.source), "variant_change": flash_report["variant_change"],
        "simulator_sha256": util.sha256_file(simulator),
        "controller_sha256": util.sha256_file(simulator.parent / "libSimulatedRobot.so"),
        "core3_sha256": util.sha256_file(simulator.parent / "libSimRobotCore3.so"),
        "scene_sha256": util.sha256_file(scene), "schedule_sha256": util.sha256_file(schedule),
        "foundation_protected_sha256": protected, "flash_readback": flash_report,
        "robot_connected": False, "perception_mode": "normal rendered camera, not oracle or 2D",
        "at": util.now_iso(),
        "case": case, "kickoff_team": kickoff_team, "roster": roster,
        "expected_behavior_parameters": expected_parameters,
        "pack_snapshots": {t: packs.load(r["pack_id"]) for t, r in teams.items()},
        "runner_sha256": util.sha256_file(__file__), "scenarios_sha256": util.sha256_file(scenarios.__file__),
        "recovery_assessor_sha256": util.sha256_file(recovery.__file__),
    }
    util.write_json(run / "launch.json", launch)
    shutil.copy2(scene, run / scene.name)
    shutil.copy2(console, run / console.name)
    timeout = timeout or seconds * 12 + 180
    expected_products = {"SimRobot": {"path": str(simulator.resolve()), "sha256": launch["simulator_sha256"]},
                         "libSimulatedRobot.so": {"path": str((simulator.parent / "libSimulatedRobot.so").resolve()),
                                                   "sha256": launch["controller_sha256"]},
                         "libSimRobotCore3.so": {"path": str((simulator.parent / "libSimRobotCore3.so").resolve()),
                                                "sha256": launch["core3_sha256"]}}
    loaded_products = {}

    def observe_output(line):
        if set(loaded_products) != set(expected_products):
            try:
                pid = int((run / "pid.txt").read_text().strip())
                snapshot = read_loaded_products(pid, expected_products)
                loaded_products.update(snapshot)
            except (OSError, ValueError):
                pass  # A missing runtime readback is a failed check below.
        if on_line and (not line.startswith("AUDIT ") or line.startswith("AUDIT game")):
            on_line(line)

    execution = runtime_mod.stream_process(command, cwd=arena.root, env=env, directory=run, timeout=timeout,
                                          on_line=observe_output)
    loaded_identity = {"expected": expected_products, "loaded": loaded_products,
                       "ok": loaded_products_match(expected_products, loaded_products)}
    util.write_json(run / "runtime-libraries.json", loaded_identity)
    wall = execution["wall_s"]
    util.write_json(run / "execution.json", execution)
    result = summarize(run, seconds * 500, execution["exit_code"], teams, arena.config,
                       roster=roster, required_game_states={3} if single_robot else {1, 2, 3})
    result["runtime_libraries"] = loaded_identity
    result["checks"]["runtime_executable_controller_core3_identity"] = loaded_identity["ok"]
    execution_check_names = set(result["checks"]) | {"runtime_behavior_parameters", "kickoff_command_dispatched", "complete_frame_capture"}
    result["case"] = case
    audit_records = parse_audit((run / "console.log").read_text(errors="replace").splitlines())
    result["recovery"] = recovery.assess(audit_records, roster, forced=is_recovery)
    if is_recovery:
        result["checks"].update(result["recovery"]["checks"])
    else:
        result["checks"]["no_failed_recovery_observed"] = result["recovery"]["conclusion"] in ("PASS", "NOT_EXERCISED")
    # Keep execution validity separate from recovery quality. No observed fall
    # means NOT_EXERCISED, never proof that the controller can get up.
    if is_motion:
        commands_seen = parse_audit((run / "console.log").read_text(errors="replace").splitlines())["command"]
        result["checks"].update(scenarios.motion_checks(result, commands_seen))
    if behavior_readback:
        result["behavior_readback"] = strategies.verify_runtime(expected_parameters)
        result["checks"]["runtime_behavior_parameters"] = result["behavior_readback"]["ok"]
    if kickoff_team is not None:
        first_command = "gc kickOff " + ("firstTeam" if kickoff_team == 5 else "secondTeam")
        result["checks"]["kickoff_command_dispatched"] = any(
            row.get("text") == first_command for row in parse_audit((run / "console.log").read_text(errors="replace").splitlines())["command"])
    result["status"] = "PASS" if all(result["checks"].values()) else "FAIL"
    result["run"] = str(run)
    result["tag"] = tag
    result["started_at"] = launch.get("at") or util.now_iso()
    result["performance"] = {"wall_s": wall, "real_time_factor": seconds / wall if wall else None,
                             "includes_startup_and_capture": True, "encoding_excluded": True}
    if record:
        recording = encode_recording(run, seconds * 10)
        result["recording"] = recording
        if recording["encoded"]:
            result["video"] = recording["video"]
        result["checks"]["complete_frame_capture"] = recording["complete"] and recording["encoded"]
        result["status"] = "PASS" if all(result["checks"].values()) else "FAIL"
    result["execution_status"] = "PASS" if all(v for k, v in result["checks"].items() if k in execution_check_names) else "FAIL"
    util.write_json(run / "result.json", result)
    return result


def read_loaded_products(pid: int, expected: dict) -> dict:
    """Observe mapped executable/Core3/controller, not just files at intended paths."""
    maps = Path(f"/proc/{pid}/maps").read_text()
    result = {}
    seen = set()
    for row in maps.splitlines():
        columns = row.split(None, 5)
        if len(columns) != 6 or not columns[5].startswith("/"):
            continue
        address, permissions, offset, device, inode, filename = columns
        deleted = filename.endswith(" (deleted)")
        filename = filename.removesuffix(" (deleted)")
        name = Path(filename).name
        key = (name, filename, inode, device)
        if name not in expected or key in seen:
            continue
        seen.add(key)
        entry = {"path": filename, "inode": int(inode), "device": device, "deleted": deleted}
        try:
            path = Path(filename)
            stat = path.stat()
            entry.update(sha256=util.sha256_file(path),
                         same_inode=stat.st_ino == int(inode) and
                         f"{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}" == device)
        except OSError:
            entry.update(sha256=None, same_inode=False)
        result.setdefault(name, []).append(entry)
    return result


def loaded_products_match(expected: dict, loaded: dict) -> bool:
    if set(expected) != set(loaded):
        return False
    for name, wanted in expected.items():
        rows = loaded[name]
        if len(rows) != 1:
            return False
        row = rows[0]
        if (row.get("deleted") or not row.get("same_inode") or row.get("path") != wanted["path"]
                or row.get("sha256") != wanted["sha256"]):
            return False
        path = Path(wanted["path"])
        if not path.is_file() or util.sha256_file(path) != wanted["sha256"]:
            return False
    return True


def encode_recording(run: Path, expected_frames: int) -> dict:
    """Record capture hashes and create a viewing copy; retain all source frames."""
    frames = sorted((run / "frames").glob("frame-*.jpg"))
    manifest = {f.name: util.sha256_file(f) for f in frames}
    complete = set(manifest) == {f"frame-{i:06d}.jpg" for i in range(1, expected_frames + 1)}
    util.write_json(run / "frames-manifest.json", {"sha256": manifest, "expected_frames": expected_frames,
                                                 "complete": complete})
    recording = {"frames": str(run / "frames"), "manifest": str(run / "frames-manifest.json"),
                 "manifest_sha256": util.sha256_file(run / "frames-manifest.json"),
                 "captured_frames": len(frames), "expected_frames": expected_frames,
                 "complete": complete, "encoded": False, "source_frames_retained": True}
    if complete:
        video = run / "match.mp4"
        with (run / "encode.log").open("w") as log:
            encoded = subprocess.run(["ffmpeg", "-nostdin", "-y", "-framerate", "10", "-start_number", "1",
                                      "-i", str(run / "frames/frame-%06d.jpg"), "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                                      "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                                      str(video)], stdout=log, stderr=subprocess.STDOUT)
        recording["encoded"] = encoded.returncode == 0 and video.is_file() and video.stat().st_size > 0
        recording["encode_exit_code"] = encoded.returncode
        if recording["encoded"]:
            recording.update(video=str(video), video_sha256=util.sha256_file(video))
    util.write_json(run / "recording.json", recording)
    return recording


# ---------------------------------------------------------------- evidence

_AUDIT = re.compile(r"AUDIT (\w+) (.*)")
_KV = re.compile(r"(\w+)=([^\s]+)")


def parse_audit(lines):
    records = defaultdict(list)
    for line in lines:
        match = _AUDIT.match(line)
        if match:
            row = dict(_KV.findall(match[2]))
            if match[1] == "command" and " text=" in match[2]:
                row["text"] = match[2].split(" text=", 1)[1]
            records[match[1]].append(row)
    return records


def _fall_episodes(samples):
    episodes, previous, rising = 0, 0, False
    for row in samples:
        value = int(row.get("fall_frames", 0))
        if value > previous and not rising:
            episodes += 1
        rising = value > previous
        previous = value
    return episodes


def match_roster():
    roster = {name: (5, i + 1) for i, name in enumerate(FIRST_TEAM_ROBOTS)}
    roster.update({name: (70, i + 1) for i, name in enumerate(SECOND_TEAM_ROBOTS)})
    return roster


def summarize(run: Path, steps: int, exit_code, teams: dict, config_root: Path | None = None,
              *, roster=None, required_game_states=None) -> dict:
    lines = (run / "console.log").read_text(errors="replace").splitlines()
    records = parse_audit(lines)
    physics, motion, perception, cognition = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for row in records["physics"]:
        physics[row["robot"]].append(row)
    for name, target in (("motion", motion), ("perception", perception), ("cognition", cognition)):
        for row in records[name]:
            target[(row.get("team"), row.get("player"))].append(row)
    first, second = arena_mod.TEAM_NUMBERS
    roster = match_roster() if roster is None else roster
    required_game_states = {1, 2, 3} if required_game_states is None else required_game_states
    team_counts = Counter(team for team, player in roster.values())
    robots = {}
    for name, (team, player) in roster.items():
        key = (str(team), str(player))
        p, m, v, c = physics[name], motion[key], perception[key], cognition[key]
        span = (int(v[-1]["image_time"]) - int(v[0]["image_time"])) / 1000 if len(v) > 1 else 0
        tilt, tilt_start = 0.0, None
        for pose in p:
            tick = int(pose["tick"])
            if max(abs(float(pose["roll_rad"])), abs(float(pose["pitch_rad"]))) > 0.85:
                tilt_start = tick if tilt_start is None else tilt_start
                tilt = max(tilt, (tick - tilt_start) * 0.002)
            else:
                tilt_start = None
        robots[name] = {
            "team": team, "player": player,
            "physics_samples": len(p), "motion_samples": len(m), "perception_samples": len(v), "cognition_samples": len(c),
            "perception_hz": (int(v[-1]["frames"]) - int(v[0]["frames"])) / span if span > 0 else 0,
            "camera_sizes": sorted({(int(x["width"]), int(x["height"])) for x in v if "width" in x}),
            "unique_camera_timestamps": len({x["image_time"] for x in p}),
            "ball_seen_samples": sum(x.get("ball_status") == "1" for x in v),
            "walk_frames": max((int(x["walk_frames"]) for x in m), default=0),
            "fall_frames": max((int(x["fall_frames"]) for x in m), default=0),
            "getup_frames": max((int(x["getup_frames"]) for x in m), default=0),
            "fall_episodes_sampled": _fall_episodes(m),
            "nonfinite_total": max([int(x["nonfinite_total"]) for x in p + m] or [0]),
            "path_m": sum(math.hypot(float(b["x_mm"]) - float(a["x_mm"]), float(b["y_mm"]) - float(a["y_mm"]))
                          for a, b in zip(p, p[1:])) / 1000,
            "longest_tilt_s": tilt,
            "near_arena": bool(p) and all(abs(float(x["x_mm"])) < 10000 and abs(float(x["y_mm"])) < 7000 for x in p),
            "trajectory": [[int(x["tick"]), float(x["x_mm"]), float(x["y_mm"]), float(x["yaw_rad"])] for x in p],
            "skill_samples": dict(Counter(scenarios.SKILLS[int(x["skill"])] if 0 <= int(x["skill"]) < len(scenarios.SKILLS)
                                           else "unknown" for x in c)),
        }
    games = records["game"]
    contacts = [x for x in records["contact"] if ".robots.robot" in x.get("robot", "")]
    contact_by_team = Counter(roster.get(x["robot"].rsplit(".", 1)[-1], (None,))[0] for x in contacts)
    ball_track = [[int(g["tick"]), float(g["ball_x_mm"]), float(g["ball_y_mm"])] for g in games]
    ball_path = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(ball_track, ball_track[1:])) / 1000
    last = games[-1] if games else {}
    score = {str(first): int(last.get("score_a", 0)), str(second): int(last.get("score_b", 0))}
    # Runtime read-back: how often each motion network file was loaded, and from where.
    loads = Counter(row.get("model", "") for row in records["network"])
    expected = Counter()
    for team, receipt in teams.items():
        pack = packs.load(receipt["pack_id"])
        for slot in packs.motion_slots(pack):
            if pack["kind"] != "baseline" and slot in pack["components"]:
                expected[f"/NeuralNets/Walk/forge/{pack['id']}/{slot}.onnx"] += team_counts[int(team)]
            else:
                expected[OFFICIAL_MOTION_SUFFIX[slot]] += team_counts[int(team)]
    observed = Counter()
    for model, count in loads.items():
        for suffix in expected:
            if model.endswith(suffix):
                observed[suffix] += count
    foreign = sorted(m for m in loads if config_root and not m.startswith(str(config_root) + "/"))
    native_robots = {name for name, (team, player) in roster.items()
                     if "BoosterNativeMotionProvider" in (packs.load(teams[str(team)]["pack_id"]).get("modules") or {})}
    connected_native = Counter(row.get("robot") for row in records["native_controller_connected"])
    stopped_native, native_errors = Counter(), []
    for row in records["native_controller_stopped"]:
        try:
            if row.get("status") != "acknowledged" or int(row.get("native_ticks", 0)) <= 0:
                raise ValueError("missing acknowledged native execution")
            stopped_native[row.get("robot")] += 1
        except (ValueError, TypeError):
            native_errors.append("invalid native shutdown evidence")
    expected_native = Counter({robot: 1 for robot in native_robots})
    native_readback = {"expected_robots": sorted(native_robots), "connected": dict(connected_native),
                       "stopped": dict(stopped_native), "errors": native_errors,
                       "ok": not native_errors and connected_native == stopped_native == expected_native}
    readback = {"expected_loads": dict(expected), "observed_loads": dict(observed),
                "all_model_loads": dict(loads), "loaded_outside_arena": foreign,
                "native_controllers": native_readback,
                "ok": bool(expected or expected_native) and observed == expected and not foreign and native_readback["ok"]}
    module_counts = Counter((row.get("name"), str(row.get("team"))) for row in records["forge_module"])
    expected_modules = Counter()
    for team, receipt in teams.items():
        for module in (receipt.get("modules") or packs.load(receipt["pack_id"]).get("modules") or {}):
            expected_modules[(module, str(team))] += team_counts[int(team)]
    module_readback = {"expected": {f"{m}@T{t}": n for (m, t), n in expected_modules.items()},
                       "observed": {f"{m}@T{t}": n for (m, t), n in module_counts.items()},
                       "ok": module_counts == expected_modules}
    # Count alone cannot prove that three distinct robots used the candidate.
    expected_instances = Counter()
    expected_foreign = set()
    expected_multi = set()
    expected_low_mapping = set()
    for team, receipt in teams.items():
        pack = packs.load(receipt["pack_id"])
        slots = packs.motion_slots(pack)
        if not slots:
            for module in pack.get("modules") or {}:
                for member_team, player in roster.values():
                    if str(member_team) == str(team):
                        expected_instances[(module, str(team), str(player), "native-fw16-original")] += 1
            continue
        walk_slot = slots[0]
        model = (f"forge/{pack['id']}/{walk_slot}.onnx" if walk_slot in pack["components"]
                 and pack["kind"] != "baseline" else "K1_walk.onnx")
        for module in pack.get("modules") or {}:
            for member_team, player in roster.values():
                if str(member_team) == str(team):
                    expected_instances[(module, str(team), str(player), model)] += 1
                    if walk_slot not in OFFICIAL_MOTION_SUFFIX:
                        expected_foreign.add((module, str(team), str(player)))
                        if pack["modules"][module].get("params", {}).get(
                                "walkNeuronalNetworkParameters.boosterUseLowStiffnessMapping") == "true":
                            expected_low_mapping.add((str(team), str(player)))
                        if pack["modules"][module].get("params", {}).get(
                                "walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher") == "true":
                            expected_multi.add((module, str(team), str(player)))
    observed_instances = Counter((r.get("name"), r.get("team"), r.get("player"), r.get("model"))
                                 for r in records["forge_module"])
    module_readback["instances"] = list(records["forge_module"])
    module_readback["instances_ok"] = observed_instances == expected_instances
    module_readback["ok"] &= module_readback["instances_ok"]
    foreign_execution = {}
    for row in records["booster_policy"]:
        key = (row.get("name"), row.get("team"), row.get("player"))
        state = foreign_execution.setdefault(key, {"inferences": 0, "nonfinite_total": 0, "invalid_evidence": False})
        try:
            inferences, nonfinite = int(row["inferences"]), int(row["nonfinite_total"])
            if min(inferences, nonfinite) < 0:
                raise ValueError("negative execution counter")
            state["inferences"] = max(state["inferences"], inferences)
            state["nonfinite_total"] = max(state["nonfinite_total"], nonfinite)
            if key in expected_multi:
                counts = {policy: int(row[f"{policy}_inferences"]) for policy in ("forward", "side", "turn")}
                if min(counts.values()) < 0 or sum(counts.values()) != inferences or row.get("selected") not in counts:
                    raise ValueError("inconsistent per-policy execution counters")
                previous = state.setdefault("policy_inferences", dict.fromkeys(counts, 0))
                for policy, value in counts.items():
                    previous[policy] = max(previous[policy], value)
        except (KeyError, ValueError):
            state["invalid_evidence"] = True
    foreign_execution_ok = (set(foreign_execution) == expected_foreign and all(
        row["inferences"] > 0 and row["nonfinite_total"] == 0 and not row["invalid_evidence"]
        for row in foreign_execution.values()))
    mapping_rows = list(records["booster_mapping"])
    expected_mapping_players = {(team, player) for _, team, player in expected_foreign}
    seen_walk_mapping = {(row.get("team"), row.get("player")) for row in mapping_rows
                         if row.get("mode") == "walk" and row.get("mapping") == "low"}
    mapping_ok = seen_walk_mapping == expected_low_mapping and all(
        (row.get("team"), row.get("player")) in expected_mapping_players
        and row.get("mode") in ("walk", "kick")
        and row.get("phase") in (("stand", "walk") if row["mode"] == "walk" else ("walk",))
        and row.get("mapping") == ("low" if row["mode"] == "walk"
                                  and (row.get("team"), row.get("player")) in expected_low_mapping
                                  else "regular") for row in mapping_rows)
    readback["motor_mapping"] = {"expected_isolated_players": sorted(expected_low_mapping),
                                 "expected_foreign_players": sorted(expected_mapping_players),
                                 "observed": mapping_rows, "ok": mapping_ok}
    readback["foreign_policy_execution"] = {
        "instances": {f"{m}@T{t}P{p}": v for (m, t, p), v in foreign_execution.items()},
        "ok": foreign_execution_ok,
    }
    readback["modules"] = module_readback
    readback["ok"] = readback["ok"] and module_readback["ok"] and foreign_execution_ok and mapping_ok
    errors = [line for line in lines if any(k in line for k in ("AUDIT ERROR", "Syntax Error", "Syntax error:",
                                                                 "Not allowed in this game state", "Assertion failed",
                                                                 "Segmentation fault"))]
    per_team = {}
    for team in (first, second):
        members = [r for r in robots.values() if r["team"] == team]
        per_team[str(team)] = {
            "pack_id": teams.get(str(team), {}).get("pack_id"),
            "goals": score[str(team)], "goals_against": score[str(second if team == first else first)],
            "ball_contacts": contact_by_team.get(team, 0),
            "fall_episodes_sampled": sum(r["fall_episodes_sampled"] for r in members),
            "fall_frames": sum(r["fall_frames"] for r in members),
            "getup_frames": sum(r["getup_frames"] for r in members),
            "walk_frames": sum(r["walk_frames"] for r in members),
            "path_m": sum(r["path_m"] for r in members),
            "ball_seen_samples": sum(r["ball_seen_samples"] for r in members),
            "mean_perception_hz": sum(r["perception_hz"] for r in members) / max(1, len(members)),
            "skill_samples": {skill: sum(r["skill_samples"].get(skill, 0) for r in members) for skill in scenarios.SKILLS},
        }
    checks = {
        "process_exit_zero": exit_code == 0,
        "completed_requested_steps": any(int(x.get("steps", -1)) == steps for x in records["completed"]),
        "no_console_errors": not errors,
        "all_robots_reported": all(r["physics_samples"] >= 10 and r["motion_samples"] >= 10 for r in robots.values()),
        "all_robots_have_camera_perception_cognition": all(r["unique_camera_timestamps"] >= 10 and r["perception_samples"] > 0
                                                           and r["cognition_samples"] > 0 for r in robots.values()),
        "finite_all_recorded_frames": all(r["nonfinite_total"] == 0 for r in robots.values()),
        "normal_camera_resolution": all(r["camera_sizes"] == [(544, 448)] for r in robots.values()),
        "camera_perception_rate_at_least_50hz": all(50 <= r["perception_hz"] <= 65 for r in robots.values()),
        "required_game_states_observed": required_game_states.issubset({int(x["state"]) for x in games}),
        "expected_active_robots": bool(games) and all(int(x["robots"]) == len(roster) for x in games),
        "all_robots_remain_near_arena": all(r["near_arena"] for r in robots.values()),
        "runtime_network_readback": readback["ok"],
    }
    return {
        "schema": "forge.match-result/1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": "B-Human K1 public controller in normal 3D SimRobot with per-team flashed motion packs; "
                 "local simulation only, not a regulation match or hardware qualification",
        "requested_simulation_s": steps * 0.002, "checks": checks, "teams": per_team, "robots": robots,
        "score": score, "game_states": sorted({int(x["state"]) for x in games}), "ball_track": ball_track,
        "ball_path_m": ball_path, "ball_contacts_logged": len(contacts), "network_readback": readback,
        "errors": errors[:20],
        "measurement_note": "Trajectories sampled at 2 Hz; falls are sampled episodes of the cumulative fall counter; "
                            "contacts are rate-limited at 10 Hz; ball path includes referee placement; skill samples are requests, not completed passes or shots.",
    }
