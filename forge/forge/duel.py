"""Anytime-valid sequential duels in SimRobot: play paired matches until the evidence decides.

A fixed two-match series cannot tell two motion packs or two strategies apart: goals are
rare and noisy.  A duel instead keeps playing *pairs* of matches (the candidate once on each
jersey; consecutive pairs alternate the kickoff team, so two pairs cover team x kickoff)
and after every pair updates a confidence sequence for the mean pair outcome.

Endpoints, fixed before the first match:

* primary: goal difference per pair, sum over both matches of (candidate - baseline goals),
  clipped to +/- ``GOAL_CLIP`` so that the observation is bounded;
* secondary (reported, never used for the decision): territory, the mean ball position
  along the candidate's attacking direction during PLAYING, averaged over the pair [m].

Inference uses predictable plug-in betting confidence sequences for bounded means
(hedged capital process, Waudby-Smith & Ramdas, JRSS-B 2024).  They are valid at every
stopping time: the duel may stop as soon as the decision is reached, or be interrupted
and resumed later, without inflating the error rate.  Decision on the primary endpoint:
STRONGER when the whole sequence is above 0, WEAKER when it is below 0, EQUIVALENT when it
lies inside +/- delta, otherwise CONTINUE, and INCONCLUSIVE once the pair cap is reached.

Every match keeps its own run directory, configuration read-back and recording; the duel
ledger records hashes of each result.  A match counts when its *execution* checks pass
(process, camera perception, network/module read-back ...).  Quality findings such as a
robot that failed to get up are part of the football outcome and never void a match;
otherwise replays would censor exactly the results that hurt one side.  Only the first
execution-valid match of each (pair, side) counts; replays exist only for execution failures.
Simulation evidence only, not a hardware result.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import arena as arena_mod, match, packs, paths, strategies, util
from .locking import exclusive_simulation
from .runtime import interrupt_on_termination

SCHEMA = "forge.duel/1"
RUNS = paths.RUNS / "duels"
GOAL_CLIP = 4
TERRITORY_CLIP_M = 4.0  # pair means beyond +/- 4 m are clipped (field half-length is 7.5 m)
PLAYING = 3
ATTACK_DIRECTION = {5: -1.0, 70: 1.0}  # from recorded goals: first team scores at -x, second at +x
GRID = 2001


class DuelError(ValueError):
    pass


# ------------------------------------------------------------------ statistics
def confidence_sequence(observations, alpha: float = 0.05, c: float = 0.75, grid: int = GRID) -> dict:
    """Running-intersection betting CS for the mean of observations in [0, 1].

    Returns the bounds after every observation (on the [0, 1] scale) plus the final
    two-sided wealth at m = 1/2 for reference.  Predictable plug-in bets:
    lambda_t = sqrt(2 log(2/alpha) / (sigma2_{t-1} t log(1+t))), truncated at c/m and c/(1-m).
    """
    y = np.asarray(observations, dtype=float)
    if y.size and (np.any(y < 0) or np.any(y > 1) or not np.all(np.isfinite(y))):
        raise DuelError("置信序列的观测必须在 [0, 1]")
    m = np.linspace(0.0, 1.0, grid)[1:-1]
    log_plus = np.zeros_like(m)
    log_minus = np.zeros_like(m)
    lower, upper = 0.0, 1.0
    history = []
    mean_hat, var_hat = 0.5, 0.25
    total, squares = 0.0, 0.0
    threshold = math.log(1.0 / alpha)
    for t, value in enumerate(y, 1):
        lam = math.sqrt(2.0 * math.log(2.0 / alpha) / (var_hat * t * math.log(1.0 + t)))
        lam_plus = np.minimum(lam, c / m)
        lam_minus = np.minimum(lam, c / (1.0 - m))
        log_plus += np.log1p(lam_plus * (value - m))
        log_minus += np.log1p(-lam_minus * (value - m))
        hedged = np.maximum(log_plus + math.log(0.5), log_minus + math.log(0.5))
        inside = m[hedged < threshold]
        if inside.size:
            lower, upper = max(lower, float(inside.min())), min(upper, float(inside.max()))
        else:  # empty CS: keep the last interval (can only happen with probability <= alpha)
            lower, upper = lower, upper
        history.append([lower, upper])
        total += value
        squares += (value - mean_hat) ** 2
        mean_hat = (0.5 + total) / (t + 1)
        var_hat = (0.25 + squares) / (t + 1)
    return {"bounds": history, "lower": lower, "upper": upper, "n": int(y.size), "alpha": alpha, "c": c,
            "method": "hedged capital, predictable plug-in (Waudby-Smith & Ramdas 2024), running intersection"}


def _scaled_goal(d):
    return (min(GOAL_CLIP, max(-GOAL_CLIP, d)) + GOAL_CLIP) / (2 * GOAL_CLIP)


def _unscale_goal(v):
    return v * 2 * GOAL_CLIP - GOAL_CLIP


def _scaled_territory(t):
    return (min(TERRITORY_CLIP_M, max(-TERRITORY_CLIP_M, t)) + TERRITORY_CLIP_M) / (2 * TERRITORY_CLIP_M)


def _unscale_territory(v):
    return v * 2 * TERRITORY_CLIP_M - TERRITORY_CLIP_M


def decide(goal_cs: dict, delta: float, pairs: int, max_pairs: int) -> str:
    lo, hi = _unscale_goal(goal_cs["lower"]), _unscale_goal(goal_cs["upper"])
    if pairs == 0:
        return "CONTINUE"
    if lo > 0:
        return "STRONGER"
    if hi < 0:
        return "WEAKER"
    if -delta < lo and hi < delta:
        return "EQUIVALENT"
    return "INCONCLUSIVE" if pairs >= max_pairs else "CONTINUE"


def counts(row: dict) -> bool:
    """Execution validity only; recovery or other quality results never void a match."""
    return row.get("execution_status") == "PASS" and row.get("territory_m") is not None


def summarize(record: dict) -> dict:
    """Recompute pairs, sequences and the decision from the stored per-match outcomes."""
    matches, seen = [], set()
    for row in record["matches"]:
        key = (row["pair"], row["candidate_team"])
        if counts(row) and key not in seen:  # first execution-valid result of each side counts
            seen.add(key)
            matches.append(row)
    by_pair = {}
    for row in matches:
        by_pair.setdefault(row["pair"], []).append(row)
    pairs = []
    for index in sorted(by_pair):
        rows = by_pair[index]
        if len(rows) != 2 or {r["candidate_team"] for r in rows} != {5, 70}:
            continue
        goal = sum(r["candidate_goals"] - r["baseline_goals"] for r in rows)
        territory = sum(r["territory_m"] for r in rows) / 2
        pairs.append({"pair": index, "goal_difference": goal, "territory_m": territory,
                      "kickoff_team": rows[0]["kickoff_team"], "matches": [r["run"] for r in rows]})
    alpha = record["plan"]["alpha"]
    goal_cs = confidence_sequence([_scaled_goal(p["goal_difference"]) for p in pairs], alpha)
    territory_cs = confidence_sequence([_scaled_territory(p["territory_m"]) for p in pairs], alpha)
    decision = decide(goal_cs, record["plan"]["delta_goals"], len(pairs), record["plan"]["max_pairs"])
    wins = sum(1 for r in matches if r["candidate_goals"] > r["baseline_goals"])
    losses = sum(1 for r in matches if r["candidate_goals"] < r["baseline_goals"])
    return {
        "pairs": pairs, "pairs_complete": len(pairs), "matches_valid": len(matches),
        "matches_invalid": sum(1 for m in record["matches"] if not counts(m)),
        "matches_superseded": len(record["matches"]) - len(matches) - sum(1 for m in record["matches"] if not counts(m)),
        "record": {"win": wins, "draw": len(matches) - wins - losses, "loss": losses},
        "goals": {"candidate": sum(r["candidate_goals"] for r in matches), "baseline": sum(r["baseline_goals"] for r in matches)},
        "goal_difference_cs": {"lower": _unscale_goal(goal_cs["lower"]), "upper": _unscale_goal(goal_cs["upper"]),
                               "trajectory": [[_unscale_goal(a), _unscale_goal(b)] for a, b in goal_cs["bounds"]],
                               "mean": float(np.mean([p["goal_difference"] for p in pairs])) if pairs else None,
                               "clip": GOAL_CLIP, "method": goal_cs["method"]},
        "territory_cs": {"lower": _unscale_territory(territory_cs["lower"]), "upper": _unscale_territory(territory_cs["upper"]),
                         "trajectory": [[_unscale_territory(a), _unscale_territory(b)] for a, b in territory_cs["bounds"]],
                         "mean": float(np.mean([p["territory_m"] for p in pairs])) if pairs else None,
                         "note": "辅助指标：只报告，不参与判定"},
        "decision": decision,
    }


# ------------------------------------------------------------------ match evidence
def territory(console: Path, candidate_team: int) -> tuple[float, int]:
    """Mean ball x along the candidate's attack direction while PLAYING, metres."""
    games = match.parse_audit(console.read_text(errors="replace").splitlines())["game"]
    values = [float(g["ball_x_mm"]) / 1000.0 * ATTACK_DIRECTION[candidate_team]
              for g in games if g.get("state") == str(PLAYING) and g.get("ball_valid", "1") == "1" and "ball_x_mm" in g]
    if not values:
        raise DuelError("比赛没有 PLAYING 状态的球位置样本")
    return sum(values) / len(values), len(values)


def plan(kind: str, candidate: str, *, baseline: str | None = None, motion_pack: str = packs.BASELINE_ID,
         max_pairs: int = 10, seconds: int = 120, alpha: float = 0.05, delta_goals: float = 0.5,
         source_arena: str = "main", vision: str = "cuda", record_first_pair: bool = True) -> dict:
    if kind not in ("motion", "strategy"):
        raise DuelError("对决类型必须是 motion 或 strategy")
    if isinstance(max_pairs, bool) or not isinstance(max_pairs, int) or not 1 <= max_pairs <= 200:
        raise DuelError("max_pairs 需在 1..200")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 600:
        raise DuelError("比赛时长需在 60..600 秒")
    if not 0.001 <= float(alpha) <= 0.2 or not 0 < float(delta_goals) <= GOAL_CLIP:
        raise DuelError(f"alpha 需在 0.001..0.2，delta 需在 (0, {GOAL_CLIP}]")
    if vision not in ("cuda", "cpu"):
        raise DuelError("vision 必须是 cuda 或 cpu")
    source = arena_mod.Arena(source_arena)
    if not source.state():
        raise DuelError("作为程序来源的 arena 不存在")
    if kind == "motion":
        baseline = baseline or packs.BASELINE_ID
        if candidate == baseline:
            raise DuelError("候选与基线不能相同；同模型对照请使用字节相同的副本包")
        snapshots = {"candidate": packs.load(candidate), "baseline": packs.load(baseline)}
        for pack in snapshots.values():
            if packs.verify(pack["id"])["status"] != "PASS":
                raise DuelError(f"运控包校验失败: {pack['id']}")
            missing = [name for name in pack.get("modules", {}) if not source.has_module(name)]
            if missing:
                raise DuelError("程序来源不包含模块：" + ", ".join(missing))
    else:
        baseline = baseline or strategies.BASELINE_ID
        if candidate == baseline:
            raise DuelError("候选策略与基线策略不能相同")
        strategies.motion_only(packs.load(motion_pack))
        snapshots = {"candidate": strategies.load(candidate), "baseline": strategies.load(baseline),
                     "motion_pack": packs.load(motion_pack)}
    return {"schema": SCHEMA, "kind": kind, "candidate": candidate, "baseline": baseline, "motion_pack": motion_pack,
            "max_pairs": max_pairs, "seconds": seconds, "alpha": float(alpha), "delta_goals": float(delta_goals),
            "goal_clip": GOAL_CLIP, "source_arena": source.name, "source": str(source.source), "vision": vision,
            "record_first_pair": record_first_pair, "snapshots": snapshots,
            "design": "每对两场：候选分别在 T5、T70；相邻两对交替开球队，两对覆盖队伍×开球四种组合",
            "endpoints": {"primary": "每对净胜球（候选−基线，截断 ±4）", "secondary": "控球区域：PLAYING 时球沿候选进攻方向的平均位置（m）"},
            "robot_connected": False}


def _assignment(record, pair_index, candidate_team):
    plan_ = record["plan"]
    if plan_["kind"] == "motion":
        return {candidate_team: plan_["candidate"], (70 if candidate_team == 5 else 5): plan_["baseline"]}
    composed = record["composed_packs"]
    return {candidate_team: composed["candidate"]["id"], (70 if candidate_team == 5 else 5): composed["baseline"]["id"]}


@interrupt_on_termination()
@exclusive_simulation(match.MatchError)
def run(kind: str | None = None, candidate: str | None = None, *, resume: str | None = None, extra_pairs: int = 0,
        on_line=None, **options) -> dict:
    """Start a new duel, or resume ``resume`` (optionally raising its pair cap by ``extra_pairs``)."""
    if resume:
        directory = _directory(resume)
        record = util.read_json(directory / "duel.json")
        if not record:
            raise DuelError("对决记录不存在")
        if extra_pairs:
            if isinstance(extra_pairs, bool) or not isinstance(extra_pairs, int) or not 1 <= extra_pairs <= 200:
                raise DuelError("extra_pairs 需在 1..200")
            record["plan"]["max_pairs"] += extra_pairs
            record.setdefault("cap_history", []).append({"at": util.now_iso(), "max_pairs": record["plan"]["max_pairs"]})
        arena = arena_mod.Arena(record["arena"], source=Path(record["plan"]["source"]))
        record["resumed_at"] = record.get("resumed_at", []) + [util.now_iso()]
    else:
        specification = plan(kind, candidate, **options)
        identifier = f"{util.stamp()}_{kind}_{util.safe_name(candidate, 40)}"
        directory = RUNS / identifier
        directory.mkdir(parents=True)
        arena = arena_mod.Arena(f"duel-{identifier}", source=Path(specification["source"]))
        record = {"schema": SCHEMA, "id": identifier, "status": "RUNNING", "started_at": util.now_iso(), "plan": specification,
                  "arena": arena.name, "matches": [], "runner_sha256": util.sha256_file(__file__), "robot_connected": False}

    def save():
        record["summary"] = summarize(record)
        record["decision"] = record["summary"]["decision"]
        util.write_json(directory / "duel.json", record)

    save()
    try:
        if not arena.state():
            arena.materialize()
        if record["plan"]["kind"] == "strategy" and "composed_packs" not in record:
            record["composed_packs"] = {
                "candidate": strategies.compose(record["plan"]["motion_pack"], record["plan"]["candidate"]),
                "baseline": strategies.compose(record["plan"]["motion_pack"], record["plan"]["baseline"])}
        record["status"] = "RUNNING"
        while record["summary"]["decision"] == "CONTINUE":
            # Lowest pair index that is not complete; an invalid match is replayed on the same side.
            done = {(m["pair"], m["candidate_team"]) for m in record["matches"] if counts(m)}
            complete = {p["pair"] for p in record["summary"]["pairs"]}
            pair = 0
            while pair in complete:
                pair += 1
            kickoff = 5 if pair % 2 == 0 else 70
            for candidate_team in (5, 70):
                if (pair, candidate_team) in done:
                    continue
                assignment = _assignment(record, pair, candidate_team)
                for team, pack_id in assignment.items():
                    arena.flash(team, pack_id)
                tag = f"duel-p{pair + 1}-cand-t{candidate_team}-ko{kickoff}"
                if on_line:
                    on_line(f"[duel] pair {pair + 1}/{record['plan']['max_pairs']} candidate T{candidate_team}, kickoff T{kickoff}\n")
                result = match.run_match(arena, seconds=record["plan"]["seconds"],
                                         record=record["plan"]["record_first_pair"] and pair == 0,
                                         vision=record["plan"]["vision"], tag=tag, kickoff_team=kickoff,
                                         behavior_readback=record["plan"]["kind"] == "strategy", on_line=on_line)
                other = 70 if candidate_team == 5 else 5
                row = {"pair": pair, "candidate_team": candidate_team, "kickoff_team": kickoff, "run": result["run"],
                       "status": result["status"], "execution_status": result.get("execution_status"),
                       "failed_checks": [k for k, v in result["checks"].items() if not v],
                       "candidate_goals": result["teams"][str(candidate_team)]["goals"],
                       "baseline_goals": result["teams"][str(other)]["goals"],
                       "candidate_falls": result["teams"][str(candidate_team)]["fall_episodes_sampled"],
                       "baseline_falls": result["teams"][str(other)]["fall_episodes_sampled"],
                       "recovery_conclusion": (result.get("recovery") or {}).get("conclusion"),
                       "result_sha256": util.sha256_file(Path(result["run"]) / "result.json"),
                       "assignment": {str(k): v for k, v in assignment.items()}}
                try:
                    row["territory_m"], row["territory_samples"] = territory(Path(result["run"]) / "console.log", candidate_team)
                except DuelError as exc:
                    row.update(territory_m=None, invalid_reason=str(exc))
                row["valid"] = counts(row)
                if not row["valid"]:
                    row.setdefault("invalid_reason", "执行检查未通过：" + ", ".join(
                        k for k, v in result["checks"].items() if not v and k not in ("no_failed_recovery_observed",)))
                record["matches"].append(row)
                save()
                if on_line:
                    s = record["summary"]
                    cs = s["goal_difference_cs"]
                    on_line(f"[duel] {row['candidate_goals']}:{row['baseline_goals']} territory {row['territory_m']}; "
                            f"pairs {s['pairs_complete']} CS[{cs['lower']:.2f}, {cs['upper']:.2f}] -> {s['decision']}\n")
                invalid = sum(1 for m in record["matches"] if not counts(m))
                if invalid > max(2, len(record["matches"]) // 4):
                    raise DuelError("无效比赛过多，停止对决以便检查")
        record.update(status="COMPLETED", ended_at=util.now_iso())
    except (Exception, KeyboardInterrupt) as exc:
        record.update(status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                      ended_at=util.now_iso(), error=str(exc))
        save()
        raise
    save()
    record["path"] = str(directory / "duel.json")
    return record


def _directory(identifier: str) -> Path:
    directory = RUNS / identifier
    if "/" in identifier or identifier.startswith(".") or directory.resolve().parent != RUNS.resolve():
        raise DuelError("对决标识无效")
    return directory


def list_duels() -> list[dict]:
    rows = []
    for path in sorted(RUNS.glob("*/duel.json"), reverse=True):
        data = util.read_json(path) or {}
        summary = data.get("summary") or {}
        rows.append({"id": path.parent.name, "status": data.get("status"), "decision": data.get("decision"),
                     "kind": data.get("plan", {}).get("kind"), "candidate": data.get("plan", {}).get("candidate"),
                     "baseline": data.get("plan", {}).get("baseline"), "pairs": summary.get("pairs_complete"),
                     "max_pairs": data.get("plan", {}).get("max_pairs"), "record": summary.get("record"),
                     "goal_cs": [summary.get("goal_difference_cs", {}).get(k) for k in ("lower", "upper")],
                     "started_at": data.get("started_at")})
    return rows


def load(identifier: str) -> dict:
    record = util.read_json(_directory(identifier) / "duel.json")
    if not record:
        raise DuelError("对决记录不存在")
    return record
