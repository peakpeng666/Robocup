"""Evidence dossier: one read-only view of everything known about a motion pack.

Forge and the training mainline write evidence into many timestamped directories
(training runs, exports, Isaac Gym evaluations, MuJoCo Warp stress tests, fragility
atlases, SimRobot matches / validations / recoveries, series, duels, pipelines, gates).
This module indexes those files *without rewriting them* and links them to packs by
identity: pack id where a runner recorded it, otherwise the walk ONNX SHA-256 or the
checkpoint SHA-256.  A hash shared by several packs (an A/A copy) is reported as such.

The dossier answers: where did this pack come from, which evidence exists, what did each
piece conclude, and which evidence is still missing for a promotion decision.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import packs, paths, util

SCHEMA = "forge.dossier/1"
_CACHE: dict = {"at": 0.0, "index": None}
CACHE_SECONDS = 20


def _rel(path) -> str:
    return paths.rel(path)


def _stamp_of(name: str) -> str:
    """'20261022_202543_...' -> ISO-like text for ordering and display."""
    return f"{name[:4]}-{name[4:6]}-{name[6:8]} {name[9:11]}:{name[11:13]}:{name[13:15]}" if name[:8].isdigit() else name


def _walk_hash(pack: dict) -> str | None:
    walk = (pack.get("components") or {}).get("walk") or {}
    return walk.get("sha256")


def build_index(force: bool = False) -> dict:
    if not force and _CACHE["index"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["index"]
    from .training import OFFICIAL_WALK_SHA256

    pack_rows = {p["id"]: p for p in packs.list_packs()}
    by_walk, by_checkpoint = {}, {}
    for pack in pack_rows.values():
        if _walk_hash(pack):
            by_walk.setdefault(_walk_hash(pack), set()).add(pack["id"])
        checkpoint = (pack.get("provenance") or {}).get("checkpoint_sha256")
        if checkpoint:
            by_checkpoint.setdefault(checkpoint, set()).add(pack["id"])
    by_checkpoint.setdefault(OFFICIAL_WALK_SHA256, set()).add(packs.BASELINE_ID)
    records = []

    def add(kind, path, at, link, **fields):
        records.append({"kind": kind, "path": _rel(path), "id": Path(path).parent.name if Path(path).is_file() else Path(path).name,
                        "at": at, "packs": sorted(link), **fields})

    # Isaac Gym frozen-schedule evaluations (mainline and Forge wrappers) link by checkpoint hash.
    for path in sorted((paths.TRAINING / "runs").glob("*walk_eval*/results.json")):
        data = util.read_json(path) or {}
        sha = data.get("policy_sha256")
        segments = data.get("segments") or {}
        moving = [s.get("tracking_rmse_settled_vx_vy_wz") for s in segments.values()
                  if any(abs(c) > 1e-9 for c in (s.get("command_vx_vy_wz") or [0, 0, 0]))]
        rmse = [sum(r[i] for r in moving) / len(moving) for i in range(3)] if moving and all(moving) else None
        add("isaac_eval", path, _stamp_of(path.parent.name), by_checkpoint.get(sha, set()), policy_sha256=sha,
            status="COMPLETED" if data.get("finite_checks_pass") else "INCOMPLETE", seed=data.get("seed"),
            summary={"rmse_vx_vy_wz_moving": rmse,
                     "resets": (data.get("termination_events_total") or {}).get("non_timeout_reset")})
    # MuJoCo Warp stress tests link by ONNX hash (an A/A copy shares the official hash).
    for path in sorted((paths.RUNS / "mjwarp").glob("*/result.json")):
        data = util.read_json(path) or {}
        metrics = data.get("metrics") or {}
        add("mujoco_stress", path, _stamp_of(path.parent.name), by_walk.get(data.get("policy_sha256"), set()),
            policy_sha256=data.get("policy_sha256"), status=data.get("status"),
            summary={"worlds": (data.get("setup") or {}).get("worlds"), "push_force_max_N": (data.get("setup") or {}).get("push_force_max_N"),
                     "schedule": (data.get("setup") or {}).get("schedule"), "fall_rate": metrics.get("fall_rate"),
                     "tracking_rmse": metrics.get("tracking_rmse")})
    # Fragility atlases record pack ids as policy labels.
    for path in sorted((paths.RUNS / "atlas").glob("*/analysis.json")):
        data = util.read_json(path) or {}
        labels = set(data.get("policies") or {})
        comparisons = {c["candidate"]: {"verdict": c["verdict"], "baseline": c["baseline"], "better_axes": c.get("better_axes"),
                                        "worse_axes": c.get("worse_axes"), "failed_axes": c.get("failed_axes")}
                       for c in data.get("comparisons") or []}
        add("atlas", path, _stamp_of(path.parent.name), labels & set(pack_rows), status="COMPLETED",
            summary={"worlds": data.get("worlds"), "comparisons": comparisons,
                     "C50": {label: {axis: row["C50"]["value"] for axis, row in (policy.get("axes") or {}).items()}
                             for label, policy in (data.get("policies") or {}).items()}})
    # SimRobot runs record the pack flashed to every team.
    for kind, base in (("simrobot_match", "matches"), ("simrobot_motion", "motion"), ("simrobot_recovery", "recovery")):
        for path in sorted((paths.RUNS / base).glob("*/launch.json")):
            launch = util.read_json(path) or {}
            result = util.read_json(path.parent / "result.json") or {}
            teams = {t: (v or {}).get("pack_id") for t, v in (launch.get("teams") or {}).items()}
            add(kind, path, _stamp_of(path.parent.name), {p for p in teams.values() if p}, status=result.get("status") or "INCOMPLETE",
                summary={"teams": teams, "score": result.get("score"), "case": launch.get("case"),
                         "recovery": (result.get("recovery") or {}).get("conclusion"),
                         "execution_status": result.get("execution_status")})
    for path in sorted((paths.RUNS / "series").glob("*/series.json")):
        data = util.read_json(path) or {}
        add("series", path, _stamp_of(path.parent.name), {data.get("pack_a"), data.get("pack_b")} - {None},
            status=data.get("status"), summary={"record": data.get("record"), "rounds": data.get("rounds_played")})
    for path in sorted((paths.RUNS / "duels").glob("*/duel.json")):
        data = util.read_json(path) or {}
        plan = data.get("plan") or {}
        linked = {plan.get("candidate"), plan.get("baseline")} if plan.get("kind") == "motion" else {plan.get("motion_pack")}
        summary = data.get("summary") or {}
        add("duel", path, _stamp_of(path.parent.name), linked - {None}, status=data.get("status"),
            summary={"kind": plan.get("kind"), "candidate": plan.get("candidate"), "baseline": plan.get("baseline"),
                     "decision": data.get("decision"), "pairs": summary.get("pairs_complete"), "record": summary.get("record"),
                     "goal_cs": [summary.get("goal_difference_cs", {}).get(k) for k in ("lower", "upper")]})
    for path in sorted((paths.RUNS / "validations").glob("*/validation.json")):
        data = util.read_json(path) or {}
        plan = data.get("plan") or {}
        add("validation", path, _stamp_of(path.parent.name), {plan.get("motion_pack")} - {None}, status=data.get("status"),
            summary={"mode": plan.get("mode"), "strategy": plan.get("strategy_id"), "verdict": data.get("verdict")})
    for path in sorted((paths.RUNS / "gates").glob("*.json")):
        data = util.read_json(path) or {}
        records.append({"kind": "gate", "path": _rel(path), "id": path.stem, "at": _stamp_of(path.stem),
                        "packs": [data["pack_id"]] if data.get("pack_id") else [], "status": data.get("verdict"),
                        "summary": {"rule_version": data.get("rule_version"),
                                    "gates": {k: (v or {}).get("status") for k, v in (data.get("gates") or {}).items()}}})
    for path in sorted((paths.RUNS / "pipelines").glob("*/pipeline.json")):
        data = util.read_json(path) or {}
        add("pipeline", path, _stamp_of(path.parent.name), {data.get("pack_id")} - {None}, status=data.get("verdict") or "INCOMPLETE",
            summary={"steps": {k: (v or {}).get("status") for k, v in (data.get("steps") or {}).items()}})
    index = {"schema": SCHEMA, "built_at": util.now_iso(), "records": records, "packs": sorted(pack_rows),
             "hash_aliases": {h: sorted(ids) for h, ids in by_walk.items() if len(ids) > 1}}
    _CACHE.update(at=time.time(), index=index)
    return index


def _lineage(pack: dict) -> list[dict]:
    provenance = pack.get("provenance") or {}
    stages = []
    checkpoint = provenance.get("checkpoint")
    if checkpoint:
        run_dir = Path(checkpoint).parent.parent
        launch = util.read_json(run_dir / "launch.json") or {}
        execution = util.read_json(run_dir / "execution.json") or {}
        detail = {k: launch.get(k) for k in ("preset", "label", "envs", "iterations", "seed", "mode", "recipe") if launch.get(k) is not None}
        for key in ("source_sha256", "wall_s", "sampled_gpu_peak_mib"):
            value = launch.get(key, execution.get(key))
            if value is not None and key not in detail:
                detail[key] = value
        stages.append({"stage": "训练", "id": run_dir.name, "path": _rel(run_dir), "status": execution.get("status"), "detail": detail})
        stages.append({"stage": "检查点", "id": Path(checkpoint).name, "path": _rel(checkpoint),
                       "status": "RECORDED", "detail": {"sha256": provenance.get("checkpoint_sha256")}})
    if provenance.get("export_dir"):
        tri = (provenance.get("tri_check") or {}).get("verdict")
        stages.append({"stage": "导出", "id": Path(provenance["export_dir"]).name, "path": _rel(provenance["export_dir"]),
                       "status": tri or "RECORDED", "detail": {"tri_check": tri, "load_mode": (provenance.get("export_manifest") or {}).get("load_mode")}})
    if provenance.get("firmware_version"):
        stages.append({"stage": "原厂固件导出", "id": str(provenance.get("firmware_version")), "path": None, "status": "RECORDED",
                       "detail": {"controller_scope": provenance.get("controller_scope")}})
    stages.append({"stage": "运控包", "id": pack["id"], "path": _rel(packs.pack_dir(pack["id"])) if pack["kind"] != "baseline" else None,
                   "status": pack.get("status"), "detail": {"walk_sha256": _walk_hash(pack), "components": list(pack.get("components") or {}),
                                                          "modules": list((pack.get("modules") or {}).keys())}})
    return stages


EXPECTED = (("isaac_eval", "Isaac Gym 冻结日程评估"), ("mujoco_stress", "MuJoCo Warp 压力评测"), ("atlas", "易损性图谱"),
            ("simrobot_motion", "SimRobot 固定指令运控"), ("simrobot_recovery", "SimRobot 跌倒恢复"),
            ("duel", "SimRobot 序贯对决"), ("gate", "晋级门"))


def dossier(pack_id: str) -> dict:
    pack = packs.load(pack_id)
    index = build_index()
    evidence = [r for r in index["records"] if pack_id in r["packs"]]
    by_kind = {}
    for row in sorted(evidence, key=lambda r: r["at"], reverse=True):
        by_kind.setdefault(row["kind"], []).append(row)
    walk = _walk_hash(pack)
    aliases = [p for p in index["hash_aliases"].get(walk, []) if p != pack_id] if walk else []
    latest = {kind: rows[0] for kind, rows in by_kind.items()}
    scorecard = {}
    if "atlas" in latest:
        comparison = latest["atlas"]["summary"]["comparisons"].get(pack_id)
        scorecard["atlas"] = comparison or {"note": "作为基线出现在图谱中"}
    if "duel" in latest:
        scorecard["duel"] = latest["duel"]["summary"]
    if "gate" in latest:
        scorecard["gate"] = {"verdict": latest["gate"]["status"], **latest["gate"]["summary"]}
    if "mujoco_stress" in latest:
        scorecard["mujoco_stress"] = latest["mujoco_stress"]["summary"]
    if "isaac_eval" in latest:
        scorecard["isaac_eval"] = latest["isaac_eval"]["summary"]
    if "validation" in latest:
        scorecard["validation"] = latest["validation"]["summary"]
    missing = [label for kind, label in EXPECTED if kind not in by_kind and not (kind == "simrobot_motion" and "validation" in by_kind)]
    if pack["kind"] == "baseline":
        missing = []
    return {"schema": SCHEMA, "pack": {k: pack.get(k) for k in ("id", "name", "kind", "status", "description", "created_at")},
            "walk_sha256": walk, "hash_aliases": aliases, "lineage": _lineage(pack), "evidence": by_kind,
            "counts": {k: len(v) for k, v in by_kind.items()}, "scorecard": scorecard, "missing": missing,
            "note": "只读索引：证据按包 ID、walk ONNX 或检查点哈希关联；字节相同的副本共享按哈希关联的证据。"
                    "仿真证据不代表真机资格（L5 固定未验证）。", "built_at": index["built_at"]}


def overview() -> list[dict]:
    index = build_index()
    rows = []
    for pack in packs.list_packs():
        evidence = [r for r in index["records"] if pack["id"] in r["packs"]]
        kinds = {}
        for row in evidence:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        latest_gate = max((r for r in evidence if r["kind"] == "gate"), key=lambda r: r["at"], default=None)
        latest_atlas = max((r for r in evidence if r["kind"] == "atlas"), key=lambda r: r["at"], default=None)
        latest_duel = max((r for r in evidence if r["kind"] == "duel"), key=lambda r: r["at"], default=None)
        rows.append({"id": pack["id"], "name": pack["name"], "kind": pack["kind"], "status": pack.get("status"),
                     "evidence": kinds, "total": len(evidence),
                     "gate": latest_gate and latest_gate["status"],
                     "atlas": latest_atlas and (latest_atlas["summary"]["comparisons"].get(pack["id"]) or {}).get("verdict"),
                     "duel": latest_duel and latest_duel["summary"].get("decision")})
    return rows
