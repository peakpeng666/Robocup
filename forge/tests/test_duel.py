"""Sequential duel statistics: anytime-valid confidence sequences, decisions and ledgers."""
import numpy as np
import pytest

from forge import duel


def test_confidence_sequence_is_nested_and_contains_truth_for_constant_data():
    cs = duel.confidence_sequence([0.5] * 40)
    lows, highs = zip(*cs["bounds"])
    assert all(a <= b for a, b in zip(lows, lows[1:])) and all(a >= b for a, b in zip(highs, highs[1:]))
    assert cs["lower"] < 0.5 < cs["upper"] and cs["upper"] - cs["lower"] < 0.5
    with pytest.raises(duel.DuelError):
        duel.confidence_sequence([1.2])


def test_time_uniform_coverage_under_the_null():
    """P(the sequence ever excludes the true mean) must stay below alpha (Ville's inequality)."""
    rng = np.random.default_rng(11)
    misses = 0
    runs = 300
    for _ in range(runs):
        # Symmetric, heavy-ish goal differences per pair: true mean 0 -> scaled 0.5.
        d = rng.choice([-3, -2, -1, 0, 1, 2, 3], size=60, p=[.04, .1, .2, .32, .2, .1, .04])
        cs = duel.confidence_sequence([duel._scaled_goal(x) for x in d])
        if any(not lo <= 0.5 <= hi for lo, hi in cs["bounds"]):
            misses += 1
    assert misses / runs <= 0.05


def test_decisions_follow_the_sequence():
    plan = {"alpha": 0.05, "delta_goals": 0.5, "max_pairs": 40}
    strong = {"plan": plan, "matches": []}
    for pair in range(12):
        for team in (5, 70):
            strong["matches"].append({"execution_status": "PASS", "pair": pair, "candidate_team": team, "kickoff_team": 5,
                                      "candidate_goals": 2, "baseline_goals": 0, "territory_m": 1.5, "run": "r"})
    summary = duel.summarize(strong)
    assert summary["decision"] == "STRONGER" and summary["goal_difference_cs"]["lower"] > 0
    assert summary["record"] == {"win": 24, "draw": 0, "loss": 0}
    assert summary["territory_cs"]["mean"] == pytest.approx(1.5) and summary["territory_cs"]["lower"] > -0.5
    weak = {"plan": plan, "matches": [dict(m, candidate_goals=0, baseline_goals=2, territory_m=-1.5) for m in strong["matches"]]}
    assert duel.summarize(weak)["decision"] == "WEAKER"
    assert duel.decide({"lower": duel._scaled_goal(-0.2), "upper": duel._scaled_goal(0.3)}, 0.5, 30, 40) == "EQUIVALENT"
    assert duel.decide({"lower": duel._scaled_goal(-1), "upper": duel._scaled_goal(1)}, 0.5, 30, 40) == "CONTINUE"
    assert duel.decide({"lower": duel._scaled_goal(-1), "upper": duel._scaled_goal(1)}, 0.5, 40, 40) == "INCONCLUSIVE"


def test_execution_failures_are_replayed_but_quality_findings_count():
    ok = {"execution_status": "PASS", "status": "PASS"}
    record = {"plan": {"alpha": 0.05, "delta_goals": 0.5, "max_pairs": 5}, "matches": [
        {**ok, "pair": 0, "candidate_team": 5, "kickoff_team": 5, "candidate_goals": 1, "baseline_goals": 0, "territory_m": 0.2, "run": "a"},
        {"execution_status": "FAIL", "pair": 0, "candidate_team": 70, "kickoff_team": 5, "candidate_goals": 3, "baseline_goals": 0, "territory_m": 2.0, "run": "b"},
        # A failed get-up makes the overall status FAIL, but the football result stands.
        {"execution_status": "PASS", "status": "FAIL", "pair": 0, "candidate_team": 70, "kickoff_team": 5, "candidate_goals": 0,
         "baseline_goals": 0, "territory_m": -0.4, "run": "c"},
        # A later duplicate of an already counted side is ignored (first valid result counts).
        {**ok, "pair": 0, "candidate_team": 70, "kickoff_team": 5, "candidate_goals": 4, "baseline_goals": 0, "territory_m": 3.0, "run": "e"},
        {**ok, "pair": 1, "candidate_team": 5, "kickoff_team": 70, "candidate_goals": 0, "baseline_goals": 1, "territory_m": -0.1, "run": "d"},
        {**ok, "pair": 1, "candidate_team": 70, "kickoff_team": 70, "candidate_goals": 0, "baseline_goals": 0, "territory_m": None, "run": "f"},
    ]}
    summary = duel.summarize(record)
    assert summary["pairs_complete"] == 1 and summary["matches_invalid"] == 2 and summary["matches_superseded"] == 1
    assert summary["pairs"][0]["goal_difference"] == 1 and summary["pairs"][0]["territory_m"] == pytest.approx(-0.1)
    assert summary["pairs"][0]["matches"] == ["a", "c"]
    assert summary["decision"] == "CONTINUE"


def test_goal_difference_is_clipped_to_a_bounded_observation():
    assert duel._scaled_goal(100) == 1.0 and duel._scaled_goal(-100) == 0.0 and duel._scaled_goal(0) == 0.5
    assert duel._unscale_goal(duel._scaled_goal(2)) == pytest.approx(2)


def test_territory_uses_playing_samples_along_attack_direction(tmp_path):
    console = tmp_path / "console.log"
    console.write_text("\n".join([
        "AUDIT game tick=1 state=1 ball_valid=1 ball_x_mm=0.0 ball_y_mm=0",
        "AUDIT game tick=2 state=3 ball_valid=1 ball_x_mm=-2000.0 ball_y_mm=0",
        "AUDIT game tick=3 state=3 ball_valid=1 ball_x_mm=-1000.0 ball_y_mm=0",
        "AUDIT game tick=4 state=3 ball_valid=0 ball_x_mm=9000.0 ball_y_mm=0",
    ]) + "\n")
    # Team 5 attacks towards -x: the ball deep at -x is good for team 5.
    assert duel.territory(console, 5) == (pytest.approx(1.5), 2)
    assert duel.territory(console, 70)[0] == pytest.approx(-1.5)
    (tmp_path / "empty.log").write_text("AUDIT game tick=1 state=1 ball_x_mm=0\n")
    with pytest.raises(duel.DuelError):
        duel.territory(tmp_path / "empty.log", 5)
