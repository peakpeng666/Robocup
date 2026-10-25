"""Fragility-atlas statistics: monotone fits, capacities, censoring and paired non-inferiority."""
import json
import math

import numpy as np
import pytest

from forge import atlas, util


def test_isotonic_pools_violators_with_weights():
    assert atlas.isotonic([0, 0.2, 0.1, 0.5], [1, 1, 1, 1]) == pytest.approx([0, 0.15, 0.15, 0.5])
    # A heavy level dominates the pooled value.
    assert atlas.isotonic([0.4, 0.0], [3, 1]) == pytest.approx([0.3, 0.3])
    assert atlas.isotonic([0.1, 0.2, 0.3], [1, 0, 1]) == pytest.approx([0.1, 0.2, 0.3])


def test_crossing_interpolates_and_reports_censoring():
    margins = [0, 10, 20, 30]
    assert atlas.crossing(margins, [0, 0.2, 0.8, 1.0], 0.5) == (15.0, False, False)
    assert atlas.crossing(margins, [0, 0.0, 0.1, 0.2], 0.5) == (30.0, True, False)
    assert atlas.crossing(margins, [0.6, 0.7, 0.8, 1.0], 0.5) == (0.0, False, True)


def test_margin_transforms_are_larger_is_better():
    assert atlas.to_margin("inverse", [1.0, 0.1]).tolist() == [1.0, 10.0]
    assert atlas.to_margin("one_minus", [1.0, 0.25]).tolist() == [0.0, 0.75]
    assert atlas.from_margin("inverse", 20.0) == pytest.approx(0.05)
    assert atlas.from_margin("one_minus", 0.75) == pytest.approx(0.25)
    with pytest.raises(atlas.AtlasError):
        atlas.to_margin("log", [1.0])


def _synthetic_run(tmp_path, thresholds, *, replicas=40, levels=(0, 2, 4, 6, 8, 10, 12, 14), noise=0.0, seed=1,
                   functional=False):
    """One axis; each policy fails deterministically above its threshold (plus optional flips)."""
    rng = np.random.default_rng(seed)
    rows = {k: [] for k in ("axis", "level_index", "level", "replica", "direction_rad", "command_index", "sign")}
    for li, level in enumerate(levels):
        for r in range(replicas):
            rows["axis"].append("push")
            rows["level_index"].append(li)
            rows["level"].append(float(level))
            rows["replica"].append(r)
            rows["direction_rad"].append(0.0)
            rows["command_index"].append(1)
            rows["sign"].append(1.0)
    n = len(rows["axis"])
    spec = {"label": "推", "unit": "N·s", "levels": list(levels), "replicas": replicas,
            "failure": "functional" if functional else "fall", "margin": "value"}
    design = {"schema": "forge.atlas-design/1", "seed": 7, "axes": ["push"], "axis_specs": {"push": spec},
              "timeline": {"seconds": 8.0, "command_at_s": 1.0, "push_at_s": 3.0, "push_duration_s": 0.1},
              "commands": [["stand", [0, 0, 0]], ["forward", [0.5, 0, 0]]], "worlds": n, "rows": rows}
    (tmp_path / "design.json").write_text(json.dumps(design))
    policies = {}
    level = np.asarray(rows["level"])
    jitter = rng.normal(0, 1.5, n)  # same world draws for every policy: common random numbers
    for label, threshold in thresholds.items():
        fell = (level + jitter > threshold).astype(int)
        flips = rng.random(n) < noise
        fell = np.where(flips, 1 - fell, fell)
        policies[label] = {"fell": fell.tolist(), "nonfinite": 0, "policy": f"/{label}.onnx", "policy_sha256": "0" * 64,
                           "linear_progress_m": [3.5] * n, "expected_linear_m": [3.5] * n,
                           "yaw_progress_rad": [0.0] * n, "expected_yaw_rad": [0.0] * n,
                           "track_sq": [[0.0, 0.0, 0.0]] * n, "track_n": [1] * n,
                           "push_phase": [0.5] * n, "stall_fraction": 0.5}
    raw = {"schema": "forge.atlas-raw/1", "status": "COMPLETED", "parity_mode": False, "evaluator_sha256": "e" * 64,
           "design_sha256": util.sha256_file(tmp_path / "design.json"), "policies": policies,
           "engine": {}, "model": {}, "scope": "test"}
    (tmp_path / "raw.json").write_text(json.dumps(raw))
    return tmp_path


def test_equal_policies_are_noninferior(tmp_path):
    run = _synthetic_run(tmp_path, {"base": 7.0, "same": 7.0})
    result = atlas.analyze(run, resamples=200)
    row = result["comparisons"][0]["axes"]["push"]
    assert row["ratio"] == pytest.approx(1.0)
    assert row["status"] == "PASS" and result["comparisons"][0]["verdict"] == "PASS"
    assert not row["better"]
    capacity = result["policies"]["base"]["axes"]["push"]["C50"]
    assert 6.0 < capacity["value"] < 8.0 and not capacity["censored"]
    assert (run / "analysis.json").is_file()


def test_clearly_weaker_candidate_fails_and_stronger_is_better(tmp_path):
    result = atlas.analyze(_synthetic_run(tmp_path, {"base": 8.0, "weak": 4.0, "strong": 11.0}), resamples=200)
    weak, strong = result["comparisons"]
    assert weak["candidate"] == "weak" and weak["axes"]["push"]["status"] == "FAIL" and weak["verdict"] == "FAIL"
    assert weak["worse_axes"] == ["push"] and weak["failed_axes"] == ["push"]
    assert strong["axes"]["push"]["status"] == "PASS" and strong["axes"]["push"]["better"]
    assert strong["better_axes"] == ["push"]


def test_censored_baseline_cannot_support_a_decision(tmp_path):
    result = atlas.analyze(_synthetic_run(tmp_path, {"base": 99.0, "cand": 99.0}), resamples=100)
    row = result["comparisons"][0]["axes"]["push"]
    assert result["policies"]["base"]["axes"]["push"]["C50"]["censored"]
    assert row["status"] == "INSUFFICIENT" and "基线" in row["reason"]


def test_functional_failure_counts_stalls_only_on_functional_axes(tmp_path):
    run = _synthetic_run(tmp_path, {"base": 99.0}, functional=True)
    raw = json.loads((run / "raw.json").read_text())
    outcome = raw["policies"]["base"]
    outcome["linear_progress_m"] = [1.0 if level >= 6 else 3.5 for level in json.loads((run / "design.json").read_text())["rows"]["level"]]
    flags = atlas.failures(outcome, json.loads((run / "design.json").read_text()))
    assert flags["failed"].sum() == flags["stalled"].sum() > 0 and flags["fell"].sum() == 0
    design = json.loads((run / "design.json").read_text())
    design["axis_specs"]["push"]["failure"] = "fall"
    assert atlas.failures(outcome, design)["failed"].sum() == 0


def test_tampered_design_and_parity_runs_are_rejected(tmp_path):
    run = _synthetic_run(tmp_path, {"base": 7.0, "cand": 7.0})
    design = json.loads((run / "design.json").read_text())
    design["seed"] = 8
    (run / "design.json").write_text(json.dumps(design))
    with pytest.raises(atlas.AtlasError, match="哈希"):
        atlas.analyze(run, resamples=10)
    (tmp_path / "p").mkdir()
    run2 = _synthetic_run(tmp_path / "p", {"base": 7.0})
    raw = json.loads((run2 / "raw.json").read_text())
    raw["parity_mode"] = True
    (run2 / "raw.json").write_text(json.dumps(raw))
    with pytest.raises(atlas.AtlasError, match="一致性"):
        atlas.analyze(run2, resamples=10)


def test_wilson_interval_bounds():
    lo, hi = atlas.wilson(0, 64)
    assert lo == 0.0 and 0.05 < hi < 0.06
    lo, hi = atlas.wilson(32, 64)
    assert lo < 0.5 < hi and math.isclose(lo + hi, 1.0, abs_tol=1e-9)


@pytest.fixture
def state(tmp_path, monkeypatch):
    from forge import paths

    for key, relative in {"PACKS": "packs", "ARENAS": "arena", "RUNS": "runs", "STATE": "run",
                          "DB_PATH": "forge.db", "VARIANTS": "variants", "BH_SIM_LOCK": ".bhuman-sim.lock"}.items():
        monkeypatch.setattr(paths, key, tmp_path / relative)
    monkeypatch.setattr(atlas, "RUNS", tmp_path / "runs/atlas")
    return tmp_path


def test_atlas_job_is_whitelisted_gpu_only_and_validated(state):
    from forge import jobs

    manager = jobs.JobManager(db_path=state / "forge.db", autostart=False)
    try:
        spec = manager.preview("atlas", {"packs": ["cand-a", "bhuman-official"], "replica_scale": 2})
        assert spec["resources"] == ["gpu"]
        argv = spec["argv"][spec["argv"].index("atlas"):]
        assert argv[:5] == ["atlas", "run", "bhuman-official", "cand-a", "--baseline"]
        for bad in ({"packs": []}, {"packs": ["a"] * 7}, {"packs": ["../etc"]}, {"packs": ["a"], "axes": ["rm"]},
                    {"packs": ["a"], "replica_scale": 100}, {"packs": ["a"], "replica_scale": True}):
            with pytest.raises(jobs.JobError):
                manager.preview("atlas", bad)
    finally:
        manager.shutdown()


def test_atlas_api_lists_and_rejects_traversal(state):
    from fastapi.testclient import TestClient

    from forge import server

    run = state / "runs/atlas/20260101_000000_000000_fixture"
    run.mkdir(parents=True)
    _synthetic_run(run, {"base": 7.0, "cand": 5.0})
    atlas.analyze(run, resamples=50)
    app = server.create_app(start_jobs=False)
    client = TestClient(app, base_url="http://127.0.0.1:8920")
    headers = {"X-Forge-Token": app.state.token}
    listing = client.get("/api/atlas", headers=headers).json()
    assert listing[0]["id"] == run.name and listing[0]["verdicts"] == {"cand|base": "FAIL"}
    detail = client.get(f"/api/atlas/{run.name}", headers=headers).json()
    assert detail["comparisons"][0]["axes"]["push"]["status"] == "FAIL"
    assert client.get("/api/atlas/..%2F..%2Fetc", headers=headers).status_code == 404
    assert client.get("/api/atlas/missing", headers=headers).status_code == 404


def test_policy_spec_resolves_walk_contract(state):
    from forge import packs, paths

    packs.ensure_baseline()
    official = packs.load(packs.BASELINE_ID)
    walk = paths.BH_LOCAL / official["components"]["walk"]["official_file"]
    copy = packs.create("walkcopy", {"walk": str(walk)})
    spec, path = atlas.policy_spec(copy["id"])
    assert spec == str(path) and path == packs.pack_dir(copy["id"]) / "files/walk.onnx"
    assert atlas.policy_spec(packs.BASELINE_ID)[1] == walk


def test_policy_spec_resolves_real_firmware_pack():
    """The firmware locomotion contract resolves to a booster_fw16:<dir> engine spec."""
    from forge import packs

    pack_id = "booster-fw16-switch-recovery-57f7a4d73b"
    if not (packs.pack_dir(pack_id) / "pack.json").is_file():
        import pytest as _pytest
        _pytest.skip("firmware pack not present")
    spec, path = atlas.policy_spec(pack_id)
    assert spec == f"booster_fw16:{path.parent}" and path.name == "booster_fw16_walk.onnx"
    for slot in atlas.FW16_SLOTS:
        assert (path.parent / f"{slot}.onnx").is_file()
