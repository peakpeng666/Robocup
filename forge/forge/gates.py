"""Versioned simulation gates: incomplete, invalid or unrelated evidence never passes."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from . import packs, paths, util

RULE_VERSION = "forge.sim-gates/3"
RULES = {"isaac_tracking_relative": 0.10, "isaac_tracking_absolute": 0.01,
         "mj_tracking_relative": 0.25, "mj_tracking_absolute": 0.02, "mj_fall_z_max": 1.645,
         "fragility_noninferiority_margin": 0.10}
ISAAC_COMPARABLE = ("seed", "num_envs", "seg_steps", "schedule", "planned_steps",
                    "evaluator_sha256", "source_sha256", "zero_command_mode")


class EvidenceError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def _number(value, name, *, minimum=0, integer=False):
    _require(isinstance(value, (int, float)) and not isinstance(value, bool)
             and math.isfinite(value), f"{name} 缺失或不是有限数值")
    _require(minimum is None or value >= minimum, f"{name} 超出合法范围")
    _require(not integer or int(value) == value, f"{name} 必须是整数")
    return value


def _hash(value, name):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), f"{name} 缺少有效 SHA256")
    return value


def _identity(result, expected):
    actual = _hash(result.get("policy_sha256"), "policy_sha256")
    if expected is not None:
        _require(actual == _hash(expected, "expected_policy_sha256"), "评测策略哈希与待验证策略不符")


def _vector(value, name, *, nonnegative=True):
    _require(isinstance(value, list) and len(value) == 3, f"{name} 必须包含三个轴")
    for component in value:
        _number(component, name, minimum=0 if nonnegative else None)
    return value


def _insufficient(exc):
    return {"status": "INSUFFICIENT", "reason": str(exc)}


def _isaac_summary(results: dict, expected_hash=None) -> dict:
    _require(isinstance(results, dict) and bool(results), "缺少主线评估")
    _identity(results, expected_hash)
    for name in ("evaluator_sha256", "source_sha256"):
        _hash(results.get(name), name)
    _require(results.get("finite_checks_pass") is True, "主线评估未通过有限数值检查")
    for key in ("seed", "num_envs", "seg_steps", "planned_steps", "executed_steps"):
        _number(results.get(key), key, minimum=0 if key == "seed" else 1, integer=True)
    _require(isinstance(results.get("zero_command_mode"), str), "缺少零指令处理模式")
    schedule, segments = results.get("schedule"), results.get("segments")
    _require(isinstance(schedule, list) and schedule and all(isinstance(s, str) for s in schedule), "缺少评估日程")
    _require(len(set(schedule)) == len(schedule) and isinstance(segments, dict)
             and set(segments) == set(schedule), "评估段与日程不完整或不一致")
    _require(results["executed_steps"] == results["planned_steps"] == len(schedule) * results["seg_steps"],
             "计划步数与已执行步数不一致")
    moving, segment_resets = [], 0
    for name in schedule:
        segment = segments[name]
        _require(isinstance(segment, dict), f"评估段 {name} 无效")
        _number(segment.get("steps"), "segment.steps", minimum=1, integer=True)
        _require(segment["steps"] == results["seg_steps"], f"评估段 {name} 尚未完成")
        command = _vector(segment.get("command_vx_vy_wz"), "command", nonnegative=False)
        rmse = _vector(segment.get("tracking_rmse_settled_vx_vy_wz"), "tracking_rmse")
        segment_resets += _number((segment.get("termination_events") or {}).get("non_timeout_reset"),
                                  "segment.non_timeout_reset", integer=True)
        if any(abs(c) > 1e-9 for c in command):
            moving.append(rmse)
    _require(moving, "评估没有运动指令段")
    resets = _number((results.get("termination_events_total") or {}).get("non_timeout_reset"),
                     "non_timeout_reset", integer=True)
    _require(resets == segment_resets, "复位总数与各评估段不一致")
    return {"resets": resets, "rmse_vx_vy_wz": [sum(s[i] for s in moving) / len(moving) for i in range(3)],
            "segments": len(segments), "seed": results["seed"], "policy_sha256": results["policy_sha256"]}


def gate_isaac(candidate: dict | None, baseline: dict | None, tolerance=0.10, *, candidate_hash=None, baseline_hash=None) -> dict:
    try:
        c, b = _isaac_summary(candidate, candidate_hash), _isaac_summary(baseline, baseline_hash)
        for field in ISAAC_COMPARABLE:
            _require(candidate[field] == baseline[field], f"主线评估 {field} 不同，不可比")
        _require(all(candidate["segments"][s]["command_vx_vy_wz"] == baseline["segments"][s]["command_vx_vy_wz"]
                     for s in candidate["schedule"]), "主线评估运动指令不同，不可比")
    except (EvidenceError, KeyError, TypeError, AttributeError) as exc:
        return _insufficient(exc)
    tracking_ok = all(cv <= bv * (1 + tolerance) + RULES["isaac_tracking_absolute"]
                      for cv, bv in zip(c["rmse_vx_vy_wz"], b["rmse_vx_vy_wz"]))
    resets_ok = c["resets"] <= b["resets"]
    return {"status": "PASS" if tracking_ok and resets_ok else "FAIL", "tracking_ok": tracking_ok,
            "resets_ok": resets_ok, "candidate": c, "baseline": b}


def _mj_summary(result, expected_hash=None):
    _require(isinstance(result, dict) and result.get("status") == "COMPLETED", "MuJoCo 评测尚未完成")
    _identity(result, expected_hash)
    _hash(result.get("evaluator_sha256"), "MuJoCo evaluator_sha256（旧记录需重新评测）")
    setup, metrics, model, engine = (result.get(k) for k in ("setup", "metrics", "model", "engine"))
    _require(all(isinstance(v, dict) for v in (setup, metrics, model, engine)), "MuJoCo 评测元数据不完整")
    worlds = _number(setup.get("worlds"), "worlds", minimum=1, integer=True)
    _number(setup.get("seconds"), "seconds", minimum=1)
    _number(setup.get("seed"), "seed", integer=True)
    for key in ("schedule", "command_period_s", "vx", "vy", "wz", "stand_probability", "push_force_max_N",
                "push_interval_s", "push_duration_s", "init_noise_rad", "nconmax", "njmax"):
        _require(key in setup, f"MuJoCo 缺少设置 {key}")
    _require(isinstance(setup["schedule"], bool), "schedule 必须是布尔值")
    for key in ("command_period_s", "push_interval_s", "push_duration_s"):
        _require(_number(setup[key], key) > 0, f"{key} 必须大于零")
    for key in ("push_force_max_N", "init_noise_rad", "stand_probability"):
        _number(setup[key], key)
    _require(setup["stand_probability"] <= 1, "stand_probability 超出范围")
    for key in ("nconmax", "njmax"):
        _number(setup[key], key, minimum=1, integer=True)
    for axis in ("vx", "vy", "wz"):
        bounds = setup[axis]
        _require(isinstance(bounds, list) and len(bounds) == 2, f"{axis} 指令范围不完整")
        for value in bounds:
            _number(value, axis, minimum=None)
        _require(bounds[0] <= bounds[1], f"{axis} 指令范围无效")
    for key in ("xml_sha256", "config_sha256"):
        _hash(model.get(key), key)
    for key in ("physics_dt_s", "policy_dt_s"):
        _require(_number(model.get(key), key) > 0, f"{key} 必须大于零")
    for key in ("mujoco", "mujoco_warp", "warp", "torch", "device"):
        _require(isinstance(engine.get(key), str) and engine[key], f"缺少引擎版本 {key}")
    _require(isinstance(engine.get("cuda_graph"), bool), "缺少 cuda_graph 设置")
    falls = _number(metrics.get("falls"), "falls", integer=True)
    _require(falls <= worlds, "跌倒世界数超过总数")
    _require(_number(metrics.get("nonfinite_worlds"), "nonfinite_worlds", integer=True) == 0, "MuJoCo 出现非有限数值")
    _number(metrics.get("tracking_samples"), "tracking_samples（旧记录需重新评测）", minimum=1, integer=True)
    tracking = metrics.get("tracking_rmse")
    _require(isinstance(tracking, dict), "缺少跟踪误差")
    for axis in ("vx", "vy", "wz"):
        _number(tracking.get(axis), f"tracking_rmse.{axis}")
    steps = _number((result.get("performance") or {}).get("physics_steps"), "physics_steps", minimum=1, integer=True)
    _require(steps == int(round(setup["seconds"] / model["physics_dt_s"])) * worlds, "MuJoCo 执行步数不完整")
    return worlds, falls, tracking


def gate_mjwarp(candidate: dict | None, baseline: dict | None, *, candidate_hash=None, baseline_hash=None) -> dict:
    try:
        n1, k1, ct = _mj_summary(candidate, candidate_hash)
        n2, k2, bt = _mj_summary(baseline, baseline_hash)
        for field in ("setup", "engine", "evaluator_sha256"):
            _require(candidate[field] == baseline[field], f"MuJoCo {field} 不同，不可比")
        for field in ("xml_sha256", "config_sha256", "physics_dt_s", "policy_dt_s"):
            _require(candidate["model"][field] == baseline["model"][field], f"MuJoCo 模型 {field} 不同，不可比")
    except (EvidenceError, KeyError, TypeError, AttributeError) as exc:
        return _insufficient(exc)
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-12))
    z = (k1 / n1 - k2 / n2) / se
    worse = z > RULES["mj_fall_z_max"]
    tracking_ok = all(ct[a] <= bt[a] * (1 + RULES["mj_tracking_relative"]) + RULES["mj_tracking_absolute"]
                      for a in ("vx", "vy", "wz"))
    return {"status": "FAIL" if worse or not tracking_ok else "PASS", "z": z, "falls_ok": not worse,
            "tracking_ok": tracking_ok, "candidate_fall_rate": k1 / n1, "baseline_fall_rate": k2 / n2,
            "candidate_tracking": ct, "baseline_tracking": bt}


def gate_series(series: dict | None, candidate_id: str, baseline_id: str) -> dict:
    try:
        _require(isinstance(series, dict) and {series.get("pack_a"), series.get("pack_b")} == {candidate_id, baseline_id}
                 and candidate_id != baseline_id, "没有候选对基线的系列赛")
        rounds = series.get("rounds")
        requested = _number(series.get("requested_rounds"), "requested_rounds（旧系列赛未记录计划轮数）", minimum=2, integer=True)
        _require(series.get("status") == "PASS" and series.get("completed") is True, "系列赛未完整完成")
        _require(isinstance(rounds, list) and len(rounds) == requested == series.get("rounds_valid")
                 == series.get("rounds_played") and requested % 2 == 0, "系列赛缺少完整的主客互换轮次")
        falls = {candidate_id: 0, baseline_id: 0}
        for i, round_ in enumerate(rounds, 1):
            _require(round_.get("round") == i and round_.get("status") == "PASS"
                     and round_.get("failed_checks") == [], f"第 {i} 轮未通过比赛检查")
            assignment = round_.get("assignment")
            expected = {"5": series["pack_a"], "70": series["pack_b"]} if i % 2 else {"5": series["pack_b"], "70": series["pack_a"]}
            _require(assignment == expected, f"第 {i} 轮没有按计划交换队伍")
            for team, pack_id in assignment.items():
                stats = round_["teams"][team]
                _require(stats.get("pack_id") == pack_id, "比赛中的实际策略与分配不符")
                falls[pack_id] += _number(stats.get("fall_episodes_sampled"), "fall_episodes_sampled", integer=True)
        c, b = series["totals"][candidate_id], series["totals"][baseline_id]
        for pack_id, total in ((candidate_id, c), (baseline_id, b)):
            _require(_number(total.get("fall_episodes_sampled"), "total.fall_episodes_sampled", integer=True)
                     == falls[pack_id], "系列赛跌倒汇总与逐场结果不符")
    except (EvidenceError, KeyError, TypeError, AttributeError) as exc:
        return _insufficient(exc)
    falls_ok = falls[candidate_id] <= falls[baseline_id]
    return {"status": "PASS" if falls_ok else "FAIL", "falls_ok": falls_ok,
            "record": (series.get("record") or {}).get(candidate_id), "candidate": c, "baseline": b,
            "note": "比分噪声大，只作参考，不作为通过条件"}


def gate_fragility(run_dir, candidate_id: str, baseline_id: str, *, candidate_hash=None, baseline_hash=None) -> dict:
    """Paired MuJoCo Warp fragility sweep: every required axis must be non-inferior (C50 margin ratio)."""
    from . import atlas

    try:
        _require(bool(run_dir), "缺少易损性图谱（forge atlas）证据")
        directory = Path(run_dir)
        raw, design = util.read_json(directory / "raw.json"), util.read_json(directory / "design.json")
        _require(isinstance(raw, dict) and raw.get("schema") == atlas.RAW_SCHEMA and raw.get("status") == "COMPLETED",
                 "图谱原始数据不完整")
        _require(not raw.get("parity_mode"), "一致性模式不是易损性证据")
        _hash(raw.get("evaluator_sha256"), "图谱 evaluator_sha256")
        missing = [axis for axis in atlas.REQUIRED_AXES if axis not in ((design or {}).get("axes") or [])]
        _require(not missing, "图谱缺少维度: " + ", ".join(missing))
        policies = raw.get("policies") or {}
        _require(candidate_id in policies and baseline_id in policies, "图谱没有在同一世界表上同时评测候选与基线")
        _require(policies[candidate_id].get("policy_sha256") == _hash(candidate_hash, "候选 walk sha256"), "图谱候选策略哈希不符")
        _require(policies[baseline_id].get("policy_sha256") == _hash(baseline_hash, "基线 walk sha256"), "图谱基线策略哈希不符")
        analysis = atlas.analyze(directory, comparisons=[(candidate_id, baseline_id)], write=False)
    except (EvidenceError, atlas.AtlasError, KeyError, TypeError, AttributeError, OSError, ValueError) as exc:
        return _insufficient(exc)
    comparison = analysis["comparisons"][0]
    return {"status": comparison["verdict"], "run": str(directory), "raw_sha256": analysis["raw_sha256"],
            "design_sha256": analysis["design_sha256"], "analysis_sha256": analysis["analysis_sha256"],
            "evaluator_sha256": analysis["evaluator_sha256"],
            "axes": {axis: {k: row[k] for k in ("ratio", "ci95", "ci_simultaneous", "status", "reason", "better", "worse")}
                     for axis, row in comparison["axes"].items()},
            "better_axes": comparison["better_axes"], "worse_axes": comparison["worse_axes"],
            "failed_axes": comparison["failed_axes"]}


def _numerics(pack):
    provenance = pack.get("provenance") or {}
    tri, export = provenance.get("tri_check"), provenance.get("export_manifest")
    try:
        _require(isinstance(tri, dict) and isinstance(export, dict), "缺少三方校验及导出记录")
        _require(export.get("checkpoint_sha256") == _hash(provenance.get("checkpoint_sha256"), "checkpoint_sha256"),
                 "导出 checkpoint 身份不一致")
        _require((export.get("onnx") or {}).get("sha256") == _hash(pack.get("components", {}).get("walk", {}).get("sha256"), "walk.sha256"),
                 "导出 ONNX 与运控包不一致")
        _require(tri == export.get("tri_check"), "三方校验记录与导出清单不一致")
        for case in ("random_batch1", "random_batch4"):
            row = tri["results"][case]
            for key in ("eager_vs_script_maxabs", "eager_vs_ort_maxabs"):
                _number(row.get(key), f"{case}.{key}")
            _require(row.get("eager_vs_script_ok") is True and row.get("eager_vs_ort_ok") is True,
                     f"{case} 三方校验未通过")
    except (EvidenceError, KeyError, TypeError, AttributeError) as exc:
        return _insufficient(exc)
    return {"status": "PASS" if tri.get("verdict") == "PASS" else "FAIL", "tri_check": tri}


def assess(candidate_id: str, isaac_candidate=None, isaac_baseline=None, mj_candidate=None, mj_baseline=None,
           series=None, atlas_run=None) -> dict:
    from .training import OFFICIAL_WALK_SHA256

    pack, baseline = packs.load(candidate_id), packs.load(packs.BASELINE_ID)
    verify = packs.verify(candidate_id)
    baseline_verify = packs.verify(packs.BASELINE_ID)
    checkpoint_hash = (pack.get("provenance") or {}).get("checkpoint_sha256")
    walk_hash = pack.get("components", {}).get("walk", {}).get("sha256")
    gates = {
        "L0_identity": {"status": "PASS" if verify["status"] == baseline_verify["status"] == "PASS" else "FAIL",
                        "checks": verify["checks"], "baseline_checks": baseline_verify["checks"]},
        "L1_numerics": _numerics(pack),
        "G1_isaacgym_eval": gate_isaac(isaac_candidate, isaac_baseline, candidate_hash=checkpoint_hash or "missing",
                                      baseline_hash=OFFICIAL_WALK_SHA256),
        "G2_mujoco_warp": gate_mjwarp(mj_candidate, mj_baseline, candidate_hash=walk_hash or "missing",
                                    baseline_hash=baseline["components"]["walk"]["sha256"]),
        "G2F_fragility": gate_fragility(atlas_run, candidate_id, packs.BASELINE_ID, candidate_hash=walk_hash or "missing",
                                        baseline_hash=baseline["components"]["walk"]["sha256"]),
        "G3_simrobot_series": gate_series(series, candidate_id, packs.BASELINE_ID),
        "L5_hardware": {"status": "NOT_VERIFIED", "reason": "未连接机器人；真机闭环需要单独授权"},
    }
    simulated = [g["status"] for k, g in gates.items() if k != "L5_hardware"]
    verdict = "NOT_QUALIFIED" if "FAIL" in simulated else "INSUFFICIENT_EVIDENCE" if "INSUFFICIENT" in simulated else "SIM_QUALIFIED"
    inputs = {"candidate_pack": pack, "baseline_pack": baseline, "isaac_candidate": isaac_candidate,
              "isaac_baseline": isaac_baseline, "mj_candidate": mj_candidate, "mj_baseline": mj_baseline, "series": series,
              "atlas": {"run": str(atlas_run) if atlas_run else None,
                        "raw_sha256": gates["G2F_fragility"].get("raw_sha256"),
                        "design_sha256": gates["G2F_fragility"].get("design_sha256")}}
    # A string preserves even rejected NaN evidence without making the report itself invalid JSON.
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    report = {"schema": "forge.gates/2", "rule_version": RULE_VERSION, "rules": dict(RULES),
              "gate_source_sha256": util.sha256_file(__file__), "evidence": {"sha256": util.sha256_bytes(canonical.encode()),
                                                                            "canonical_json": canonical},
              "pack_id": candidate_id, "baseline": packs.BASELINE_ID, "verdict": verdict, "gates": gates, "at": util.now_iso(),
              "policy": "SIM_QUALIFIED 只表示在这些仿真条件下不劣于官方；不替换官方步态，不代表真机可部署"}
    out = paths.RUNS / "gates" / f"{util.stamp()}_{util.safe_name(candidate_id, 40)}.json"
    report["path"] = str(out)
    util.write_json(out, report)
    return report


def load_json(path: str | None):
    return util.read_json(Path(path)) if path else None
