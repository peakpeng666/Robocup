"""Series of team matches between two motion packs with alternating team assignment.

Each round re-flashes both teams (pack A on team 5 and B on team 70, then swapped), so a
side or jersey advantage of the public 3v3 scene does not favour one pack. Results are
aggregated per pack; a series is evidence about this simulation setting only.
"""
from __future__ import annotations

from collections import defaultdict

from . import arena as arena_mod, match, packs, paths, util
from .locking import exclusive_simulation

METRICS = ("goals", "goals_against", "ball_contacts", "fall_episodes_sampled", "fall_frames", "getup_frames",
           "walk_frames", "path_m", "ball_seen_samples")


@exclusive_simulation(match.MatchError)
def run_series(arena: arena_mod.Arena, pack_a: str, pack_b: str, rounds: int = 2, seconds: int = 120,
               vision: str = "cuda", record_first: bool = True, on_line=None) -> dict:
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 10:
        raise ValueError("系列赛轮数需在 1..10")
    if pack_a == pack_b:
        raise ValueError("系列赛需使用两个不同的运控包；同模型对照请创建独立副本")
    packs.load(pack_a), packs.load(pack_b)
    series_dir = paths.RUNS / "series" / f"{util.stamp()}_{util.safe_name(pack_a, 20)}_vs_{util.safe_name(pack_b, 20)}"
    series_dir.mkdir(parents=True)
    first, second = arena_mod.TEAM_NUMBERS
    rounds_out = []
    util.write_json(series_dir / "series.json", _aggregate(pack_a, pack_b, rounds_out, seconds, rounds))
    for index in range(rounds):
        assignment = {first: pack_a, second: pack_b} if index % 2 == 0 else {first: pack_b, second: pack_a}
        for team, pack_id in assignment.items():
            arena.flash(team, pack_id)
        if on_line:
            on_line(f"[series] round {index + 1}/{rounds}: T{first}={assignment[first]} T{second}={assignment[second]}\n")
        result = match.run_match(arena, seconds=seconds, record=record_first and index == 0, vision=vision,
                                 tag=f"series-r{index + 1}", on_line=on_line)
        rounds_out.append({"round": index + 1, "assignment": {str(t): p for t, p in assignment.items()},
                           "status": result["status"], "score": result["score"], "teams": result["teams"],
                           "run": result.get("run"), "video": result.get("video"), "failed_checks": [k for k, v in result["checks"].items() if not v]})
        util.write_json(series_dir / "series.json", _aggregate(pack_a, pack_b, rounds_out, seconds, rounds))
    summary = _aggregate(pack_a, pack_b, rounds_out, seconds, rounds, completed=True)
    util.write_json(series_dir / "series.json", summary)
    summary["dir"] = str(series_dir)
    return summary


def _aggregate(pack_a, pack_b, rounds, seconds, requested_rounds, completed=False) -> dict:
    per_pack = {pack_a: defaultdict(float), pack_b: defaultdict(float)}
    record = {pack_a: {"win": 0, "draw": 0, "loss": 0}, pack_b: {"win": 0, "draw": 0, "loss": 0}}
    valid = [r for r in rounds if r["status"] == "PASS"]
    for r in valid:
        team_of = {pack: int(team) for team, pack in r["assignment"].items()}
        for pack in (pack_a, pack_b):
            stats = r["teams"][str(team_of[pack])]
            for metric in METRICS:
                per_pack[pack][metric] += float(stats.get(metric, 0))
        goals_a = r["teams"][str(team_of[pack_a])]["goals"]
        goals_b = r["teams"][str(team_of[pack_b])]["goals"]
        if goals_a > goals_b:
            record[pack_a]["win"] += 1
            record[pack_b]["loss"] += 1
        elif goals_a < goals_b:
            record[pack_b]["win"] += 1
            record[pack_a]["loss"] += 1
        else:
            record[pack_a]["draw"] += 1
            record[pack_b]["draw"] += 1
    return {"schema": "forge.series/2", "pack_a": pack_a, "pack_b": pack_b, "seconds_per_match": seconds,
            "requested_rounds": requested_rounds, "completed": completed and len(rounds) == requested_rounds,
            "rounds_played": len(rounds), "rounds_valid": len(valid), "rounds": rounds,
            "totals": {p: dict(v) for p, v in per_pack.items()}, "record": record,
            "status": "PASS" if completed and len(valid) == len(rounds) == requested_rounds else "INCOMPLETE",
            "scope": "Simulation evidence in the public 3v3 HSL-M SimRobot scene with alternating assignment; "
                     "not a statistical guarantee or a hardware result"}
