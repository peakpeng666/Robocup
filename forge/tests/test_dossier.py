"""Evidence dossier: read-only linking of evidence to packs by id and by hash."""
import pytest

from forge import dossier, packs, paths, util

OFFICIAL_WALK = paths.BH_LOCAL / "Config/NeuralNets/Walk/K1_walk.onnx"


@pytest.fixture
def state(tmp_path, monkeypatch):
    for key, relative in {"PACKS": "packs", "ARENAS": "arena", "RUNS": "runs", "STATE": "run",
                          "DB_PATH": "forge.db", "VARIANTS": "variants", "BH_SIM_LOCK": ".bhuman-sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    monkeypatch.setattr(paths, "TRAINING", tmp_path / "training")
    dossier._CACHE.update(at=0.0, index=None)
    return tmp_path


def test_dossier_links_by_id_and_hash_and_reports_gaps(state):
    packs.ensure_baseline()
    digest = util.sha256_file(OFFICIAL_WALK)
    train = state / "runs/train/20261022_000000_000000_fixture"
    (train / "nn").mkdir(parents=True)
    (train / "nn/model_final.pth").write_bytes(b"checkpoint")
    util.write_json(train / "launch.json", {"preset": "thu-amp", "envs": 64, "iterations": 3, "seed": 1})
    util.write_json(train / "execution.json", {"status": "PASS"})
    checkpoint_sha = util.sha256_file(train / "nn/model_final.pth")
    copy = packs.create("copy", {"walk": str(OFFICIAL_WALK)}, provenance={
        "checkpoint": str(train / "nn/model_final.pth"), "checkpoint_sha256": checkpoint_sha, "tri_check": {"verdict": "PASS"},
        "export_dir": str(state / "runs/exports/20261022_000001_000000_copy")})
    # Evidence written by different runners.
    util.write_json(state / "runs/mjwarp/20261022_010000_000000_x/result.json",
                    {"status": "COMPLETED", "policy_sha256": digest, "setup": {"worlds": 8, "push_force_max_N": 60},
                     "metrics": {"fall_rate": 0.0, "tracking_rmse": {"vx": 0.1, "vy": 0.1, "wz": 0.2}}})
    util.write_json(state / "training/runs/20261022_020000_000000_walk_eval_s2027/results.json",
                    {"policy_sha256": checkpoint_sha, "finite_checks_pass": True, "seed": 2027,
                     "segments": {"fwd": {"command_vx_vy_wz": [1, 0, 0], "tracking_rmse_settled_vx_vy_wz": [0.1, 0.2, 0.3]}},
                     "termination_events_total": {"non_timeout_reset": 0}})
    util.write_json(state / "runs/atlas/20261022_030000_000000_a/analysis.json",
                    {"worlds": 10, "policies": {packs.BASELINE_ID: {"axes": {}}, copy["id"]: {"axes": {}}},
                     "comparisons": [{"candidate": copy["id"], "baseline": packs.BASELINE_ID, "verdict": "PASS",
                                      "better_axes": [], "worse_axes": [], "failed_axes": []}]})
    util.write_json(state / "runs/matches/20261022_040000_000000_m/launch.json",
                    {"teams": {"5": {"pack_id": copy["id"]}, "70": {"pack_id": packs.BASELINE_ID}}, "case": "match"})
    util.write_json(state / "runs/matches/20261022_040000_000000_m/result.json", {"status": "PASS", "score": {"5": 1, "70": 0}})
    util.write_json(state / "runs/gates/20261022_050000_000000_g.json",
                    {"pack_id": copy["id"], "verdict": "INSUFFICIENT_EVIDENCE", "rule_version": "forge.sim-gates/3", "gates": {}})
    result = dossier.dossier(copy["id"])
    assert result["hash_aliases"] == [packs.BASELINE_ID]
    assert set(result["counts"]) == {"mujoco_stress", "isaac_eval", "atlas", "simrobot_match", "gate"}
    assert [s["stage"] for s in result["lineage"]] == ["训练", "检查点", "导出", "运控包"]
    assert result["lineage"][0]["detail"]["preset"] == "thu-amp"
    assert result["scorecard"]["atlas"]["verdict"] == "PASS" and result["scorecard"]["gate"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "序贯对决" in "".join(result["missing"]) and "易损性图谱" not in result["missing"]
    # The official pack shares the hash-linked stress result but not the checkpoint-linked evaluation.
    official = dossier.dossier(packs.BASELINE_ID)
    assert "mujoco_stress" in official["counts"] and "isaac_eval" not in official["counts"] and official["missing"] == []
    overview = {row["id"]: row for row in dossier.overview()}
    assert overview[copy["id"]]["atlas"] == "PASS" and overview[copy["id"]]["gate"] == "INSUFFICIENT_EVIDENCE"
    assert overview[copy["id"]]["total"] == 5


def test_dossier_unknown_pack_is_an_error(state):
    packs.ensure_baseline()
    with pytest.raises(packs.PackError):
        dossier.dossier("does-not-exist")
