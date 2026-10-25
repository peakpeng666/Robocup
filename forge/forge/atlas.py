"""Fragility atlas: GPU disturbance sweeps -> fragility curves -> paired capacity comparison.

The engine (``sim/atlas.py``, MuJoCo Warp venv) records one outcome per world.  This module
(control plane, numpy only) turns those outcomes into evidence and can always be re-run
offline from the stored ``raw.json`` / ``design.json``:

* failure fraction per tested level, for each axis and each direction/azimuth group;
* monotone (isotonic, pool-adjacent-violators) fit of P(failure | severity), weighted by trials;
* capacities C10 / C50: severity at which the fitted curve first reaches 10 % / 50 %, linearly
  interpolated on a larger-is-better *margin* scale; right-censored when never reached;
* stratified bootstrap (worlds resampled within axis x group x level) for 95 % intervals,
  paired by world index across policies because every policy runs on the same world table;
* non-inferiority of a candidate against a baseline on each axis' C50 margin ratio:
  lower 95 % bound >= 1 - margin -> PASS, upper bound < 1 - margin -> FAIL, else INSUFFICIENT.
  A baseline that is censored in the resamples cannot support a decision (INSUFFICIENT).
  The verdict requires every axis to pass (intersection-union, no multiplicity inflation).
* "better"/"worse" flags are exploratory claims over many axes, so they use simultaneous
  (Bonferroni over the compared axes) intervals rather than the per-axis 95 % interval.
  Six independent runs of the same official policy gave 4 of 135 per-axis 95 % ratio
  intervals excluding 1 (3.0 %), i.e. the paired bootstrap is calibrated or conservative.

Failure is a fall (height < 0.30 m or tilt > 1 rad) or, on axes whose declared failure mode is
``functional``, a fall or a stall (less than half of the commanded distance/yaw achieved).
These are MuJoCo statements about the B-Human walk contract, not SimRobot or hardware results.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

from . import packs, paths, util

SCHEMA = "forge.atlas/1"
RAW_SCHEMA = "forge.atlas-raw/1"
REQUIRED_AXES = ("push", "friction", "slope", "payload", "com_shift", "torque", "latency", "imu_bias", "joint_friction")
ENGINE = paths.FORGE / "sim/atlas.py"
RUNS = paths.RUNS / "atlas"
BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20261023
NONINFERIORITY_MARGIN = 0.10
QUANTILES = {"C10": 0.10, "C50": 0.50}


class AtlasError(ValueError):
    pass


# ------------------------------------------------------------------ statistics
def isotonic(rates, weights):
    """Weighted increasing isotonic regression (pool adjacent violators)."""
    blocks = []
    for value, weight in zip(rates, weights):
        blocks.append([float(value), float(weight), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            total = w1 + w2
            blocks.append([(v1 * w1 + v2 * w2) / total if total else (v1 + v2) / 2, total, c1 + c2])
    out = []
    for value, _, count in blocks:
        out.extend([value] * count)
    return out


def crossing(margins, fitted, q):
    """First margin where the fitted curve reaches q: (value, censored, left_censored)."""
    for i, p in enumerate(fitted):
        if p >= q:
            if i == 0:
                return float(margins[0]), False, True
            lo, hi = fitted[i - 1], p
            t = (q - lo) / (hi - lo) if hi > lo else 1.0
            return float(margins[i - 1] + t * (margins[i] - margins[i - 1])), False, False
    return float(margins[-1]), True, False


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def to_margin(kind, value):
    value = np.asarray(value, dtype=float)
    if kind == "value":
        return value
    if kind == "inverse":
        return 1.0 / value
    if kind == "one_minus":
        return 1.0 - value
    raise AtlasError(f"unknown margin transform {kind}")


def from_margin(kind, margin):
    if kind == "value":
        return margin
    if kind == "inverse":
        return 1.0 / margin if margin else math.inf
    return 1.0 - margin


def capacities(margins, failures, trials):
    rates = [f / n if n else 0.0 for f, n in zip(failures, trials)]
    fitted = isotonic(rates, trials)
    return fitted, {name: crossing(margins, fitted, q) for name, q in QUANTILES.items()}


def _interval(samples, alpha=0.05):
    lo, hi = np.percentile(samples, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return [float(lo), float(hi)]


# ------------------------------------------------------------------ outcomes
def failures(outcome: dict, design: dict) -> dict:
    """Per-world fall / stall / failure flags, using each axis' declared failure mode."""
    rows = design["rows"]
    fell = np.asarray(outcome["fell"], dtype=bool)
    stall_fraction = float(outcome.get("stall_fraction", 0.5))
    lin = np.asarray(outcome["linear_progress_m"], dtype=float)
    lin_expected = np.asarray(outcome["expected_linear_m"], dtype=float)
    yaw = np.asarray(outcome["yaw_progress_rad"], dtype=float)
    yaw_expected = np.asarray(outcome["expected_yaw_rad"], dtype=float)
    stalled = ~fell & (((lin_expected > 0) & (lin < stall_fraction * lin_expected))
                       | ((yaw_expected > 0) & (yaw < stall_fraction * yaw_expected)))
    axis = np.asarray(rows["axis"])
    functional = np.array([design["axis_specs"][a].get("failure") == "functional" for a in axis])
    return {"fell": fell, "stalled": stalled, "failed": fell | (functional & stalled)}


def _strata(design):
    """{(axis, group, level_index): world indices}; group = direction/azimuth index or 0."""
    rows = design["rows"]
    strata = {}
    for i, axis in enumerate(rows["axis"]):
        spec = design["axis_specs"][axis]
        groups = spec.get("directions") or spec.get("azimuths") or 1
        group = int(round(rows["direction_rad"][i] / (2 * math.pi) * groups)) % groups if groups > 1 else 0
        strata.setdefault((axis, group, rows["level_index"][i]), []).append(i)
    return {k: np.asarray(v, dtype=np.int64) for k, v in strata.items()}


def _group_labels(spec):
    if spec.get("directions"):
        count = spec["directions"]
        return [f"{round(360 * g / count)}°" for g in range(count)]
    if spec.get("azimuths"):
        names = {0: "前/下坡", 90: "左", 180: "后/上坡", 270: "右"}
        count = spec["azimuths"]
        return [names.get(round(360 * g / count), f"{round(360 * g / count)}°") for g in range(count)]
    return ["all"]


def analyze(run_dir, *, resamples: int = BOOTSTRAP, seed: int = BOOTSTRAP_SEED,
            comparisons: list[tuple[str, str]] | None = None, write: bool = True) -> dict:
    run_dir = Path(run_dir)
    design = util.read_json(run_dir / "design.json")
    raw = util.read_json(run_dir / "raw.json")
    if not isinstance(design, dict) or not isinstance(raw, dict) or raw.get("status") != "COMPLETED":
        raise AtlasError("图谱原始数据不完整")
    if raw.get("design_sha256") != util.sha256_file(run_dir / "design.json"):
        raise AtlasError("design.json 与原始数据记录的哈希不一致")
    if raw.get("parity_mode"):
        raise AtlasError("一致性模式没有扰动，不能做易损性分析")
    n = int(design["worlds"])
    labels = list(raw["policies"])
    flags = {}
    for label in labels:
        outcome = raw["policies"][label]
        if len(outcome.get("fell", [])) != n:
            raise AtlasError(f"{label} 的世界数与设计不符")
        if outcome.get("nonfinite"):
            raise AtlasError(f"{label} 出现非有限数值")
        flags[label] = failures(outcome, design)
    strata = _strata(design)
    rng = np.random.default_rng(seed)
    draws = {key: rng.integers(0, len(idx), size=(resamples, len(idx))) for key, idx in strata.items()}
    axes_out = {label: {} for label in labels}
    boot = {label: {} for label in labels}
    for axis in design["axes"]:
        spec = design["axis_specs"][axis]
        kind = spec.get("margin", "value")
        margins = to_margin(kind, spec["levels"]).tolist()
        groups = _group_labels(spec)
        L = len(spec["levels"])
        for label in labels:
            failed, fell, stalled = flags[label]["failed"], flags[label]["fell"], flags[label]["stalled"]
            counts = np.zeros((len(groups), L, 4))
            boot_fail = np.zeros((len(groups), L, resamples))
            for g in range(len(groups)):
                for li in range(L):
                    idx = strata.get((axis, g, li))
                    if idx is None:
                        continue
                    counts[g, li] = (len(idx), failed[idx].sum(), fell[idx].sum(), stalled[idx].sum())
                    boot_fail[g, li] = failed[idx][draws[(axis, g, li)]].sum(axis=1)
            trials = counts[:, :, 0].sum(0)
            fails = counts[:, :, 1].sum(0)
            fitted, point = capacities(margins, fails, trials)
            group_rows = {}
            for g, name in enumerate(groups if len(groups) > 1 else []):
                g_fitted, g_point = capacities(margins, counts[g, :, 1], counts[g, :, 0])
                group_rows[name] = {"trials": counts[g, :, 0].astype(int).tolist(), "failures": counts[g, :, 1].astype(int).tolist(),
                                    "isotonic": g_fitted, **{q: _capacity_entry(kind, g_point[q]) for q in QUANTILES}}
            samples = {q: np.empty(resamples) for q in QUANTILES}
            censored = {q: 0 for q in QUANTILES}
            group_samples = {name: np.empty(resamples) for name in group_rows}
            for b in range(resamples):
                b_fails = boot_fail[:, :, b].sum(0)
                _, b_point = capacities(margins, b_fails, trials)
                for q in QUANTILES:
                    samples[q][b] = b_point[q][0]
                    censored[q] += b_point[q][1]
                for g, name in enumerate(group_rows):
                    _, gb = capacities(margins, boot_fail[g, :, b], counts[g, :, 0])
                    group_samples[name][b] = gb["C50"][0]
            for name, values in group_samples.items():
                group_rows[name]["C50"]["ci95_margin"] = _interval(values)
            entry = {
                "label": spec.get("label"), "unit": spec.get("unit"), "failure_mode": spec.get("failure", "fall"),
                "margin_kind": kind, "levels": spec["levels"], "margins": margins,
                "trials": trials.astype(int).tolist(), "failures": fails.astype(int).tolist(),
                "falls": counts[:, :, 2].sum(0).astype(int).tolist(), "stalls": counts[:, :, 3].sum(0).astype(int).tolist(),
                "rate": [f / t if t else None for f, t in zip(fails, trials)],
                "wilson95": [wilson(int(f), int(t)) for f, t in zip(fails, trials)],
                "isotonic": fitted, "groups": group_rows,
            }
            for q in QUANTILES:
                entry[q] = _capacity_entry(kind, point[q])
                entry[q]["ci95_margin"] = _interval(samples[q])
                entry[q]["bootstrap_censored_fraction"] = censored[q] / resamples
                entry[q]["ci95_value"] = sorted(from_margin(kind, m) for m in entry[q]["ci95_margin"])
            entry["by_command"] = _by_command(design, axis, margins, failed)
            axes_out[label][axis] = entry
            boot[label][axis] = {q: samples[q] for q in QUANTILES}
            boot[label][axis]["censored_C50"] = censored["C50"] / resamples
    policies_out = {}
    for label in labels:
        outcome = raw["policies"][label]
        policies_out[label] = {"policy": outcome["policy"], "policy_sha256": outcome["policy_sha256"],
                               "nominal_tracking_rmse": _nominal_tracking(design, outcome),
                               "performance": outcome.get("performance"), "axes": axes_out[label],
                               "push_phase": _phase_profile(design, outcome, flags[label]["failed"],
                                                            axes_out[label].get("push"))}
    if comparisons is None:
        comparisons = [(label, labels[0]) for label in labels[1:]]
    compared = [compare(axes_out, boot, c, b, design["axes"]) for c, b in comparisons]
    result = {
        "schema": SCHEMA, "run": str(run_dir), "raw_sha256": util.sha256_file(run_dir / "raw.json"),
        "design_sha256": raw["design_sha256"], "evaluator_sha256": raw["evaluator_sha256"],
        "analysis_sha256": util.sha256_file(__file__), "engine": raw.get("engine"), "model": raw.get("model"),
        "seed": design["seed"], "worlds": n, "timeline": design["timeline"], "axes": design["axes"],
        "bootstrap": {"resamples": resamples, "seed": seed, "strata": "axis x group x level, paired by world"},
        "rules": {"noninferiority_margin": NONINFERIORITY_MARGIN, "quantity": "C50 margin ratio candidate/baseline",
                  "pass": "ci95 lower >= 1 - margin", "fail": "ci95 upper < 1 - margin",
                  "baseline_censored": "INSUFFICIENT when > 2.5 % of baseline resamples are censored"},
        "policies": policies_out, "comparisons": compared, "at": util.now_iso(),
        "scope": raw.get("scope"), "robot_connected": False,
    }
    if write:
        util.write_json(run_dir / "analysis.json", result)
    return result


def _capacity_entry(kind, point):
    margin, censored, left = point
    return {"margin": margin, "value": from_margin(kind, margin), "censored": bool(censored), "at_or_below_first_level": bool(left)}


def _by_command(design, axis, margins, failed):
    rows = design["rows"]
    out = {}
    names = [c[0] for c in design["commands"]]
    L = len(margins)
    for name in dict.fromkeys(names):
        trials, fails = np.zeros(L), np.zeros(L)
        for i, a in enumerate(rows["axis"]):
            if a == axis and names[rows["command_index"][i]] == name:
                trials[rows["level_index"][i]] += 1
                fails[rows["level_index"][i]] += failed[i]
        if trials.sum():
            fitted, point = capacities(margins, fails, trials)
            out[name] = {"trials": int(trials.sum()), "C50_margin": point["C50"][0], "C50_censored": bool(point["C50"][1])}
    return out


def _nominal_tracking(design, outcome):
    rows = design["rows"]
    sq = np.zeros(3)
    count = 0
    for i, axis in enumerate(rows["axis"]):
        if rows["level_index"][i] == 0 and axis != "push":
            sq += np.asarray(outcome["track_sq"][i])
            count += outcome["track_n"][i]
    if not count:
        return None
    rmse = np.sqrt(sq / count)
    return {"vx": float(rmse[0]), "vy": float(rmse[1]), "wz": float(rmse[2]), "samples": int(count),
            "worlds": "level 0 of every non-push axis; fixed command mix"}


def _phase_profile(design, outcome, failed, push_entry):
    """Failure fraction by gait phase at push onset, for pushes within ±20 % of the pooled C50."""
    if not push_entry or push_entry["C50"]["censored"]:
        return None
    centre = push_entry["C50"]["margin"]
    rows = design["rows"]
    bins = 8
    trials, fails = np.zeros(bins), np.zeros(bins)
    for i, axis in enumerate(rows["axis"]):
        phase = outcome["push_phase"][i]
        if axis != "push" or phase is None or not 0.8 * centre <= rows["level"][i] <= 1.2 * centre:
            continue
        b = min(bins - 1, int(phase * bins))
        trials[b] += 1
        fails[b] += failed[i]
    return {"bins": bins, "window": [0.8 * centre, 1.2 * centre], "trials": trials.astype(int).tolist(),
            "failures": fails.astype(int).tolist(), "rate": [f / t if t else None for f, t in zip(fails, trials)]}


def compare(axes_out, boot, candidate, baseline, axes) -> dict:
    if candidate not in axes_out or baseline not in axes_out or candidate == baseline:
        raise AtlasError("比较需要两个不同的已评测策略")
    floor = 1 - NONINFERIORITY_MARGIN
    simultaneous_alpha = 0.05 / max(1, len(axes))
    rows = {}
    for axis in axes:
        c, b = axes_out[candidate][axis], axes_out[baseline][axis]
        cb, bb = boot[candidate][axis]["C50"], boot[baseline][axis]["C50"]
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = np.where(bb > 0, cb / bb, np.nan)
        point = c["C50"]["margin"] / b["C50"]["margin"] if b["C50"]["margin"] > 0 else None
        valid = ratios[np.isfinite(ratios)]
        ci = _interval(valid) if len(valid) >= 0.95 * len(ratios) else None
        ci_sim = _interval(valid, simultaneous_alpha) if ci else None
        baseline_censored = boot[baseline][axis]["censored_C50"]
        if ci is None or baseline_censored > 0.025:
            status, reason = "INSUFFICIENT", ("基线在扫描范围内未达到 50% 失效，无法确定比值" if baseline_censored > 0.025
                                              else "比值无法估计")
        elif ci[0] >= floor:
            status, reason = "PASS", "非劣效：比值 95% 下界不低于 {:.2f}".format(floor)
        elif ci[1] < floor:
            status, reason = "FAIL", "劣于基线：比值 95% 上界低于 {:.2f}".format(floor)
        else:
            status, reason = "INSUFFICIENT", "区间跨越非劣效界，证据不足"
        rows[axis] = {"label": c["label"], "unit": c["unit"], "candidate_C50": c["C50"], "baseline_C50": b["C50"],
                      "ratio": point, "ci95": ci, "ci_simultaneous": ci_sim, "status": status, "reason": reason,
                      "better": bool(ci_sim and ci_sim[0] > 1.0), "worse": bool(ci_sim and ci_sim[1] < 1.0),
                      "candidate_censored_fraction": boot[candidate][axis]["censored_C50"],
                      "baseline_censored_fraction": baseline_censored}
    statuses = [r["status"] for r in rows.values()]
    verdict = "FAIL" if "FAIL" in statuses else "PASS" if statuses and all(s == "PASS" for s in statuses) else "INSUFFICIENT"
    return {"candidate": candidate, "baseline": baseline, "axes": rows, "verdict": verdict,
            "better_axes": [a for a, r in rows.items() if r["better"]],
            "worse_axes": [a for a, r in rows.items() if r["worse"]],
            "failed_axes": [a for a, r in rows.items() if r["status"] == "FAIL"],
            "simultaneous_alpha": simultaneous_alpha}


# ------------------------------------------------------------------ running
FW16_SLOTS = ("booster_fw16_walk", "booster_fw16_side", "booster_fw16_turn")


def policy_spec(pack_id: str) -> tuple[str, Path]:
    """Engine policy specification and the file whose hash identifies the policy."""
    pack = packs.load(pack_id)
    slot = packs.motion_slots(pack)[0]
    if slot == "walk":
        if pack["kind"] == "baseline":
            path = paths.BH_LOCAL / pack["components"]["walk"]["official_file"]
        else:
            path = packs.pack_dir(pack["id"]) / pack["components"]["walk"]["file"]
        return str(path), path
    if slot == "booster_fw16_walk":
        present = [s for s in FW16_SLOTS if s in pack["components"]]
        if present not in (["booster_fw16_walk"], list(FW16_SLOTS)):
            raise AtlasError("原厂 1.6 运控包需包含 forward，或同时包含 forward/side/turn 三个网络")
        files = [packs.pack_dir(pack["id"]) / pack["components"][s]["file"] for s in present]
        if len({f.parent for f in files}) != 1 or [f.name for f in files] != [s + ".onnx" for s in present]:
            raise AtlasError("原厂 1.6 网络文件布局与引擎约定不符")
        for slot_name, file in zip(present, files):
            if util.sha256_file(file) != pack["components"][slot_name]["sha256"]:
                raise AtlasError(f"{slot_name} 文件哈希与运控包登记不符")
        return f"booster_fw16:{files[0].parent}", files[0]
    raise AtlasError(f"图谱引擎尚无 {slot} 契约适配器；支持 B-Human walk 344→13 与原厂 1.6 690→20")


def policy_file(pack_id: str) -> Path:
    return policy_spec(pack_id)[1]


def run(pack_ids: list[str], *, axes: list[str] | None = None, seed: int = 2027, replica_scale: float = 1.0,
        tag: str | None = None, on_line=print) -> dict:
    """Evaluate the listed packs on one shared world table; the first pack is the baseline."""
    if len(pack_ids) < 1 or len(set(pack_ids)) != len(pack_ids):
        raise AtlasError("需要至少一个且互不相同的运控包")
    if not 0.05 <= replica_scale <= 8:
        raise AtlasError("replica_scale 需在 0.05..8")
    run_dir = RUNS / f"{util.stamp()}_{util.safe_name(tag or '-vs-'.join(pack_ids), 60)}"
    command = [str(paths.INTERPRETERS["mjlab"]), "-B", str(ENGINE), "--seed", str(seed),
               "--replica-scale", str(replica_scale), "--out", str(run_dir)]
    if axes:
        command += ["--axes", ",".join(axes)]
    files = {}
    for pack_id in pack_ids:
        spec, path = policy_spec(pack_id)
        files[pack_id] = {"path": str(path), "sha256": util.sha256_file(path), "spec": spec}
        command += ["--policy", f"{pack_id}={spec}"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in process.stdout:
        tail = (tail + [line])[-40:]
        if on_line and (line.startswith("[atlas]") or line.startswith("RESULT") or "Error" in line):
            on_line(line if line.endswith("\n") else line + "\n")
    code = process.wait()
    if code != 0 or not (run_dir / "raw.json").is_file():
        raise AtlasError("图谱引擎失败（退出码 %s）：%s" % (code, "".join(tail[-8:])))
    raw = util.read_json(run_dir / "raw.json")
    for pack_id, info in files.items():
        if raw["policies"][pack_id]["policy_sha256"] != info["sha256"]:
            raise AtlasError(f"{pack_id} 的评测策略哈希与运控包不符")
    util.write_json(run_dir / "packs.json", {"baseline": pack_ids[0], "packs": files,
                                             "pack_snapshots": {p: packs.load(p) for p in pack_ids}})
    result = analyze(run_dir)
    if on_line:
        for row in result["comparisons"]:
            on_line(f"[atlas] {row['candidate']} vs {row['baseline']}: {row['verdict']}\n")
    return result


def list_runs(limit: int = 50) -> list[dict]:
    out = []
    for directory in sorted(RUNS.glob("*/"), reverse=True)[:limit]:
        analysis = util.read_json(directory / "analysis.json")
        raw_ok = (directory / "raw.json").is_file()
        entry = {"id": directory.name, "analyzed": bool(analysis), "raw": raw_ok}
        if analysis:
            entry.update(policies=list(analysis["policies"]), axes=analysis["axes"], worlds=analysis["worlds"],
                         verdicts={f"{c['candidate']}|{c['baseline']}": c["verdict"] for c in analysis["comparisons"]},
                         at=analysis.get("at"))
        out.append(entry)
    return out


def load(run_id: str) -> dict:
    directory = RUNS / run_id
    if "/" in run_id or run_id.startswith(".") or not directory.is_dir():
        raise AtlasError("图谱运行不存在")
    analysis = util.read_json(directory / "analysis.json")
    if analysis is None:
        raise AtlasError("该运行尚未分析")
    analysis["packs"] = (util.read_json(directory / "packs.json") or {}).get("packs")
    return analysis
