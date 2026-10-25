"""Verdicts over motion-bridge evidence and the run orchestration (control plane, no torch).

The engine (``sim/bridge.py`` and ``sim/bridge_server.py``, MuJoCo venv) records raw outcomes.
This module turns them into conservative conclusions:

* identity -- ``FAITHFUL`` only when neither side fell and every segment's mean velocity agrees
  within ``IDENTITY_VELOCITY_TOL``; ``EXACT`` additionally needs sub-centimetre trajectories;
* protocol / session -- every recorded check must hold;
* gaps -- per controller and axis, the largest tested level up to which no replicate fell or
  stalled ("margin"); compared with a planning reference value that is stated, not measured;
* the real robot is never claimed: ``real_robot`` is always ``UNVERIFIED``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import paths, util
from . import contract

SCHEMA = "forge.bridge-analysis/1"
RUNS = paths.RUNS / "bridge"
ENGINE = paths.FORGE / "sim/bridge.py"
SESSION_ENGINE = paths.FORGE / "sim/bridge_server.py"
IDENTITY_VELOCITY_TOL = 0.02   # m/s or rad/s, per-segment mean velocity difference
IDENTITY_EXACT_M = 0.01        # whole-trajectory base position difference
EXPERIMENTS = ("identity", "protocol", "gaps", "crosssim")
CROSSSIM_REL_TOL = 0.20      # relative agreement of a primary segment displacement between simulators
CROSSSIM_ABS_TOL = 0.10      # m or rad: small displacements agree within this absolute band
SIMROBOT_EXPECTED = {        # controller -> pack components the SimRobot run must carry (same weights as the twin)
    "booster-deploy": ("booster_walk",),
    "firmware-gait": ("booster_fw16_walk", "booster_fw16_side", "booster_fw16_turn"),
}
PRIMARY = (("forward", "forward_m"), ("left", "left_m"), ("turn", "yaw_change_rad"))


class BridgeError(RuntimeError):
    pass


# ------------------------------------------------------------------ identity
def identity_verdict(pair: dict) -> dict:
    comp = pair.get("comparison") or {}
    ref_fell = bool(pair["reference"].get("first_fall_s") or pair["reference"].get("fall_events"))
    bridge = pair.get("bridge") or {}
    if bridge.get("error") or "max_segment_velocity_delta" not in comp:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif ref_fell or bridge.get("fell"):
        verdict = "DIVERGENT"
    elif comp["max_segment_velocity_delta"] > IDENTITY_VELOCITY_TOL:
        verdict = "DIVERGENT"
    elif comp["max_position_delta_m"] < IDENTITY_EXACT_M:
        verdict = "EXACT"
    else:
        verdict = "FAITHFUL"
    return {"stack": pair["stack"], "variant": pair["variant"], "verdict": verdict, "reference": pair["reference"]["kind"],
            "max_position_delta_m": comp.get("max_position_delta_m"), "final_position_delta_m": comp.get("final_position_delta_m"),
            "first_over_1cm_s": comp.get("first_over_1cm_s"), "first_over_5cm_s": comp.get("first_over_5cm_s"),
            "max_segment_velocity_delta": comp.get("max_segment_velocity_delta"), "segments": comp.get("segments"),
            "bridge_fell": bridge.get("fell"), "reference_fell": ref_fell}


# ------------------------------------------------------------------ gap margins
def _direction(levels: list) -> str:
    return "decreasing" if len(levels) > 1 and levels[1] < levels[0] else "increasing"


def stalled(row: dict, fraction: float) -> bool:
    """Upright but less than ``fraction`` of the commanded forward speed or yaw rate."""
    if row.get("fell"):
        return False
    segments = row.get("segments") or {}
    checks = (("forward", 0), ("turn", 2))
    for name, axis in checks:
        seg = segments.get(name)
        if not seg:
            return True
        command = seg["command"][axis]
        if command and seg["mean_velocity"][axis] / command < fraction:
            return True
    return False


def gap_margins(gaps: dict) -> dict:
    fraction = gaps.get("stall_fraction", 0.5)
    table, weakest = {}, {}
    for controller in gaps["controllers"]:
        onboard = controller in gaps.get("onboard_controllers", [])
        rows_c = [r for r in gaps["rows"] if r["controller"] == controller]
        table[controller] = {}
        for axis, spec in gaps["axes"].items():
            levels = spec["levels"]
            if onboard and axis in gaps.get("transport_axes", []):
                table[controller][axis] = {"status": "NOT_APPLICABLE",
                                           "reason": "原厂步态在机载控制环内运行，不经过 LowState/LowCmd 传输"}
                continue
            cells, margin, first_failure, errors = [], None, None, 0
            for level in levels:
                rows = [r for r in rows_c if r["axis"] == axis and r["level"] == level]
                falls = sum(bool(r.get("fell")) for r in rows)
                stalls = sum(stalled(r, fraction) for r in rows)
                errors += sum(bool(r.get("error")) for r in rows)
                ok = [r for r in rows if not r.get("fell") and r.get("segments", {}).get("forward")]
                forward = [r["segments"]["forward"]["mean_velocity"][0] for r in ok]
                turn = [r["segments"]["turn"]["mean_velocity"][2] for r in ok if r["segments"].get("turn")]
                cells.append({"level": level, "trials": len(rows), "falls": falls, "stalls": stalls,
                              "mean_forward_m_s": sum(forward) / len(forward) if forward else None,
                              "mean_turn_rad_s": sum(turn) / len(turn) if turn else None,
                              "fall_times_s": sorted(round(r["fall_s"], 2) for r in rows if r.get("fell") and r.get("fall_s") is not None)})
                if not rows:
                    continue
                if falls or stalls:
                    first_failure = level if first_failure is None else first_failure
                elif first_failure is None:
                    margin = level
            direction = _direction(levels)
            reference = spec.get("reference")
            if errors or any(c["trials"] == 0 for c in cells):
                status = "INSUFFICIENT_EVIDENCE"
            elif margin is None:
                status = "FAILS_AT_NOMINAL"
            elif reference is None:
                status = "MEASURED"
            else:
                beyond = margin >= reference if direction == "increasing" else margin <= reference
                status = "COVERS_REFERENCE" if beyond else "BELOW_REFERENCE"
            if margin is not None and reference not in (None, levels[0]):
                span = (margin - levels[0]) / (reference - levels[0])
            else:
                span = None
            table[controller][axis] = {"status": status, "margin": margin, "first_failure": first_failure,
                                       "censored": first_failure is None, "direction": direction, "reference": reference,
                                       "headroom": span, "cells": cells, "errors": errors}
        ranked = sorted(((a, v) for a, v in table[controller].items() if v.get("headroom") is not None),
                        key=lambda item: item[1]["headroom"])
        weakest[controller] = [{"axis": a, "margin": v["margin"], "first_failure": v["first_failure"],
                                "headroom": v["headroom"], "status": v["status"]} for a, v in ranked[:4]]
    return {"table": table, "weakest": weakest, "stall_fraction": fraction}


# ------------------------------------------------------------------ cross-simulator
def simrobot_reference(controller: str, run_dir: Path) -> dict:
    """Validate a SimRobot motion-basic-v1 run as the counterpart of a Virtual K1 controller."""
    run_dir = Path(run_dir)
    if not str(run_dir.resolve()).startswith(str((paths.RUNS / "motion").resolve()) + "/"):
        raise BridgeError("SimRobot 对照必须是 runs/motion 下的运行目录")
    result, launch = util.read_json(run_dir / "result.json"), util.read_json(run_dir / "launch.json")
    if not result or not launch:
        raise BridgeError(f"{run_dir} 缺少 result.json / launch.json")
    if result.get("case") != "motion-basic-v1" or result.get("execution_status") != "PASS":
        raise BridgeError(f"{run_dir.name} 不是执行通过的 motion-basic-v1 运行")
    pack = (launch.get("pack_snapshots") or {}).get("5") or {}
    components = pack.get("components") or {}
    if tuple(sorted(components)) != tuple(sorted(SIMROBOT_EXPECTED[controller])):
        raise BridgeError(f"{run_dir.name} 的 T5 运控包组件 {sorted(components)} 与 {controller} 不对应")
    robot = (result.get("robots") or {}).get("robot5") or {}
    return {"run": run_dir.name, "path": paths.rel(run_dir), "pack_id": pack.get("id"),
            "components": {k: v["sha256"] for k, v in components.items()},
            "export_checkpoint_sha256": ((pack.get("provenance") or {}).get("export") or {}).get("checkpoint_sha256"),
            "motion_segments": result.get("motion_segments"), "checks": result.get("checks"),
            "fall_frames": robot.get("fall_frames"), "getup_frames": robot.get("getup_frames"),
            "video": paths.rel(run_dir / "match.mp4") if (run_dir / "match.mp4").is_file() else None}


def crosssim_compare(crosssim: dict, references: dict) -> dict:
    rows = {}
    for controller, ref in references.items():
        vk1 = (crosssim.get("controllers") or {}).get(controller)
        if vk1 is None:
            rows[controller] = {"verdict": "INSUFFICIENT_EVIDENCE", "reason": "虚拟 K1 侧没有该控制器的运行"}
            continue
        identity = vk1["controller"]
        same_weights = None
        if controller == "firmware-gait":
            actors = identity.get("actors") or {}
            same_weights = sorted(actors.values()) == sorted(ref["components"].values())
        elif controller == "booster-deploy":
            same_weights = identity.get("checkpoint_sha256") == ref.get("export_checkpoint_sha256")
        segments, agree = {}, []
        for window, key in PRIMARY:
            a = (ref["motion_segments"] or {}).get(window, {}).get(key)
            b = vk1["metrics"].get(window, {}).get(key)
            if a is None or b is None:
                agree.append(False)
                continue
            rel = (b - a) / abs(a) if abs(a) > 1e-9 else None
            ok = abs(b - a) <= CROSSSIM_ABS_TOL or (rel is not None and abs(rel) <= CROSSSIM_REL_TOL)
            agree.append(ok)
            segments[window] = {"metric": key, "simrobot": a, "virtual_k1": b, "relative": rel, "agrees": ok}
        drift = {"forward_window_yaw_rad": {"simrobot": (ref["motion_segments"] or {}).get("forward", {}).get("yaw_change_rad"),
                                            "virtual_k1": vk1["metrics"]["forward"]["yaw_change_rad"]},
                 "settled_stop_net_m": {"simrobot": (ref["motion_segments"] or {}).get("settled_stop", {}).get("net_displacement_m"),
                                        "virtual_k1": vk1["metrics"]["settled_stop"]["net_displacement_m"]}}
        fell = bool(vk1.get("fell")) or bool(ref.get("fall_frames"))
        verdict = ("INSUFFICIENT_EVIDENCE" if same_weights is False or vk1.get("error")
                   else "CONSISTENT" if all(agree) and not fell else "MODEL_GAP")
        rows[controller] = {"verdict": verdict, "same_weights": same_weights, "segments": segments, "drift": drift,
                            "simrobot": ref, "virtual_k1_fell": vk1.get("fell")}
    return {"rows": rows, "tolerance": {"relative": CROSSSIM_REL_TOL, "absolute": CROSSSIM_ABS_TOL},
            "note": "同一网络、同一 m/s 指令：SimRobot（B-Human 场景模型 + 编译适配模块）对虚拟 K1（B-Human 训练用 MJCF + 上游代码）。"
                    "差异反映两个 K1 模型与执行器实现的差别，不是桥接失败。"}


# ------------------------------------------------------------------ whole run
def _protocol_findings(protocol: dict) -> list[dict]:
    out = []
    for scenario in protocol.get("scenarios", []):
        observed = scenario.get("observed") or {}
        if scenario["id"].startswith("P3") and observed.get("policy_safety_stop"):
            out.append({"id": "deploy-fall-exit-mode", "severity": "warn",
                        "title": f"booster_deploy 策略检测到摔倒后，退出模式为 {observed.get('exit_mode_after_stop')}",
                        "detail": "LocomotionPolicy 的跌倒回退只调用 controller.stop()；_safety_abort 只在准备阶段姿态检查时置位，"
                                  "因此摔倒后仍按配置的 exit_mode 切换。真机试验建议显式使用 --exit-mode damping。",
                        "evidence": {"scenario": scenario["id"], "rpc": observed.get("rpc")}})
    return out


def analyze(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    raw = util.read_json(run_dir / "raw.json")
    if raw is None:
        raise BridgeError(f"{run_dir} 缺少 raw.json")
    experiments = raw.get("experiments", {})
    identity = [identity_verdict(p) for p in experiments.get("identity", {}).get("pairs", [])]
    protocol = experiments.get("protocol", {})
    gaps = experiments.get("gaps")
    margins = gap_margins(gaps) if gaps else None
    session = util.read_json(run_dir / "session" / "session.json")
    references = util.read_json(run_dir / "simrobot.json") or {}
    crosssim = crosssim_compare(experiments["crosssim"], references) if experiments.get("crosssim") and references else None
    verdicts = {
        "identity": ("NOT_RUN" if not identity else "BRIDGE_FAITHFUL" if all(i["verdict"] in ("EXACT", "FAITHFUL") for i in identity)
                     else "INSUFFICIENT_EVIDENCE" if any(i["verdict"] == "INSUFFICIENT_EVIDENCE" for i in identity)
                     else "BRIDGE_DISTORTS"),
        "protocol": ("NOT_RUN" if not protocol.get("scenarios") else
                     "PASS" if all(s["status"] == "PASS" for s in protocol["scenarios"]) else "FAIL"),
        "session": "NOT_RUN" if session is None else session.get("status", "FAIL"),
        "gaps": ("NOT_RUN" if margins is None else "INSUFFICIENT_EVIDENCE" if any(
            v.get("status") == "INSUFFICIENT_EVIDENCE" for t in margins["table"].values() for v in t.values()) else "COMPLETE"),
    }
    # Cross-simulator agreement is reported beside the bridge verdict: a model gap is a finding, not a bridge failure.
    crosssim_verdict = ("NOT_RUN" if crosssim is None else "CONSISTENT" if all(
        r["verdict"] == "CONSISTENT" for r in crosssim["rows"].values()) else "INSUFFICIENT_EVIDENCE" if any(
        r["verdict"] == "INSUFFICIENT_EVIDENCE" for r in crosssim["rows"].values()) else "MODEL_GAP")
    errors = raw.get("errors") or {}
    ran = [v for v in verdicts.values() if v != "NOT_RUN"]
    if errors or not ran or "INSUFFICIENT_EVIDENCE" in ran:
        overall = "INSUFFICIENT_EVIDENCE"
    elif all(v in ("BRIDGE_FAITHFUL", "PASS", "COMPLETE") for v in ran):
        overall = "SIM_BRIDGE_VERIFIED"
    else:
        overall = "SIM_BRIDGE_ISSUES"
    findings = _protocol_findings(protocol)
    for controller, row in ((crosssim or {}).get("rows") or {}).items():
        off = {w: v for w, v in row.get("segments", {}).items() if not v["agrees"]}
        if off:
            text = "、".join(f"{w} {v['virtual_k1']:.2f} 对 {v['simrobot']:.2f}" for w, v in off.items())
            findings.append({"id": f"crosssim-{controller}", "severity": "info",
                             "title": f"{controller} 在虚拟 K1 与 SimRobot 上的位移不一致：{text}",
                             "detail": "同一网络、同一指令。差异来自两个 K1 模型与执行器实现；需要以第二个孪生模型（booster_assets 或 SimRobot 场景导出）定位。",
                             "evidence": {"simrobot_run": row["simrobot"]["run"], "same_weights": row["same_weights"]}})
    if session and session.get("prime_to_first_policy_command_ms"):
        findings.append({"id": "deploy-prime-gap", "severity": "info",
                         "title": f"进入 Custom 后首个策略命令晚于预置保持命令 {session['prime_to_first_policy_command_ms']:.0f} ms",
                         "detail": "booster_deploy 依赖固件保留预置命令跨越模式切换；这段时间机器人只执行保持姿态 PD。",
                         "evidence": {"session": "session/session.json"}})
    result = {"schema": SCHEMA, "at": util.now_iso(), "run_id": run_dir.name, "environment": raw.get("environment"),
              "virtual_k1": raw.get("virtual_k1"), "identity": identity, "identity_tolerance": {
                  "segment_velocity": IDENTITY_VELOCITY_TOL, "exact_position_m": IDENTITY_EXACT_M},
              "protocol": protocol.get("scenarios", []), "session": session, "gaps": margins,
              "gap_setup": {k: gaps[k] for k in ("schedule", "schedule_segments", "axes", "controllers", "seeds", "gap_onset_s",
                                                 "replicates", "onboard_controllers", "transport_axes", "jobs", "wall_s")
                            if k in gaps} if gaps else None,
              "verdicts": verdicts, "overall": overall, "real_robot": "UNVERIFIED",
              "crosssim": crosssim, "crosssim_verdict": crosssim_verdict,
              "engine_errors": errors, "findings": findings,
              "scope": "虚拟 K1（MuJoCo 孪生）上的接口与代码路径验证；不代表真机资格（L5 未验证）。"}
    util.write_json(run_dir / "analysis.json", result)
    return result


# ------------------------------------------------------------------ orchestration
def run(*, experiments=EXPERIMENTS, controllers=None, axes=None, seeds: int = 4, session: bool = True,
        tag: str | None = None, simrobot: dict | None = None, on_line=print) -> dict:
    if not experiments and not session:
        raise BridgeError("至少选择一个实验")
    if set(experiments) - set(EXPERIMENTS):
        raise BridgeError(f"实验只能是 {EXPERIMENTS}")
    if not 1 <= seeds <= 10:
        raise BridgeError("seeds 需在 1..10")
    references = {}
    for controller, ref_dir in (simrobot or {}).items():
        if controller not in SIMROBOT_EXPECTED:
            raise BridgeError(f"SimRobot 对照只支持 {sorted(SIMROBOT_EXPECTED)}")
        references[controller] = simrobot_reference(controller, Path(ref_dir))
    if references and "crosssim" not in experiments:
        raise BridgeError("提供 SimRobot 对照时需包含 crosssim 实验")
    run_dir = RUNS / f"{util.stamp()}_{util.safe_name(tag or 'motion-bridge', 40)}"
    run_dir.mkdir(parents=True)
    util.write_json(run_dir / "contract.json", contract.audit())
    if references:
        util.write_json(run_dir / "simrobot.json", references)
    python = str(paths.INTERPRETERS["mjlab"])

    def stream(command, name):
        on_line(f"[bridge] {name}: {' '.join(command[2:4])} …\n") if on_line else None
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=paths.FORGE)
        tail = []
        with open(run_dir / f"{name}.log", "w") as log:
            for line in process.stdout:
                log.write(line)
                tail = (tail + [line])[-40:]
                if on_line and (line.startswith("[bridge]") or line.startswith("RESULT") or "Error" in line):
                    on_line(line if line.endswith("\n") else line + "\n")
        return process.wait(), tail

    if session:  # real-time first, before the CPU-heavy sweep
        code, tail = stream([python, "-B", str(SESSION_ENGINE), "--out", str(run_dir / "session")], "session")
        if not (run_dir / "session/session.json").is_file():
            raise BridgeError("实时会话失败：%s" % "".join(tail[-8:]))
    if experiments:
        command = [python, "-B", str(ENGINE), "--out", str(run_dir / "engine"), "--experiments", ",".join(experiments),
                   "--seeds", str(seeds)]
        if controllers:
            command += ["--controllers", ",".join(controllers)]
        if axes:
            command += ["--axes", ",".join(axes)]
        code, tail = stream(command, "engine")
        raw_path = run_dir / "engine/raw.json"
        if not raw_path.is_file():
            raise BridgeError("桥接引擎失败（退出码 %s）：%s" % (code, "".join(tail[-8:])))
        raw_path.rename(run_dir / "raw.json")
    else:
        util.write_json(run_dir / "raw.json", {"schema": "forge.bridge-raw/1", "experiments": {}, "errors": {}})
    result = analyze(run_dir)
    if on_line:
        on_line(f"[bridge] overall {result['overall']} · " + " · ".join(f"{k}={v}" for k, v in result["verdicts"].items()) + "\n")
    return result


def list_runs(limit: int = 50) -> list[dict]:
    out = []
    for directory in sorted(RUNS.glob("*/"), reverse=True)[:limit]:
        analysis = util.read_json(directory / "analysis.json")
        entry = {"id": directory.name, "analyzed": bool(analysis)}
        if analysis:
            entry.update(overall=analysis["overall"], verdicts=analysis["verdicts"], at=analysis.get("at"))
        out.append(entry)
    return out


def load(run_id: str) -> dict:
    directory = RUNS / run_id
    if "/" in run_id or run_id.startswith(".") or not directory.is_dir():
        raise BridgeError("桥接运行不存在")
    analysis = util.read_json(directory / "analysis.json")
    if analysis is None:
        raise BridgeError("该运行尚未分析")
    analysis["contract"] = util.read_json(directory / "contract.json")
    return analysis


def identity_paths(run_id: str, stride: int = 10) -> dict:
    """Downsampled base trajectories of the identity pairs (reference vs bridge) for plotting."""
    import numpy as np

    directory = RUNS / run_id / "engine" / "traces"
    if "/" in run_id or not directory.is_dir():
        directory = RUNS / run_id / "traces"
    out = {}
    for path in sorted(list(directory.glob("identity-*.npz")) + list(directory.glob("crosssim-*.npz"))):
        data = np.load(path)
        base = data["base"]
        out[path.stem] = {"t": data["t"][::stride].round(3).tolist(), "x": base[::stride, 0].round(4).tolist(),
                          "y": base[::stride, 1].round(4).tolist()}
    bh = RUNS / run_id / "engine" / "bhuman-reference" / "trajectory.npz"
    if bh.is_file():
        rows = np.load(bh)["trajectory"]
        out["identity-bhuman-reference"] = {"t": rows[::stride, 0].round(3).tolist(), "x": rows[::stride, 8].round(4).tolist(),
                                            "y": rows[::stride, 9].round(4).tolist()}
    return out
