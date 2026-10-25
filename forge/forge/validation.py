"""Repeatable SimRobot experiments with one changed factor and retained evidence."""
from __future__ import annotations

import math
from pathlib import Path

from . import arena as arena_mod, match, packs, paths, scenarios, strategies, util
from .locking import exclusive_simulation
from .runtime import interrupt_on_termination

RULE_VERSION = "forge.simrobot-validation/1"
MOTION_RULES = {"minimum_response_ratio": 0.8, "stop_displacement_max_m": 0.1}


def plan(mode: str, *, motion_pack: str = packs.BASELINE_ID, strategy_id: str = strategies.BASELINE_ID,
         source_arena: str = "main", repetitions: int = 1, seconds: int = 120, vision: str = "cuda", record: bool = True) -> dict:
    if mode not in ("motion", "strategy"):
        raise ValueError("验证类型必须为 motion 或 strategy")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 5:
        raise ValueError("重复次数必须在 1..5")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 600:
        raise ValueError("比赛时长必须在 60..600 秒")
    if vision not in ("cuda", "cpu") or not isinstance(record, bool):
        raise ValueError("视觉或录像选项无效")
    motion = packs.load(motion_pack)
    strategies.motion_only(motion)
    if packs.verify(motion_pack)["status"] != "PASS":
        raise ValueError("运控包校验失败")
    strategy = strategies.load(strategy_id)
    if mode == "motion" and strategy_id != strategies.BASELINE_ID:
        raise ValueError("运控验证需保持官方策略；战术对照请使用策略验证")
    source = arena_mod.Arena(source_arena)
    if not source.state():
        raise ValueError("作为程序来源的 arena 不存在")
    missing_modules = [name for name in motion.get("modules", {}) if not source.has_module(name)]
    if missing_modules:
        raise ValueError("程序来源不包含候选模块：" + ", ".join(missing_modules) + "；请选择对应的已编译 arena")
    cases = []
    if mode == "motion":
        for repeat in range(1, repetitions + 1):
            roles = ("baseline", "candidate") if repeat % 2 else ("candidate", "baseline")
            for role in roles:
                cases.append({"id": f"r{repeat}-{role}", "repeat": repeat, "role": role,
                              "motion_pack": packs.BASELINE_ID if role == "baseline" else motion_pack,
                              "case": scenarios.MOTION_ID, "seconds": 30})
    else:
        for repeat in range(1, repetitions + 1):
            # Each strategy plays on both jerseys and both kickoff assignments.
            for team, kickoff in ((5, 5), (70, 5), (70, 70), (5, 70)):
                cases.append({"id": f"r{repeat}-candidate-t{team}-kickoff-t{kickoff}", "repeat": repeat,
                              "candidate_team": team, "kickoff_team": kickoff, "seconds": seconds, "case": "match"})
    return {"schema": RULE_VERSION, "mode": mode, "motion_pack": motion_pack, "strategy_id": strategy_id,
            "source_arena": source.name, "source": str(source.source), "vision": vision, "record": record,
            "repetitions": repetitions, "seconds": seconds, "cases": cases, "case_count": len(cases),
            "simulation_seconds": sum(c["seconds"] for c in cases),
            "motion_snapshot": motion, "strategy_snapshot": strategy,
            "rules": dict(MOTION_RULES), "robot_connected": False,
            "scope": "固定指令与初始场景的可重复实验；正常渲染相机。保留完整输入，不声称线程调度逐位确定。"}


def _motion_comparison(results: list[dict], requested: int) -> dict:
    baseline = [r["result"] for r in results if r["case"]["role"] == "baseline"]
    candidate = [r["result"] for r in results if r["case"]["role"] == "candidate"]
    if len(baseline) != requested or len(candidate) != requested or not all(r["status"] == "PASS" for r in baseline):
        return {"verdict": "INSUFFICIENT_EVIDENCE", "reason": "基线没有完整通过固定指令验证"}
    rows = []
    for segment, metric in (("forward", "forward_m"), ("left", "left_m"), ("turn", "yaw_change_rad"), ("settled_stop", "net_displacement_m")):
        b = sum(r["motion_segments"][segment][metric] for r in baseline) / requested
        values = [r.get("motion_segments", {}).get(segment, {}).get(metric) for r in candidate]
        if any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
            return {"verdict": "INSUFFICIENT_EVIDENCE", "reason": "候选缺少有效运动样本"}
        c = sum(values) / requested
        ok = c <= MOTION_RULES["stop_displacement_max_m"] if segment == "settled_stop" else c >= b * MOTION_RULES["minimum_response_ratio"]
        rows.append({"segment": segment, "metric": metric, "baseline": b, "candidate": c, "delta": c - b, "ok": ok})
    runtime_keys = {"process_exit_zero", "completed_requested_steps", "runtime_network_readback", "runtime_behavior_parameters", "no_console_errors"}
    if not all(all(r["checks"].get(k) is True for k in runtime_keys) for r in candidate):
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "NO_REGRESSION_OBSERVED" if all(r["ok"] for r in rows) and all(r["status"] == "PASS" for r in candidate) else "REGRESSION_OBSERVED"
    return {"verdict": verdict, "metrics": rows, "rules": dict(MOTION_RULES),
            "note": "仅覆盖此固定指令和重复次数；不是多引擎晋级，也不表示候选优于官方。"}


def _strategy_comparison(results: list[dict], expected_count: int) -> dict:
    if len(results) != expected_count or not all(r["result"]["status"] == "PASS" for r in results):
        return {"verdict": "INSUFFICIENT_EVIDENCE", "reason": "主客与开球条件尚未完整通过运行验证"}
    totals = {role: {"goals": 0, "goals_against": 0, "ball_contacts": 0, "fall_episodes_sampled": 0,
                     "ball_seen_samples": 0, "skill_samples": {s: 0 for s in scenarios.SKILLS}}
              for role in ("candidate", "baseline")}
    record = {"win": 0, "draw": 0, "loss": 0}
    conditions = []
    for row in results:
        candidate_team = row["case"]["candidate_team"]
        c = row["result"]["teams"][str(candidate_team)]
        b = row["result"]["teams"][str(70 if candidate_team == 5 else 5)]
        record["win" if c["goals"] > b["goals"] else "loss" if c["goals"] < b["goals"] else "draw"] += 1
        for role, stats in (("candidate", c), ("baseline", b)):
            for metric in totals[role]:
                if metric == "skill_samples":
                    for skill in scenarios.SKILLS:
                        totals[role][metric][skill] += stats[metric][skill]
                else:
                    totals[role][metric] += stats[metric]
        conditions.append({"case_id": row["case"]["id"], "candidate_team": candidate_team,
                           "kickoff_team": row["case"]["kickoff_team"], "candidate_goals": c["goals"], "baseline_goals": b["goals"]})
    verdict = "REGRESSION_OBSERVED" if totals["candidate"]["fall_episodes_sampled"] > totals["baseline"]["fall_episodes_sampled"] else "READY_FOR_REVIEW"
    return {"verdict": verdict, "record": record, "totals": totals, "conditions": conditions,
            "note": "比分、触球与技能请求供对照审阅；技能请求不等于成功传射，短系列赛不自动认定战术更优。"}


@interrupt_on_termination()
@exclusive_simulation(match.MatchError)
def run(mode: str, *, on_line=None, **options) -> dict:
    specification = plan(mode, **options)
    identifier = f"{util.stamp()}_{mode}"
    directory = paths.RUNS / "validations" / identifier
    directory.mkdir(parents=True)
    arena = arena_mod.Arena(f"validation-{identifier}", source=Path(specification["source"]))
    report = {"schema": RULE_VERSION, "id": identifier, "status": "RUNNING", "started_at": util.now_iso(),
              "plan": specification, "arena": arena.name, "cases": [], "verdict": "INSUFFICIENT_EVIDENCE",
              "runner_sha256": util.sha256_file(__file__), "robot_connected": False}

    def save():
        util.write_json(directory / "validation.json", report)

    save()
    try:
        arena.materialize()
        if mode == "strategy":
            baseline = strategies.compose(specification["motion_pack"], strategies.BASELINE_ID)
            candidate = strategies.compose(specification["motion_pack"], specification["strategy_id"])
            report["composed_packs"] = {"baseline": baseline, "candidate": candidate}
        for index, case in enumerate(specification["cases"], 1):
            if mode == "motion":
                assignment = {5: case["motion_pack"], 70: packs.BASELINE_ID}
            else:
                assignment = {team: candidate["id"] if team == case["candidate_team"] else baseline["id"] for team in (5, 70)}
            for team, identifier_ in assignment.items():
                arena.flash(team, identifier_)
            if on_line:
                on_line(f"[validation] {index}/{len(specification['cases'])} {case['id']}\n")
            result = match.run_match(arena, seconds=case["seconds"], record=specification["record"],
                                     vision=specification["vision"], tag=case["id"], case=case["case"],
                                     kickoff_team=case.get("kickoff_team"), behavior_readback=True, on_line=on_line)
            result_file = Path(result["run"]) / "result.json"
            report["cases"].append({"case": case, "result": result, "result_sha256": util.sha256_file(result_file)})
            save()
        comparison = _motion_comparison(report["cases"], specification["repetitions"]) if mode == "motion" else _strategy_comparison(report["cases"], specification["case_count"])
        report.update(status="COMPLETED", ended_at=util.now_iso(), comparison=comparison, verdict=comparison["verdict"])
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED", ended_at=util.now_iso(), error=str(exc))
        save()
        raise
    save()
    report["path"] = str(directory / "validation.json")
    return report


def list_runs() -> list[dict]:
    rows = []
    for path in sorted((paths.RUNS / "validations").glob("*/validation.json"), reverse=True):
        data = util.read_json(path) or {}
        rows.append({"id": path.parent.name, "status": data.get("status"), "verdict": data.get("verdict"),
                     "mode": data.get("plan", {}).get("mode"), "completed_cases": len(data.get("cases", [])),
                     "case_count": data.get("plan", {}).get("case_count"), "started_at": data.get("started_at"),
                     "motion_pack": data.get("plan", {}).get("motion_pack"), "strategy_id": data.get("plan", {}).get("strategy_id")})
    return rows


def load_run(identifier: str) -> dict:
    root = paths.RUNS / "validations"
    directory = root / identifier
    if directory.resolve().parent != root.resolve():
        raise ValueError("验证运行标识无效")
    report = util.read_json(directory / "validation.json")
    if not report:
        raise ValueError("验证运行不存在")
    return report


def case_directory(identifier: str, case_id: str) -> Path:
    report = load_run(identifier)
    row = next((row for row in report["cases"] if row["case"]["id"] == case_id), None)
    if row is None:
        raise ValueError("验证场景不存在或尚未完成")
    directory = Path(row["result"]["run"]).resolve()
    if directory.parent not in ((paths.RUNS / "motion").resolve(), (paths.RUNS / "matches").resolve()):
        raise ValueError("验证产物不在受控目录内")
    return directory
