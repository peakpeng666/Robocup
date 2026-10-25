#!/usr/bin/env python3
"""Motion-bridge experiments on the Virtual K1 -> raw evidence for ``forge/bridge/analysis.py``.

identity  Bridge self-test.  Each stack's *own* sim2sim is the reference:
          * Booster: booster_deploy ``MujocoController`` (headless) vs the booster_deploy
            real-robot code driving the Virtual K1 (effort clip as in its sim2sim, then motor limits);
          * B-Human: ``bhuman/sim2sim/mujoco_walk.py::execute`` (verified B-Human sim2sim) vs the
            B-Human walk through BoosterProvider semantics on the Virtual K1 (training velocity
            filter, then the robot-side raw motor velocity).
          Same MuJoCo model and version, same command schedule, same initial state.
gaps      Reality-gap sweep: each controller x interface/plant axis x level x seed on the
          ``gap-probe`` schedule; on-board firmware gait is immune to transport axes.
protocol  Mode-handshake scenarios with booster_deploy's real code: normal session with exit
          to the vendor gait, unsafe posture refusal, fall during custom control.

Runs in ~/.venvs/forge-mjlab.  No robot, network, SDK or vendor binary.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
FORGE = HERE.parent
ROOT = FORGE.parent
for p in (str(HERE), str(FORGE)):
    if p not in sys.path:
        sys.path.insert(0, p)
import bridge_controllers as bc  # noqa: E402
import vk1  # noqa: E402
from forge.bridge import lowlevel as L  # noqa: E402

SCHEMA = "forge.bridge-raw/1"
MUJOCO_WALK = ROOT / "bhuman/sim2sim/mujoco_walk.py"
BHUMAN_PTH = vk1.SOURCE / "pre-trained/WalkAndKick/K1_walk.pth"
CONTROLLERS = {
    "bhuman-training": lambda: bc.BHumanWalk(gains="training", name="bhuman-training"),
    "bhuman-real-gains": lambda: bc.BHumanWalk(gains="bhuman_real", name="bhuman-real-gains"),
    "booster-deploy": lambda: bc.DeployOfficial(name="booster-deploy"),
    "firmware-gait": lambda: bc.FirmwareGait(name="firmware-gait"),
}
TRANSPORT_AXES = ("latency_ms", "jitter_ms", "loss")
GAP_AXES = {  # levels in increasing severity; ``reference`` is a planning value to watch, not a measurement
    "latency_ms": {"label": "往返延迟", "unit": "ms", "levels": [0, 10, 20, 40, 60, 80, 100, 120], "reference": 20},
    "jitter_ms": {"label": "控制周期抖动", "unit": "±ms", "levels": [0, 2, 4, 8, 12, 16], "reference": 4},
    "loss": {"label": "状态/命令丢帧率", "unit": "概率", "levels": [0, 0.05, 0.1, 0.2, 0.3, 0.5], "reference": 0.05},
    "kd_low": {"label": "电机侧阻尼偏低", "unit": "×", "levels": [1, 0.75, 0.5, 0.35, 0.25], "reference": 0.5},
    "kd_high": {"label": "电机侧阻尼偏高", "unit": "×", "levels": [1, 1.5, 2, 3, 4], "reference": 2},
    "kp_low": {"label": "电机侧刚度偏低", "unit": "×", "levels": [1, 0.9, 0.8, 0.7, 0.6, 0.5], "reference": 0.8},
    "kp_high": {"label": "电机侧刚度偏高", "unit": "×", "levels": [1, 1.25, 1.5, 2], "reference": 1.25},
    "torque_scale": {"label": "力矩能力下降", "unit": "×", "levels": [1, 0.8, 0.6, 0.5, 0.4, 0.3], "reference": 0.8},
    "imu_bias_deg": {"label": "姿态偏差", "unit": "°", "levels": [0, 2, 4, 6, 8, 10, 12], "reference": 3},
    "gyro_noise": {"label": "陀螺噪声", "unit": "rad/s", "levels": [0, 0.05, 0.1, 0.2, 0.4, 0.8], "reference": 0.1},
    "motor_lag_ms": {"label": "执行器滞后", "unit": "ms", "levels": [0, 2, 5, 10, 20, 30, 40], "reference": 5},
    "push_ns": {"label": "前进中侧推冲量", "unit": "N·s", "levels": [0, 10, 20, 30, 40, 50], "reference": 15},
}
STALL_FRACTION = 0.5  # a run that achieves less than half the commanded forward speed or yaw rate "stalls"
GAP_ONSET_S = 2.0  # gaps switch on when "forward" begins: the controller is already running at zero command


def gaps_for(axis: str, level: float) -> vk1.Gaps:
    if axis == "latency_ms":
        return vk1.Gaps(state_latency_ms=level / 2, cmd_latency_ms=level / 2)
    if axis == "loss":
        return vk1.Gaps(state_drop=level, cmd_drop=level)
    if axis == "push_ns":
        return vk1.Gaps(push_ns=level, push_at_s=4.0, push_dir_deg=90.0)
    if axis in ("kd_low", "kd_high"):
        return vk1.Gaps(kd_scale=level)
    if axis in ("kp_low", "kp_high"):
        return vk1.Gaps(kp_scale=level)
    return vk1.Gaps(**{axis: level})


# ------------------------------------------------------------------ one lockstep run
def run_lockstep(controller, *, schedule: str, gaps: vk1.Gaps, seed: int, settle_s: float = 0.5, handshake: bool = True,
                 post_s: float = 0.0, mode: str = "prepare", initial_pose=None, initial_height=None,
                 stop_on_fall: bool = True, finish: bool = True, traces: bool = False, replicate: bool = False,
                 gap_onset_s: float | None = None) -> dict:
    """``replicate``: seed-dependent initial joint noise, heading and start phase (independent trials).
    ``gap_onset_s``: run ideal until this schedule time, then apply ``gaps`` (steady-gait tolerance)."""
    ctrl = CONTROLLERS[controller]() if isinstance(controller, str) else controller
    walking = vk1.FW16Walking(vk1.fw16_actor_files(bc.FW16_PACK))
    target_gaps = gaps
    if gap_onset_s is not None:
        gaps = vk1.Gaps(effort_limits=target_gaps.effort_limits)
    robot = vk1.VirtualK1(gaps=gaps, seed=seed, mode=mode, walking=walking, initial_pose=initial_pose,
                          initial_height=initial_height, init_noise_rad=0.01 if replicate else 0.0)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x4A4954]))
    if replicate:
        settle_s += float(rng.uniform(0.0, 0.4))
    if settle_s:
        robot.step(int(round(settle_s / robot.dt)))
    started = time.perf_counter()
    error = None
    try:
        ctrl.attach(robot, handshake=handshake)
        start = robot.k
        total = bc.schedule_length(schedule)
        ticks, next_tick, pushed, onset_done = 0, start, False, gap_onset_s is None
        while (robot.k - start) * robot.dt < total - 1e-9:
            t = (robot.k - start) * robot.dt
            if not onset_done and t >= gap_onset_s:
                robot.set_gaps(target_gaps)
                gaps, onset_done = target_gaps, True
            jitter = gaps.jitter_ms / 1000 / robot.dt
            if robot.k >= next_tick:
                ctrl.tick(robot, t, bc.command_at(schedule, t)[2])
                ticks += 1
                next_tick = start + 10 * ticks + (int(round(rng.uniform(-jitter, jitter))) if jitter else 0)
            if gaps.push_ns and not pushed and t >= gaps.push_at_s:
                robot.start_push()
                pushed = True
            robot.step()
            if stop_on_fall and robot.fell() and robot.time - robot.stats["first_fall_s"] > 0.5:
                break
        if finish:
            ctrl.finish(robot)
        if post_s and not (stop_on_fall and robot.fell()):
            robot.step(int(round(post_s / robot.dt)))
    except Exception as exc:  # recorded, never hidden
        error = f"{type(exc).__name__}: {exc}"
        start = locals().get("start", robot.k)
    wall = time.perf_counter() - started
    trace = robot.traces()
    t0 = start * robot.dt
    out = {"controller": ctrl.describe(), "schedule": schedule, "seed": seed, "gaps": target_gaps.nonideal(),
           "gap_onset_s": gap_onset_s, "error": error,
           "start_s": t0, "wall_s": wall, "summary": robot.summary(), "events": robot.events,
           "segments": segment_metrics(trace, schedule, t0), "fell": robot.fell(),
           "fall_s": None if robot.stats["first_fall_s"] is None else robot.stats["first_fall_s"] - t0}
    if traces:
        out["_trace"] = trace
    return out


def displacement_velocities(t, base, yaw, start: float, end: float, window: float = 0.5):
    """Heading-frame velocities from displacement over consecutive ``window`` sub-intervals.

    Instantaneous velocities sampled once per 20 ms control tick are phase-locked to the gait and
    alias the strong within-step oscillation (yaw rate especially) into a bias; displacements do not.
    """
    idx = np.nonzero((t >= start - 1e-9) & (t <= end + 1e-9))[0]
    if idx.size < 2:
        return None
    edges = np.arange(t[idx[0]], t[idx[-1]] + 1e-9, window)
    if edges.size < 2:
        edges = np.array([t[idx[0]], t[idx[-1]]])
    picks = [idx[np.argmin(np.abs(t[idx] - e))] for e in edges]
    rows = []
    for a, b in zip(picks, picks[1:]):
        dt = t[b] - t[a]
        if dt <= 0:
            continue
        dx, dy, psi = base[b, 0] - base[a, 0], base[b, 1] - base[a, 1], yaw[a]
        rows.append([(math.cos(psi) * dx + math.sin(psi) * dy) / dt, (-math.sin(psi) * dx + math.cos(psi) * dy) / dt,
                     (yaw[b] - yaw[a]) / dt])
    return np.asarray(rows) if rows else None


def segment_metrics(trace: dict, schedule: str, t0: float, settle: float = 1.0) -> dict:
    t = trace["t"] - t0
    yaw = np.unwrap(trace["rpy"][:, 2])
    out = {}
    for name, start, end, cmd in bc.SCHEDULES[schedule]:
        vel = displacement_velocities(t, trace["base"], yaw, start + min(settle, (end - start) / 2), end)
        if vel is None:
            continue
        mask = (t >= start + min(settle, (end - start) / 2)) & (t <= end)
        cmd = np.array(cmd)
        out[name] = {"command": cmd.tolist(), "samples": int(len(vel)), "mean_velocity": vel.mean(0).tolist(),
                     "rmse": np.sqrt(((vel - cmd) ** 2).mean(0)).tolist(), "method": "displacement/0.5s",
                     "mode": L.mode_name(int(np.bincount(trace["mode"][mask]).argmax()))}
    return out


# ------------------------------------------------------------------ identity
def compare(ref: dict, run: dict) -> dict:
    """Reference/run: dict with t and xyz (time-aligned on the 20 ms policy grid).

    Segment velocities are world-frame displacement rates (no yaw needed, no sampling alias).
    """
    ref_t, run_t = np.round(ref["t"], 6), np.round(run["t"], 6)
    common, ia, ib = np.intersect1d(ref_t, run_t, return_indices=True)
    if common.size < 2:
        return {"aligned_samples": int(common.size), "error": "no common timeline"}
    a_xyz, b_xyz = ref["xyz"][ia], run["xyz"][ib]
    delta = np.linalg.norm(a_xyz - b_xyz, axis=1)

    def first_over(threshold):
        hits = np.nonzero(delta > threshold)[0]
        return float(common[hits[0]]) if hits.size else None

    seg = {}
    for name, start, end, cmd in bc.SCHEDULES[run["schedule"]]:
        idx = np.nonzero((common >= start + 1.0) & (common <= end))[0]
        if idx.size < 2:
            continue
        dt = common[idx[-1]] - common[idx[0]]
        a = (a_xyz[idx[-1], :2] - a_xyz[idx[0], :2]) / dt
        b = (b_xyz[idx[-1], :2] - b_xyz[idx[0], :2]) / dt
        seg[name] = {"command": list(cmd), "reference_world_velocity": a.tolist(), "bridge_world_velocity": b.tolist(),
                     "delta": float(np.linalg.norm(b - a))}
    return {"aligned_samples": int(common.size), "max_position_delta_m": float(delta.max()),
            "final_position_delta_m": float(delta[-1]), "position_delta_at_5s_m": float(delta[np.searchsorted(common, 5.0) - 1]),
            "first_over_1cm_s": first_over(0.01), "first_over_5cm_s": first_over(0.05), "segments": seg,
            "segment_velocity_method": "world-frame displacement over each segment (from +1 s)",
            "max_segment_velocity_delta": float(max((s["delta"] for s in seg.values()), default=0.0))}


def bhuman_reference(out_dir: Path) -> dict:
    """Run B-Human's own sim2sim (mujoco_walk.execute) into out_dir in a clean interpreter."""
    out_dir.mkdir(parents=True, exist_ok=True)
    code = ("import importlib.util,sys,argparse;from pathlib import Path;"
            f"spec=importlib.util.spec_from_file_location('bhuman_mujoco_walk',{str(MUJOCO_WALK)!r});"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            f"a=argparse.Namespace(seconds=30.0,checkpoint=Path({str(BHUMAN_PTH)!r}),viewer=False,realtime=False);"
            f"sys.exit(m.execute(a,Path({str(out_dir)!r})))")
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                          env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    (out_dir / "console.log").write_text(proc.stdout + proc.stderr)
    result = json.loads((out_dir / "result.json").read_text())
    data = np.load(out_dir / "trajectory.npz")
    rows = data["trajectory"]
    return {"exit_code": proc.returncode, "status": result["status"], "result": result,
            "trace": {"t": rows[:, 0], "xyz": rows[:, 8:11], "vel": rows[:, 5:8]}}


def identity(out_dir: Path) -> dict:
    traces_dir = out_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    schedule = "sim2sim-6x5"
    out = {"schedule": schedule, "schedule_segments": bc.SCHEDULES[schedule], "pairs": []}
    # ---- Booster: booster_deploy's own sim2sim vs its real-robot code on the Virtual K1
    deploy_cfg = bc.deploy_modules()["get_task"]("k1_walk")
    default_pose = [float(v) for v in deploy_cfg.robot.default_joint_pos]
    ref = bc.run_deploy_mujoco(schedule, init_height=0.58)
    rt = ref["trace"]
    reference = {"t": rt["t"], "xyz": rt["base"], "vel": rt["vel"]}
    np.savez_compressed(traces_dir / "identity-booster-reference.npz", **rt)
    for label, limits in (("deploy_effort_clip", "deploy"), ("motor_limits", "motor")):
        run = run_lockstep("booster-deploy", schedule=schedule, gaps=vk1.Gaps(effort_limits=limits), seed=0, settle_s=0,
                           handshake=False, mode="custom", initial_pose=default_pose, initial_height=0.58, finish=False,
                           traces=True)
        tr = run.pop("_trace")
        np.savez_compressed(traces_dir / f"identity-booster-{label}.npz", **tr)
        bridge = {"t": tr["t"], "xyz": tr["base"], "vel": tr["vel"], "schedule": schedule}
        out["pairs"].append({"stack": "booster_deploy", "variant": label,
                             "reference": {"kind": "booster_deploy MujocoController (official sim2sim, headless)",
                                           "first_fall_s": ref["first_fall_s"], "effort_limit": ref["effort_limit"],
                                           "physics_dt_s": ref["physics_dt_s"], "decimation": ref["decimation"]},
                             "bridge": {k: run[k] for k in ("controller", "summary", "segments", "fell", "fall_s", "error", "gaps")},
                             "comparison": compare(reference, bridge)})
    # ---- B-Human: its verified sim2sim vs BoosterProvider semantics on the Virtual K1
    bh = bhuman_reference(out_dir / "bhuman-reference")
    reference = bh["trace"]
    controller = bc.BHumanWalk(gains="training", stand_s=0.0, name="bhuman-training")
    pose = controller.defaults.copy()
    pose[:10] = 0.0  # mujoco_walk starts every joint at the YAML default (upper body 0) and holds the keyframe
    for label, gaps in (("training_velocity_filter", vk1.Gaps(velocity_estimate="fd", dq_filter=0.22)),
                        ("raw_motor_velocity", vk1.Gaps())):
        run = run_lockstep(bc.BHumanWalk(gains="training", stand_s=0.0, name="bhuman-training"), schedule=schedule,
                           gaps=gaps, seed=0, settle_s=0, handshake=False, mode="custom", initial_pose=pose,
                           initial_height=0.58, finish=False, traces=True)
        tr = run.pop("_trace")
        np.savez_compressed(traces_dir / f"identity-bhuman-{label}.npz", **tr)
        # mujoco_walk reports body-frame vx/vy and body wz; for level walking these equal the heading frame.
        bridge = {"t": tr["t"], "xyz": tr["base"], "vel": tr["vel"], "schedule": schedule}
        out["pairs"].append({"stack": "bhuman", "variant": label,
                             "reference": {"kind": "bhuman/sim2sim/mujoco_walk.py execute() (verified B-Human sim2sim)",
                                           "status": bh["status"], "exit_code": bh["exit_code"],
                                           "fall_events": bh["result"]["fall_events"],
                                           "policy_sha256": bh["result"]["policy_identity"]["checkpoint_sha256"]},
                             "bridge": {k: run[k] for k in ("controller", "summary", "segments", "fell", "fall_s", "error", "gaps")},
                             "comparison": compare(reference, bridge)})
    return out


# ------------------------------------------------------------------ cross-simulator (SimRobot motion-basic-v1)
SIMROBOT_WINDOWS = (("forward", 2.0, 10.0), ("left", 10.0, 16.0), ("turn", 16.0, 24.0), ("settled_stop", 26.0, 30.0))


def simrobot_style_metrics(trace: dict, t0: float, sample_s: float = 0.5) -> dict:
    """Displacements exactly as forge/scenarios.py::motion_metrics computes them from SimRobot's 0.5 s samples."""
    t = trace["t"] - t0
    keep = np.isclose(np.mod(t + 1e-9, sample_s), 0.0, atol=1e-6) & (t >= -1e-9)
    t, base, yaw = t[keep], trace["base"][keep], trace["rpy"][keep][:, 2]
    out = {}
    for label, start, end in SIMROBOT_WINDOWS:
        idx = np.nonzero((t >= start - 1e-9) & (t <= end + 1e-9))[0]
        forward = left = turn = 0.0
        for a, b in zip(idx, idx[1:]):
            dx, dy = base[b, 0] - base[a, 0], base[b, 1] - base[a, 1]
            forward += math.cos(yaw[a]) * dx + math.sin(yaw[a]) * dy
            left += -math.sin(yaw[a]) * dx + math.cos(yaw[a]) * dy
            turn += math.remainder(yaw[b] - yaw[a], 2 * math.pi)
        elapsed = t[idx[-1]] - t[idx[0]] if idx.size > 1 else 0.0
        out[label] = {"samples": int(idx.size), "forward_m": forward, "left_m": left, "yaw_change_rad": turn,
                      "mean_vx_m_s": forward / elapsed if elapsed else None, "mean_vy_m_s": left / elapsed if elapsed else None,
                      "mean_wz_rad_s": turn / elapsed if elapsed else None,
                      "net_displacement_m": float(np.linalg.norm(base[idx[-1], :2] - base[idx[0], :2])) if idx.size > 1 else None}
    return out


def crosssim(out_dir: Path, controllers=("booster-deploy", "firmware-gait")) -> dict:
    traces_dir = out_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    rows = {}
    for controller in controllers:
        run = run_lockstep(controller, schedule="simrobot-motion-basic-v1", gaps=vk1.Gaps(), seed=0, settle_s=0.5,
                           finish=False, traces=True)
        trace = run.pop("_trace")
        np.savez_compressed(traces_dir / f"crosssim-{controller}.npz", **trace)
        rows[controller] = {"metrics": simrobot_style_metrics(trace, run["start_s"]), "fell": run["fell"],
                            "fall_s": run["fall_s"], "error": run["error"], "controller": run["controller"],
                            "summary": {k: run["summary"][k] for k in ("final_mode", "lowcmd_received", "max_tilt_rad")}}
    return {"schedule": "simrobot-motion-basic-v1", "schedule_segments": bc.SCHEDULES["simrobot-motion-basic-v1"],
            "windows": SIMROBOT_WINDOWS, "sampling_s": 0.5, "controllers": rows,
            "note": "与 SimRobot motion-basic-v1 发给 Booster 运控包的 m/s 指令相同，按 SimRobot 的 0.5 s 采样与窗口计算位移"}


# ------------------------------------------------------------------ gap sweep
def _gap_job(job):
    controller, axis, level, seed = job
    try:
        run = run_lockstep(controller, schedule="gap-probe", gaps=gaps_for(axis, level), seed=seed, replicate=True,
                           gap_onset_s=GAP_ONSET_S)
        return {"controller": controller, "axis": axis, "level": level, "seed": seed, "fell": run["fell"],
                "fall_s": run["fall_s"], "error": run["error"], "segments": run["segments"],
                "rejected": run["summary"]["lowcmd_rejected"], "dropped": run["summary"]["lowcmd_dropped"],
                "state_dropped": run["summary"]["lowstate_dropped"],
                "saturation": run["summary"]["saturation_fraction"], "max_tilt_rad": run["summary"]["max_tilt_rad"],
                "wall_s": run["wall_s"], "controller_sha256": run["controller"].get("policy_sha256")
                or run["controller"].get("checkpoint_sha256") or run["controller"].get("actors")}
    except Exception as exc:
        return {"controller": controller, "axis": axis, "level": level, "seed": seed, "fell": None,
                "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}


def gap_sweep(controllers, axes, seeds: int, workers: int) -> dict:
    jobs = []
    for controller in controllers:
        onboard = CONTROLLERS[controller]().onboard
        for axis in axes:
            if onboard and axis in TRANSPORT_AXES:
                continue
            for level in GAP_AXES[axis]["levels"]:
                for seed in range(seeds):
                    jobs.append((controller, axis, level, seed))
    started = time.perf_counter()
    context = multiprocessing.get_context("fork")
    with context.Pool(workers) as pool:
        rows = []
        for i, row in enumerate(pool.imap_unordered(_gap_job, jobs, chunksize=2), 1):
            rows.append(row)
            if i % 50 == 0 or i == len(jobs):
                print(f"[bridge] gaps {i}/{len(jobs)}", flush=True)
    rows.sort(key=lambda r: (r["controller"], r["axis"], r["level"], r["seed"]))
    return {"schedule": "gap-probe", "schedule_segments": bc.SCHEDULES["gap-probe"], "axes": {a: GAP_AXES[a] for a in axes},
            "stall_fraction": STALL_FRACTION, "gap_onset_s": GAP_ONSET_S, "replicates": "per seed: N(0, 0.01 rad) initial joints, random heading, "
                                                          "0-0.4 s extra settle (start phase)",
            "controllers": list(controllers), "seeds": seeds, "transport_axes": list(TRANSPORT_AXES),
            "onboard_controllers": [c for c in controllers if CONTROLLERS[c]().onboard],
            "rows": rows, "jobs": len(jobs), "wall_s": time.perf_counter() - started}


# ------------------------------------------------------------------ protocol scenarios
def _rpc_sequence(summary):
    return [[c["api_id"], json.loads(c["body"])["mode"] if c["api_id"] == 2000 else None, c["status"]]
            for c in summary["rpc_calls"]]


def protocol() -> dict:
    scenarios = []
    # P1: a normal session -- prepare standing, X, walking preparation, A, walk, exit to the vendor gait.
    ctrl = bc.DeployOfficial(name="booster-deploy")
    run = run_lockstep(ctrl, schedule="bridge-walk", gaps=vk1.Gaps(), seed=0, settle_s=0.5, post_s=3.0)
    modes = [e["to"] for e in run["events"] if e["event"] == "mode"]
    s = run["summary"]
    checks = {
        "rpc_sequence_custom_then_walking": _rpc_sequence(s) == [[2000, 3, 0], [2018, None, 0], [2000, 2, 0], [2018, None, 0]],
        "mode_timeline_prepare_custom_walking": modes == ["custom", "walking"],
        "hold_command_primed_before_custom": not any(e["event"] == "custom_without_command" for e in run["events"]),
        "custom_period_20ms": bool(s["custom_cmd_period_ms"] and abs(s["custom_cmd_period_ms"]["mean"] - 20) < 0.5
                                   and s["custom_cmd_period_ms"]["max"] <= 30),
        "no_rejected_or_parallel_commands": s["lowcmd_rejected"] == 0 and s["lowcmd_parallel_rejected"] == 0,
        "no_fall_including_handover": not run["fell"],
        "final_mode_walking": s["final_mode"] == "walking",
        "targets_within_firmware_limits": not s["limit_violation_fraction"],
    }
    scenarios.append({"id": "P1-normal-session", "title": "正常会话：准备→X→Custom→A→行走→退出交还原厂步态",
                      "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL", "run": _slim(run),
                      "deploy_log": ctrl.log})
    # P2: unsafe posture at X -- the robot was left in damping and is lying on the ground.
    ctrl = bc.DeployOfficial(name="booster-deploy")
    run = run_lockstep(ctrl, schedule="gap-probe", gaps=vk1.Gaps(), seed=0, settle_s=2.5, mode="damping",
                       stop_on_fall=False)
    s = run["summary"]
    checks = {
        "refused_walk_preparation": any(e["event"] == "start_custom_mode_conditionally" and not e["ok"] and e["safety_abort"]
                                        for e in ctrl.log),
        "never_entered_custom": all(e.get("to") != "custom" for e in run["events"] if e["event"] == "mode"),
        "requested_damping": [2000, 0, 0] in _rpc_sequence(s),
        "no_joint_commands_sent": s["lowcmd_received"] == 0,
    }
    scenarios.append({"id": "P2-unsafe-posture", "title": "不安全姿态：机器人已倒地时按 X，应拒绝并切阻尼",
                      "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL", "run": _slim(run),
                      "deploy_log": ctrl.log})
    # P3: a fall during custom control (large lateral impulse while walking forward).
    ctrl = bc.DeployOfficial(name="booster-deploy")
    run = run_lockstep(ctrl, schedule="gap-probe", gaps=vk1.Gaps(push_ns=90, push_at_s=4.0, push_dir_deg=90), seed=0,
                       stop_on_fall=False, post_s=2.0)
    s = run["summary"]
    stop = next((e for e in ctrl.log if e["event"] == "policy_safety_stop"), None)
    exit_event = next((e for e in ctrl.log if e["event"] == "exit_mode"), None)
    observed = {"fell": run["fell"], "policy_safety_stop": stop is not None,
                "exit_mode_after_stop": exit_event["mode"] if exit_event else None,
                "final_mode": s["final_mode"], "rpc": _rpc_sequence(s)}
    checks = {"fall_induced": run["fell"], "policy_stopped_itself": stop is not None,
              "custom_left_after_stop": s["final_mode"] != "custom"}
    scenarios.append({"id": "P3-fall-during-custom", "title": "Custom 控制中摔倒：策略安全回退与退出模式",
                      "checks": checks, "observed": observed, "status": "PASS" if all(checks.values()) else "FAIL",
                      "run": _slim(run), "deploy_log": ctrl.log,
                      "note": "记录 booster_deploy 实际选择的退出模式；姿态安全中止标志只在进入准备阶段时设置"})
    # P4: firmware gait session through Loco RPC only (what B1LocoClient.Move users rely on).
    run = run_lockstep("firmware-gait", schedule="bridge-walk", gaps=vk1.Gaps(), seed=0, post_s=1.0)
    s = run["summary"]
    checks = {"walking_mode_entered": s["final_mode"] == "walking", "no_fall": not run["fell"],
              "all_three_actors_used": all(v > 0 for v in s["firmware_gait_selection_counts"].values()),
              "no_lowcmd_needed": s["lowcmd_received"] == 0}
    scenarios.append({"id": "P4-firmware-gait-rpc", "title": "原厂步态：仅通过 Loco RPC（ChangeMode/Move）驱动",
                      "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL", "run": _slim(run)})
    return {"scenarios": scenarios}


def _slim(run: dict) -> dict:
    return {k: run[k] for k in ("controller", "schedule", "gaps", "summary", "events", "segments", "fell", "fall_s", "error",
                                "wall_s")}


# ------------------------------------------------------------------ main
def environment() -> dict:
    import mujoco
    import onnxruntime
    import torch
    return {"python": sys.version.split()[0], "executable": sys.executable, "mujoco": mujoco.__version__,
            "torch": torch.__version__, "onnxruntime": onnxruntime.__version__, "robot_connected": False,
            "network_used": False}


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(type(value))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--experiments", default="identity,protocol,gaps")
    ap.add_argument("--controllers", default=",".join(CONTROLLERS))
    ap.add_argument("--axes", default=",".join(GAP_AXES))
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=max(1, min(20, (os.cpu_count() or 2) - 2)))
    args = ap.parse_args()
    experiments = [e for e in args.experiments.split(",") if e]
    controllers = [c for c in args.controllers.split(",") if c]
    axes = [a for a in args.axes.split(",") if a]
    if set(experiments) - {"identity", "gaps", "protocol", "crosssim"} or set(controllers) - set(CONTROLLERS) \
            or set(axes) - set(GAP_AXES):
        ap.error("unknown experiment, controller or axis")
    if not 1 <= args.seeds <= 10:
        ap.error("--seeds must be 1..10")
    if args.out.exists() and any(args.out.iterdir()):
        ap.error("output directory exists and is not empty; use a new timestamped directory")
    args.out.mkdir(parents=True, exist_ok=True)
    raw = {"schema": SCHEMA, "started_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="milliseconds"),
           "environment": environment(), "virtual_k1": {"assumptions": list(vk1.ASSUMPTIONS), "xml": str(vk1.XML),
                                                        "physics_dt_s": 0.002, "lowstate_hz": 500, "policy_hz": 50},
           "experiments": {}, "errors": {}}
    for name in experiments:
        print(f"[bridge] {name} ...", flush=True)
        try:
            if name == "identity":
                raw["experiments"]["identity"] = identity(args.out)
            elif name == "protocol":
                raw["experiments"]["protocol"] = protocol()
            elif name == "crosssim":
                raw["experiments"]["crosssim"] = crosssim(args.out)
            else:
                raw["experiments"]["gaps"] = gap_sweep(controllers, axes, args.seeds, args.workers)
        except Exception as exc:
            raw["errors"][name] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            print(f"[bridge] {name} FAILED: {exc}", flush=True)
    raw["finished_at"] = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="milliseconds")
    (args.out / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1, default=_json_default) + "\n")
    print(f"RESULT {args.out / 'raw.json'}", flush=True)
    return 1 if raw["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
