"""Recovery decisions from synthetic telemetry only; never starts SimRobot."""
import copy

import pytest

from forge import recovery


ROSTER = {"robot5": (5, 5)}


def telemetry(signal, duration=60):
    records = {"motion": [], "physics": [], "completed": [{"steps": str(duration * 500)}],
               "command": [{"tick": str(tick), "text": text} for tick, text in recovery.plan()]}
    fall = getup = 0
    for tick in range(250, duration * 500 + 1, 250):
        phase, pitch = signal(tick * 0.002)
        fall += 250 if phase == 3 else 0
        getup += 250 if phase == 4 else 0
        records["motion"].append({"team": "5", "player": "5", "frames": str(tick), "phase": str(phase),
                                  "fall_frames": str(fall), "getup_frames": str(getup), "nonfinite_total": "0"})
        records["physics"].append({"robot": "robot5", "tick": str(tick), "roll_rad": "0",
                                   "pitch_rad": str(pitch), "nonfinite_total": "0"})
    return records


def recovered(t):
    for start, sign in ((2, 1), (32, -1)):
        if start <= t < start + 0.5:
            return 3, 1.5 * sign
        if start + 0.5 <= t < start + 4:
            return 4, 1.2 * sign
    return 1, 0.1


def test_plan_uses_500hz_ticks_and_never_resets_upright():
    plan = recovery.plan()
    assert recovery.RECOVERY_ID == "recovery-front-back-v1"
    assert recovery.DURATION_S == 60
    assert plan[0] == (0, "robot robot5")
    assert plan[1][0] == 0 and "motion = stand;" in plan[1][1]
    assert plan[2:] == [(1000, "mv -2000 0 350 0 90 0"), (16000, "mv -2000 0 350 0 -90 0")]


def test_two_forced_falls_require_measured_recovery_and_followup():
    records = telemetry(recovered)
    original = copy.deepcopy(records)
    report = recovery.assess(records, ROSTER, forced=True)
    assert report["conclusion"] == "PASS", report
    assert all(report["checks"].values())
    windows = report["robots"]["robot5"]["forced_windows"]
    assert [w["direction"] for w in windows] == ["front", "back"]
    assert [w["recovered_s"] for w in windows] == [9, 39]
    assert [w["recovery_latency_s"] for w in windows] == [7, 7]
    assert [w["stable_since_s"] for w in windows] == [6, 36]
    assert records == original


def test_observed_eighty_second_getup_is_a_recovery_failure():
    def stuck(t):
        if 34 <= t < 40:
            return 3, 1.2
        if t >= 40:
            return 4, 1.2
        return 2, 0.1

    report = recovery.assess(telemetry(stuck, duration=120), ROSTER)
    robot = report["robots"]["robot5"]
    assert report["conclusion"] == "FAIL"
    assert robot["longest_continuous_getup_s"] == 80
    assert robot["episodes"][0]["unresolved_at_end"]
    assert not report["checks"]["no_stuck_getup_over_20s"]
    assert not report["checks"]["no_unresolved_episodes"]


def test_complete_match_with_no_falls_does_not_qualify_recovery():
    records = telemetry(lambda t: (2, 0.1))
    assert recovery.assess(records, ROSTER)["conclusion"] == "NOT_EXERCISED"
    assert recovery.assess(records, ROSTER, forced=True)["conclusion"] == "FAIL"


def test_generic_observed_recoveries_pass_without_forced_commands():
    records = telemetry(recovered)
    records.pop("command")
    report = recovery.assess(records, ROSTER)
    assert report["conclusion"] == "PASS"
    assert len(report["robots"]["robot5"]["episodes"]) == 2


@pytest.mark.parametrize("forced", [False, True])
def test_recovered_then_refallen_is_not_success(forced):
    def refall(t):
        if 12 <= t < 12.5:
            return 3, 1.1
        if 12.5 <= t < 15:
            return 4, 1.1
        return recovered(t)

    report = recovery.assess(telemetry(refall), ROSTER, forced=forced)
    assert report["conclusion"] == "FAIL"
    assert report["robots"]["robot5"]["episodes"][0]["refall_within_window"]
    if forced:
        assert not report["robots"]["robot5"]["forced_windows"][0]["checks"]["no_later_refall"]


def test_single_near_upright_frame_does_not_prove_recovery():
    def brief(t):
        if t == 6:
            return 1, 0.0
        return (4, 1.1) if t > 2 else recovered(t)

    report = recovery.assess(telemetry(brief), ROSTER, forced=True)
    assert report["conclusion"] == "FAIL"
    assert not report["robots"]["robot5"]["forced_windows"][0]["checks"]["upright_sustained_3s"]


def test_recovery_after_deadline_does_not_pass_even_if_eventually_stable():
    def late(t):
        if 2.5 <= t < 21:
            return 4, 1.1
        return recovered(t)

    report = recovery.assess(telemetry(late), ROSTER, forced=True)
    first = report["robots"]["robot5"]["forced_windows"][0]
    assert first["recovered_s"] == 24
    assert not first["checks"]["recovered_within_20s"]
    assert report["conclusion"] == "FAIL"


@pytest.mark.parametrize("mutation", ["no-physics", "one-missing-sample", "tail-missing", "missing-completed",
                                      "missing-command", "bad-command-tick", "wrong-duration"])
def test_missing_or_gapped_evidence_cannot_pass(mutation):
    records = telemetry(recovered)
    if mutation == "no-physics":
        records["physics"] = []
    elif mutation == "one-missing-sample":
        records["motion"].pop(30)
        records["physics"].pop(30)
    elif mutation == "tail-missing":
        records["motion"] = records["motion"][:-5]
        records["physics"] = records["physics"][:-5]
    elif mutation == "missing-completed":
        records.pop("completed")
    elif mutation == "missing-command":
        records["command"].pop()
    elif mutation == "bad-command-tick":
        records["command"][-1]["tick"] = "16001"
    else:
        records["completed"][0]["steps"] = "29000"
    report = recovery.assess(records, ROSTER, forced=True)
    assert report["conclusion"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("mutation", ["nan-pitch", "infinite-roll", "missing-phase", "bad-phase",
                                      "negative-counter", "counter-decrease", "duplicate-tick",
                                      "nonfinite-history", "misaligned-ticks"])
def test_malformed_or_unsynchronized_evidence_cannot_pass(mutation):
    records = telemetry(recovered)
    if mutation == "nan-pitch":
        records["physics"][20]["pitch_rad"] = "nan"
    elif mutation == "infinite-roll":
        records["physics"][20]["roll_rad"] = "inf"
    elif mutation == "missing-phase":
        records["motion"][20].pop("phase")
    elif mutation == "bad-phase":
        records["motion"][20]["phase"] = "7"
    elif mutation == "negative-counter":
        records["motion"][20]["getup_frames"] = "-1"
    elif mutation == "counter-decrease":
        records["motion"][20]["getup_frames"] = "0"
    elif mutation == "duplicate-tick":
        records["motion"].insert(20, dict(records["motion"][19]))
    elif mutation == "nonfinite-history":
        records["motion"][20]["nonfinite_total"] = "1"
    else:
        records["physics"][20]["tick"] = str(int(records["physics"][20]["tick"]) + 1)
    assert recovery.assess(records, ROSTER, forced=True)["conclusion"] == "INSUFFICIENT_EVIDENCE"


def test_back_perturbation_requires_negative_pitch_evidence():
    records = telemetry(recovered)
    for row in records["physics"]:
        row["pitch_rad"] = str(abs(float(row["pitch_rad"])))
    report = recovery.assess(records, ROSTER, forced=True)
    assert report["conclusion"] == "FAIL"
    assert not report["robots"]["robot5"]["forced_windows"][1]["checks"]["perturbation_observed"]


def test_pose_alone_without_recovery_motion_is_not_forced_recovery():
    records = telemetry(recovered)
    for row in records["motion"]:
        row.update(phase="1", fall_frames="0", getup_frames="0")
    report = recovery.assess(records, ROSTER, forced=True)
    assert report["conclusion"] == "FAIL"
    assert not report["robots"]["robot5"]["forced_windows"][0]["checks"]["getup_observed"]


def test_healthy_other_robot_cannot_hide_one_unresolved_robot():
    records = telemetry(recovered)
    bad = telemetry(lambda t: (4, 1.2) if t >= 34 else (2, 0.0))
    for row in bad["motion"]:
        row.update(team="70", player="3")
    for row in bad["physics"]:
        row["robot"] = "robot23"
    records["motion"].extend(bad["motion"])
    records["physics"].extend(bad["physics"])
    report = recovery.assess(records, {**ROSTER, "robot23": (70, 3)})
    assert report["robots"]["robot5"]["conclusion"] == "PASS"
    assert report["robots"]["robot23"]["conclusion"] == "FAIL"
    assert report["conclusion"] == "FAIL"
