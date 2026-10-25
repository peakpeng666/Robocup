"""Independent, content-addressed behavior profiles on the official B-Human stack.

Only audited behavior configuration scalars are supported. Motion, perception,
robot connectivity and compiled modules cannot be changed through this interface.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import bhconfig, packs, paths, util

BASELINE_ID = "bhuman-official-strategy"
CONFIG_REQUESTS = {
    "behaviorParameters.cfg": "representation:BehaviorParameters",
    "skillBehaviorControl.cfg": "module:SkillBehaviorControl",
    "strategyBehaviorControl.cfg": "module:StrategyBehaviorControl",
}
PARAMETERS = {
    "behaviorParameters.cfg": {k: (0, 30000) for k in (
        "ballSeenThreshold", "ballLostThreshold", "ballSearchThresholdNoTeam", "ballSearchThresholdTeam",
        "noCommunicationAfterUnpenalizedTime", "noSkillRequestAfterUnpenalizedTime", "lookAroundAfterUnpenalizedTime")},
    "skillBehaviorControl.cfg": {"continueReceivePassTime": (0, 10000), "ignoreReceivePassAfterTime": (0, 30000)},
}
PRESETS = {
    "earlier-ball-search": {"name": "提前搜球", "description": "仅缩短丢球后的搜球等待；实验配置，不预设效果更好。",
                           "cfg_patches": {"behaviorParameters.cfg": {"ballSearchThresholdNoTeam": "1500", "ballSearchThresholdTeam": "5000"}}},
    "longer-pass-reception": {"name": "延长接应等待", "description": "接应状态多保留 300 ms；需在对照赛观察实际效果。",
                             "cfg_patches": {"skillBehaviorControl.cfg": {"continueReceivePassTime": "800"}}},
}


def _canonical(patches):
    return json.dumps({"cfg_patches": patches}, sort_keys=True, separators=(",", ":"))


def directory(identifier: str) -> Path:
    if not isinstance(identifier, str) or not identifier or "/" in identifier or identifier.startswith("."):
        raise ValueError("策略标识无效")
    return paths.STRATEGIES / identifier


def load(identifier: str) -> dict:
    if identifier == BASELINE_ID:
        return {"schema": "forge.strategy/1", "id": BASELINE_ID, "name": "B-Human 官方策略",
                "kind": "baseline", "cfg_patches": {}, "content_sha256": util.sha256_bytes(_canonical({}).encode())}
    result = util.read_json(directory(identifier) / "strategy.json")
    if not result:
        raise ValueError(f"策略不存在: {identifier}")
    digest = util.sha256_bytes(_canonical(result.get("cfg_patches")).encode())
    if result.get("id") != identifier or result.get("content_sha256") != digest or not identifier.endswith("-" + digest[:10]):
        raise ValueError("策略内容与身份哈希不一致")
    validate(result["cfg_patches"])
    return result


def validate(patches: dict) -> None:
    if not isinstance(patches, dict) or not patches:
        raise ValueError("策略修改不能为空")
    for filename, changes in patches.items():
        if filename not in PARAMETERS or not isinstance(changes, dict) or not changes:
            raise ValueError(f"暂不支持此策略配置: {filename}")
        source = bhconfig.resolve(paths.BH_LOCAL / "Config", filename, robot_name="SimulatedK1", location="MField")
        document = bhconfig.CfgDocument.load(source)
        for key, value in changes.items():
            if key not in PARAMETERS[filename] or not isinstance(value, str) or not value.isascii() or not value.isdecimal():
                raise ValueError(f"{filename}:{key} 需为支持的非负整数毫秒参数")
            low, high = PARAMETERS[filename][key]
            if not low <= int(value) <= high:
                raise ValueError(f"{key} 必须在 {low}..{high} ms")
        document.patched(changes)


def create(name: str, patches: dict, description: str = "") -> dict:
    validate(patches)
    digest = util.sha256_bytes(_canonical(patches).encode())
    identifier = f"{util.safe_name(name, 32)}-{digest[:10]}"
    target = directory(identifier) / "strategy.json"
    if target.exists():
        return load(identifier)
    result = {"schema": "forge.strategy/1", "id": identifier, "name": name, "kind": "candidate",
              "description": description, "cfg_patches": patches, "content_sha256": digest, "at": util.now_iso()}
    util.write_json(target, result)
    return result


def list_profiles() -> list[dict]:
    profiles = [load(BASELINE_ID)]
    for path in sorted(paths.STRATEGIES.glob("*/strategy.json")):
        try:
            profiles.append(load(path.parent.name))
        except ValueError as exc:
            profiles.append({"id": path.parent.name, "name": path.parent.name, "kind": "invalid", "error": str(exc)})
    return profiles


def motion_only(pack: dict) -> None:
    allowed = {"walkingEngine.cfg", "motorParameters.cfg", "odometryDataPreviewProvider.cfg"}
    if set(pack.get("cfg_patches") or {}) - allowed:
        raise ValueError("运控包混有非运控配置；验证入口只允许行走、马达和里程计参数，策略需独立选择")


def compose(motion_id: str, strategy_id: str) -> dict:
    motion, strategy = packs.load(motion_id), load(strategy_id)
    motion_only(motion)
    if packs.verify(motion_id)["status"] != "PASS":
        raise ValueError("运控包身份或契约校验失败")
    if strategy_id == BASELINE_ID:
        return motion
    components = {} if motion["kind"] == "baseline" else {
        k: str(packs.pack_dir(motion_id) / v["file"]) for k, v in motion["components"].items()}
    patches = {**(motion.get("cfg_patches") or {}), **strategy["cfg_patches"]}
    return packs.create(f"team-{motion_id[:10]}-{strategy_id[:12]}", components, patches,
                        "SimRobot 验证组合：独立选择运控与策略", {"composition": {
                            "motion_pack_id": motion_id, "strategy_id": strategy_id,
                            "strategy_sha256": strategy["content_sha256"]}}, motion.get("modules") or {})


def scalar_equal(expected: str, observed: str) -> bool:
    def number(value):
        value = value.strip()
        if value.endswith("deg"):
            return math.radians(float(value[:-3]))
        if value.endswith("rad"):
            return float(value[:-3])
        return float(value)
    try:
        return math.isclose(number(expected), number(observed), rel_tol=1e-4, abs_tol=1e-4)
    except ValueError:
        return expected.strip().strip('"') == observed.strip().strip('"')


def runtime_requests(arena, run: Path, roster: dict) -> tuple[list[tuple[int, str]], list[dict]]:
    """Request actual Cognition parameters into this run, never into source Config."""
    output = run / "runtime-config"
    output.mkdir()
    commands, expected = [], []
    for robot, (team, player) in roster.items():
        commands.append((500, f"robot {robot}"))
        for filename, request in CONFIG_REQUESTS.items():
            source = bhconfig.resolve(arena.config, filename, robot_name="SimulatedK1", location="MField",
                                      scenario=f"Forge_T{team}")
            target = output / f"T{team}-P{player}-{filename}"
            commands.append((500, f'for Cognition get {request} save "{target}"'))
            expected.append({"robot": robot, "team": team, "player": player, "filename": filename,
                             "source": str(source), "source_sha256": util.sha256_file(source), "output": str(target),
                             "values": {key: scalar.text for key, scalar in bhconfig.CfgDocument.load(source).scalars.items()}})
    commands.append((500, "robot all"))
    return commands, expected


def verify_runtime(expected: list[dict]) -> dict:
    rows = []
    for spec in expected:
        target = Path(spec["output"])
        try:
            actual = bhconfig.CfgDocument.load(target)
            mismatches = [key for key, value in spec["values"].items()
                          if key not in actual.scalars or not scalar_equal(value, actual.scalars[key].text)]
            rows.append({**spec, "ok": not mismatches, "mismatches": mismatches, "sha256": util.sha256_file(target),
                         "actual": {k: v.text for k, v in actual.scalars.items()}})
        except (OSError, ValueError) as exc:
            rows.append({**spec, "ok": False, "error": str(exc)})
    return {"ok": bool(rows) and all(r["ok"] for r in rows), "robots": len({r["robot"] for r in rows}), "files": rows}
