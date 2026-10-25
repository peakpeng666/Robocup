"""Evidence-only fall recovery assessment, separate from successful execution.

The audit clock is 500 Hz; retained motion/physics samples normally arrive every
250 ticks. A recovery requires three seconds of aligned upright samples, not a
single near-upright pose. This module neither starts SimRobot nor changes logs.
"""
from __future__ import annotations

import math

from . import scenarios

RECOVERY_ID = "recovery-front-back-v1"
DURATION_S = 60
TICK_S = 0.002
STABLE_S = 3.0
MAX_RECOVERY_S = 20.0
MAX_SAMPLE_GAP_S = 0.75
UPRIGHT_TILT_RAD = 0.5
FALL_TILT_RAD = 0.85
PERTURBATIONS = (("front", 1000, 1), ("back", 16000, -1))


def plan() -> list[tuple[int, str]]:
    """One robot, two deliberate falls, no assisted upright reset."""
    return [(0, "robot robot5"), (0, scenarios.motion_command("stand")),
            (1000, "mv -2000 0 350 0 90 0"), (16000, "mv -2000 0 350 0 -90 0")]


def _integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("expected integer counter")
    number = int(value)
    if number < 0:
        raise ValueError("negative counter")
    return number


def _number(value) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a measurement")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite measurement")
    return number


def _read_stream(rows: list[dict], kind: str, errors: list[str]) -> list[dict]:
    parsed = []
    previous_tick = -1
    previous_counters = (0, 0)
    for row in rows:
        try:
            tick = _integer(row["frames" if kind == "motion" else "tick"])
            if tick <= previous_tick:
                raise ValueError("duplicate or nonmonotonic clock")
            sample = {"tick": tick}
            if "nonfinite_total" in row and _integer(row["nonfinite_total"]) != 0:
                raise ValueError("recorded nonfinite values")
            if kind == "motion":
                phase = _integer(row["phase"])
                if phase > 5:
                    raise ValueError("unknown motion phase")
                counters = (_integer(row["fall_frames"]), _integer(row["getup_frames"]))
                if any(now < before for now, before in zip(counters, previous_counters)):
                    raise ValueError("cumulative counter decreased")
                if any(value > tick for value in counters) or sum(counters) > tick:
                    raise ValueError("cumulative phase counters exceed elapsed frames")
                sample.update(phase=phase, fall_frames=counters[0], getup_frames=counters[1],
                              fall_delta=counters[0] - previous_counters[0],
                              getup_delta=counters[1] - previous_counters[1])
                previous_counters = counters
            else:
                roll, pitch = _number(row["roll_rad"]), _number(row["pitch_rad"])
                sample.update(roll_rad=roll, pitch_rad=pitch, tilt=max(abs(roll), abs(pitch)))
            previous_tick = tick
            parsed.append(sample)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"{kind}: {exc}")
    return parsed


def _covered(samples: list[dict], end_tick: int) -> bool:
    max_gap = MAX_SAMPLE_GAP_S / TICK_S
    return (len(samples) >= 2 and end_tick > 0 and samples[0]["tick"] <= max_gap
            and end_tick - max_gap <= samples[-1]["tick"] <= end_tick
            and all(0 < b["tick"] - a["tick"] <= max_gap for a, b in zip(samples, samples[1:])))


def _disturbed(row: dict) -> bool:
    return (row["phase"] in (3, 4) or row["fall_delta"] > 0
            or row["getup_delta"] > 0 or row["tilt"] >= FALL_TILT_RAD)


def _upright(row: dict) -> bool:
    return row["phase"] in (1, 2) and row["tilt"] < UPRIGHT_TILT_RAD and not _disturbed(row)


def _episodes(samples: list[dict]) -> tuple[list[dict], float]:
    episodes = []
    active = None
    stable_start = getup_start = None
    longest_getup = 0.0
    for row in samples:
        now = row["tick"] * TICK_S
        if row["phase"] == 4:
            getup_start = now if getup_start is None else getup_start
            longest_getup = max(longest_getup, now - getup_start)
        else:
            getup_start = None
        if active is None and _disturbed(row):
            if episodes and now <= episodes[-1]["onset_s"] + MAX_RECOVERY_S:
                episodes[-1]["refall_within_window"] = True
            active = {"onset_s": now, "recovered_s": None, "stable_since_s": None,
                      "recovery_latency_s": None, "unresolved_at_end": True,
                      "refall_within_window": False}
        if active is not None:
            if _upright(row):
                stable_start = now if stable_start is None else stable_start
                if now - stable_start >= STABLE_S:
                    active.update(recovered_s=now, stable_since_s=stable_start,
                                  recovery_latency_s=now - active["onset_s"], unresolved_at_end=False)
                    episodes.append(active)
                    active, stable_start = None, None
            else:
                stable_start = None
    if active is not None:
        episodes.append(active)
    return episodes, longest_getup


def _forced_window(samples: list[dict], label: str, start: int, sign: int, end: int,
                   include_end: bool) -> dict:
    window = [r for r in samples if start <= r["tick"] and
              (r["tick"] <= end if include_end else r["tick"] < end)]
    observed = any(r["tick"] <= start + 1000 and sign * r["pitch_rad"] >= FALL_TILT_RAD
                   for r in window)
    fall_seen = any(r["phase"] == 3 or r["fall_delta"] > 0 for r in window)
    getup_seen = any(r["phase"] == 4 or r["getup_delta"] > 0 for r in window)
    disturbed_seen = False
    stable_start = settled = None
    for row in window:
        disturbed_seen |= _disturbed(row)
        if disturbed_seen and _upright(row):
            stable_start = row["tick"] if stable_start is None else stable_start
            if row["tick"] - stable_start >= STABLE_S / TICK_S:
                settled = row["tick"]
                break
        else:
            stable_start = None
    refall = settled is not None and any(_disturbed(r) for r in window if r["tick"] > settled)
    checks = {"perturbation_observed": observed, "fall_observed": fall_seen, "getup_observed": getup_seen,
              "upright_sustained_3s": settled is not None,
              "recovered_within_20s": settled is not None and (settled - start) * TICK_S <= MAX_RECOVERY_S,
              "no_later_refall": settled is not None and not refall,
              "window_ends_upright": bool(window) and _upright(window[-1])}
    return {"direction": label, "injection_s": start * TICK_S, "window_end_s": end * TICK_S,
            "stable_since_s": stable_start * TICK_S if settled is not None else None,
            "recovered_s": settled * TICK_S if settled is not None else None,
            "recovery_latency_s": (settled - start) * TICK_S if settled is not None else None,
            "checks": checks, "passed": all(checks.values())}


def assess(records: dict, roster: dict, forced: bool = False) -> dict:
    """Assess parsed AUDIT records without changing their execution status.

    Missing, malformed, gapped or unsynchronized evidence cannot pass. Generic
    matches with complete evidence but no falls are NOT_EXERCISED. Forced tests
    additionally require the exact dispatched plan and both signed perturbations.
    """
    errors = []
    try:
        completions = {_integer(r["steps"]) for r in records.get("completed", [])}
        if len(completions) != 1 or not next(iter(completions)):
            raise ValueError("missing or conflicting completed steps")
        completed_tick = completions.pop()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        completed_tick = 0
        errors.append(str(exc))
    end_tick = int(DURATION_S / TICK_S) if forced else completed_tick
    if forced and completed_tick != end_tick:
        errors.append("forced recovery case must complete exactly 60 seconds")
    commands_ok = True
    if forced:
        dispatched = set()
        for row in records.get("command", []):
            try:
                dispatched.add((_integer(row["tick"]), row["text"]))
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append("invalid command evidence")
        commands_ok = all(command in dispatched for command in plan())
        if not commands_ok:
            errors.append("forced perturbation plan was not fully dispatched")
        if set(roster) != {"robot5"}:
            errors.append("forced recovery plan requires the single robot5 scene")
    robots = {}
    for name, (team, player) in roster.items():
        robot_errors = []
        motion = _read_stream([r for r in records.get("motion", [])
                               if (str(r.get("team")), str(r.get("player"))) == (str(team), str(player))],
                              "motion", robot_errors)
        physics = _read_stream([r for r in records.get("physics", []) if r.get("robot") == name],
                               "physics", robot_errors)
        synchronized = [r["tick"] for r in motion] == [r["tick"] for r in physics]
        physics_by_tick = {r["tick"]: r for r in physics}
        samples = [{**r, **physics_by_tick[r["tick"]]} for r in motion if r["tick"] in physics_by_tick]
        evidence_checks = {"valid_records": not robot_errors, "motion_coverage": _covered(motion, end_tick),
                           "physics_coverage": _covered(physics, end_tick), "synchronized_samples": synchronized}
        episodes, longest_getup = _episodes(samples)
        windows = [_forced_window(samples, label, start, sign,
                                  PERTURBATIONS[i + 1][1] if i + 1 < len(PERTURBATIONS) else end_tick,
                                  i + 1 == len(PERTURBATIONS))
                   for i, (label, start, sign) in enumerate(PERTURBATIONS)] if forced else []
        recovery_checks = {
            "no_stuck_getup_over_20s": longest_getup <= MAX_RECOVERY_S,
            "no_unresolved_episodes": all(not e["unresolved_at_end"] for e in episodes),
            "all_recoveries_within_20s": all(e["recovery_latency_s"] is not None and
                                            e["recovery_latency_s"] <= MAX_RECOVERY_S for e in episodes),
            "no_refall_within_recovery_window": all(not e["refall_within_window"] for e in episodes),
        }
        if forced:
            recovery_checks["both_forced_recoveries_pass"] = all(w["passed"] for w in windows)
        evidence_ok = all(evidence_checks.values())
        conclusion = ("INSUFFICIENT_EVIDENCE" if not evidence_ok else
                      "NOT_EXERCISED" if not forced and not episodes else
                      "PASS" if all(recovery_checks.values()) else "FAIL")
        robots[name] = {"team": team, "player": player, "conclusion": conclusion,
                        "motion_samples": len(motion), "physics_samples": len(physics),
                        "getup_seconds": (motion[-1]["getup_frames"] * TICK_S) if motion else None,
                        "longest_continuous_getup_s": longest_getup, "episodes": episodes,
                        "forced_windows": windows, "evidence_checks": evidence_checks,
                        "checks": recovery_checks, "errors": robot_errors}
    checks = {"complete_valid_evidence": bool(robots) and not errors and
              all(all(r["evidence_checks"].values()) for r in robots.values()),
              "all_commands_dispatched": commands_ok,
              "no_stuck_getup_over_20s": all(r["checks"]["no_stuck_getup_over_20s"] for r in robots.values()),
              "no_unresolved_episodes": all(r["checks"]["no_unresolved_episodes"] for r in robots.values()),
              "all_exercised_robots_recovered": all(r["conclusion"] in ("PASS", "NOT_EXERCISED")
                                                    for r in robots.values())}
    exercised = sum(bool(r["episodes"]) for r in robots.values())
    conclusion = ("INSUFFICIENT_EVIDENCE" if not checks["complete_valid_evidence"] else
                  "NOT_EXERCISED" if not forced and not exercised else
                  "PASS" if all(checks.values()) else "FAIL")
    return {"schema": "forge.recovery-assessment/1", "case": RECOVERY_ID if forced else "observed-match",
            "forced": forced, "duration_s": end_tick * TICK_S, "robots": robots, "checks": checks,
            "conclusion": conclusion, "exercised_robots": exercised, "errors": errors,
            "rules": {"tick_s": TICK_S, "stable_s": STABLE_S, "max_recovery_s": MAX_RECOVERY_S,
                      "max_sample_gap_s": MAX_SAMPLE_GAP_S, "upright_tilt_rad": UPRIGHT_TILT_RAD,
                      "fall_tilt_rad": FALL_TILT_RAD},
            "scope": "Sampled local-simulation recovery evidence; independent of process execution PASS. "
                     "Internal GetUp attempts and joint/torque causes require additional diagnostics."}
