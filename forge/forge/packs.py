"""Motion Packs: immutable, content-addressed bundles of motion-control networks + cfg patches.

Layout::

    packs/<pack_id>/pack.json
    packs/<pack_id>/files/<slot>.onnx

``pack_id = <slug>-<sha256(canonical content)[:10]>`` where the canonical content is the
set of component hashes and cfg patches. Re-creating a pack with identical content
returns the existing id; a different content can never reuse an id.
The baseline pack (``bhuman-official``) carries no files: flashing it restores the
original B-Human SimulatedK1 configuration byte for byte.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import contracts, paths, util

SCHEMA = "forge.motion-pack/1"
BASELINE_ID = "bhuman-official"


class PackError(ValueError):
    pass


MODULE_REPLACEABLE = {
    "WalkingEngine": ("WalkGenerator", "StandGenerator", "WalkStepData", "WalkingEngineOutput"),
    "MotionEngine": ("JointRequest", "ArmMotionInfo", "HeadMotionInfo", "MotionInfo", "OdometryData"),
}


def validate_bindings(components: dict, modules: dict) -> None:
    """Reject a foreign policy without its matching compiled consumer, and vice versa."""
    replacements = [spec.get("replaces") for spec in modules.values()]
    if len(replacements) != len(set(replacements)):
        raise PackError("每个原始模块只能选择一个替代模块")
    if "MotionEngine" in replacements and components:
        raise PackError("完整运动 provider 自行管理控制核心，不能同时声明 B-Human/局部适配网络槽位")
    required = {}
    active_replacements = set()
    for slot, spec in contracts.ADAPTER_SLOTS.items():
        required.setdefault(spec["module"], []).append(slot)
        if slot in components:
            if spec["module"] not in modules:
                raise PackError(f"{slot} 网络与 {spec['module']} 模块必须一起选择")
            if spec["replaces"] in components or spec["replaces"] in active_replacements:
                raise PackError(f"{slot} 与其他网络不能同时替换 {spec['replaces']} 运控")
            active_replacements.add(spec["replaces"])
    for module, slots in required.items():
        if module in modules and sum(slot in components for slot in slots) != 1:
            raise PackError(f"{module} 必须一起选择一个兼容网络：{', '.join(slots)}")
    switcher = (modules.get("BoosterDeployWalkingEngine", {}).get("params") or {}).get(
        "walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher", "false")
    if switcher not in ("true", "false"):
        raise PackError("boosterUseFirmwareSwitcher 必须为 true 或 false")
    auxiliary = set(components) & set(contracts.AUXILIARY_SLOTS)
    if auxiliary or switcher == "true":
        if (auxiliary != set(contracts.AUXILIARY_SLOTS) or "booster_fw16_walk" not in components
                or "BoosterDeployWalkingEngine" not in modules or switcher != "true"):
            raise PackError("固件多策略必须同时包含 forward、side、turn 模型，并显式启用 boosterUseFirmwareSwitcher=true")
    for slot, spec in contracts.AUXILIARY_SLOTS.items():
        if slot in components and contracts.CONTRACTS[slot].cfg_key in (modules[spec["module"]].get("params") or {}):
            raise PackError(f"{slot} 模型路径由组件自动生成，不能手动覆盖模块参数")


def motion_slots(manifest: dict) -> tuple[str, ...]:
    """The actual walk/kick consumers, including an explicitly selected foreign gait."""
    if any(spec.get("replaces") == "MotionEngine" for spec in (manifest.get("modules") or {}).values()):
        return ()  # The complete native graph owns its own models, not WalkingEngine.
    replaced = {spec["replaces"]: slot for slot, spec in contracts.ADAPTER_SLOTS.items()
                if slot in manifest["components"]}
    return (tuple(replaced.get(slot, slot) for slot in contracts.FLASHABLE)
            + tuple(slot for slot in contracts.AUXILIARY_SLOTS if slot in manifest["components"]))


def module_model_params(manifest: dict, module: str) -> dict[str, str]:
    return {contracts.CONTRACTS[slot].cfg_key: f"forge/{manifest['id']}/{slot}.onnx"
            for slot, spec in contracts.AUXILIARY_SLOTS.items()
            if slot in manifest["components"] and spec["module"] == module}


def _canonical(components: dict, cfg_patches: dict, modules: dict | None = None) -> str:
    content = {"components": {k: v["sha256"] for k, v in sorted(components.items())}, "cfg_patches": cfg_patches}
    if modules:
        content["modules"] = modules
    return json.dumps(content, sort_keys=True, separators=(",", ":"))


def pack_dir(pack_id: str) -> Path:
    if not pack_id or "/" in pack_id or pack_id.startswith("."):
        raise PackError(f"invalid pack id {pack_id!r}")
    return paths.PACKS / pack_id


def load(pack_id: str) -> dict:
    if pack_id == BASELINE_ID and not (pack_dir(pack_id) / "pack.json").exists():
        return ensure_baseline()
    manifest = util.read_json(pack_dir(pack_id) / "pack.json")
    if not manifest:
        raise PackError(f"运控包不存在: {pack_id}")
    return manifest


def list_packs() -> list[dict]:
    ensure_baseline()
    out = []
    for path in sorted(paths.PACKS.glob("*/pack.json")):
        manifest = util.read_json(path)
        if manifest:
            out.append(manifest)
    out.sort(key=lambda m: (m.get("kind") != "baseline", m.get("created_at", "")))
    return out


def ensure_baseline() -> dict:
    """Register the official B-Human K1 motion networks as the immutable baseline."""
    target = pack_dir(BASELINE_ID) / "pack.json"
    existing = util.read_json(target)
    components = {}
    for slot in contracts.FLASHABLE:
        contract = contracts.CONTRACTS[slot]
        official = paths.BH_OFFICIAL / contract.official_file
        local = paths.BH_LOCAL / contract.official_file
        digest = util.sha256_file(official)
        if util.sha256_file(local) != digest:
            raise PackError(f"bhuman-local 的 {contract.official_file} 与官方发布不一致，拒绝建立基线")
        components[slot] = {"file": None, "official_file": contract.official_file, "sha256": digest,
                            "contract": contract.id}
    manifest = {
        "schema": SCHEMA, "id": BASELINE_ID, "kind": "baseline", "name": "B-Human 官方运控",
        "description": "BHumanCodeRelease 2026 官方 K1 行走/踢球网络与 SimulatedK1 原配置；刷写即恢复原样。",
        "components": components, "cfg_patches": {},
        "base": {"BHumanCodeRelease": paths.OFFICIAL_UPSTREAM["BHumanCodeRelease"]},
        "provenance": {"source": "bhuman/BHumanCodeRelease@" + paths.OFFICIAL_UPSTREAM["BHumanCodeRelease"]},
        "status": "baseline",
    }
    if existing and existing.get("components") == components:
        return existing
    manifest["created_at"] = util.now_iso()
    util.write_json(target, manifest)
    return manifest


def create(name: str, components: dict[str, str], cfg_patches: dict | None = None,
           description: str = "", provenance: dict | None = None, modules: dict | None = None) -> dict:
    """Create (or return the identical existing) pack.

    ``components``: {slot: path to .onnx}; ``cfg_patches``: {cfg file name: {key path: value}}.
    """
    cfg_patches = cfg_patches or {}
    modules = modules or {}
    if not components and not cfg_patches and not modules:
        raise PackError("运控包至少要包含一个网络、一个配置修改或一个代码模块")
    for module, spec in modules.items():
        import re as _re

        if not _re.fullmatch(r"[A-Z][A-Za-z0-9]{2,63}", module):
            raise PackError(f"模块名不合法: {module}")
        if spec.get("replaces") not in MODULE_REPLACEABLE:
            raise PackError(f"目前只支持替换 {sorted(MODULE_REPLACEABLE)}")
        expected_cfg = module[0].lower() + module[1:] + ".cfg"
        if spec.get("cfg") != expected_cfg:
            raise PackError(f"B-Human 按模块名加载参数文件，应为 {expected_cfg}")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in (spec.get("params") or {}).items()):
            raise PackError("模块参数必须是字符串键值")
    validate_bindings(components, modules)
    checked = {}
    for slot, source in components.items():
        if slot not in contracts.PACK_SLOTS:
            raise PackError(f"槽位 {slot} 目前不能刷写（可用: {', '.join(contracts.PACK_SLOTS)}）")
        source = Path(source).resolve()
        if not source.is_file():
            raise PackError(f"文件不存在: {source}")
        info = contracts.check(slot, source)  # raises ContractError
        checked[slot] = {"file": f"files/{slot}.onnx", "sha256": info["sha256"], "contract": info["contract"],
                         "source_path": str(source), "onnx": {k: info[k] for k in
                         ("opset", "inputs", "outputs", "nodes", "ops", "parameters", "ort_smoke")}}
    for cfg_name, changes in cfg_patches.items():
        if not cfg_name.endswith(".cfg") or "/" in cfg_name:
            raise PackError(f"配置修改只能针对单个 .cfg 文件名: {cfg_name}")
        if not isinstance(changes, dict) or not changes:
            raise PackError(f"{cfg_name} 的修改必须是非空键值表")
    digest = util.sha256_bytes(_canonical(checked, cfg_patches, modules).encode())
    pack_id = f"{util.safe_name(name, 32)}-{digest[:10]}"
    target = pack_dir(pack_id)
    existing = util.read_json(target / "pack.json")
    if existing:
        if existing.get("content_sha256") != digest:
            raise PackError(f"运控包 {pack_id} 已存在且内容不同，拒绝覆盖")
        return existing
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "files").mkdir(parents=True)
    for slot, entry in checked.items():
        shutil.copy2(entry["source_path"], staging / entry["file"])
        if util.sha256_file(staging / entry["file"]) != entry["sha256"]:
            raise PackError(f"复制 {slot} 后哈希不一致")
    manifest = {
        "schema": SCHEMA, "id": pack_id, "kind": "candidate", "name": name, "description": description,
        "components": checked, "cfg_patches": cfg_patches, "modules": modules, "content_sha256": digest,
        "base": {"BHumanCodeRelease": paths.OFFICIAL_UPSTREAM["BHumanCodeRelease"]},
        "provenance": provenance or {}, "status": "experimental", "created_at": util.now_iso(),
    }
    util.write_json(staging / "pack.json", manifest)
    staging.rename(target)
    return manifest


def verify(pack_id: str) -> dict:
    """Re-check stored files against their recorded hashes and contracts."""
    manifest = load(pack_id)
    report = {"pack_id": pack_id, "checks": {}, "components": {}}
    try:
        validate_bindings(manifest["components"], manifest.get("modules") or {})
        report["checks"]["consumer_bindings"] = True
    except PackError as exc:
        report["checks"]["consumer_bindings"] = False
        report["binding_error"] = str(exc)
    if manifest["kind"] != "baseline":
        digest = util.sha256_bytes(_canonical(manifest["components"], manifest.get("cfg_patches") or {},
                                              manifest.get("modules") or {}).encode())
        report["checks"]["content_identity"] = (digest == manifest.get("content_sha256")
                                                  and manifest.get("id") == pack_id and pack_id.endswith("-" + digest[:10]))
    for slot, entry in manifest["components"].items():
        if manifest["kind"] == "baseline":
            path = paths.BH_LOCAL / entry["official_file"]
        else:
            path = pack_dir(pack_id) / entry["file"]
        ok_hash = path.is_file() and util.sha256_file(path) == entry["sha256"]
        try:
            info = contracts.check(slot, path)
            ok_contract = info["contract"] == entry["contract"]
        except contracts.ContractError as exc:
            ok_contract, info = False, {"error": str(exc)}
        report["components"][slot] = {"path": str(path), "hash_ok": ok_hash, "contract_ok": ok_contract}
        report["checks"][f"{slot}_hash"] = ok_hash
        report["checks"][f"{slot}_contract"] = ok_contract
    report["status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    return report


def model_name_patches(manifest: dict) -> dict[str, dict[str, str]]:
    """cfg patches implied by the pack's network components (relative to NeuralNets/Walk/)."""
    if manifest["kind"] == "baseline":
        return {}
    patches: dict[str, dict[str, str]] = {}
    for slot in manifest["components"]:
        if slot in contracts.AUXILIARY_SLOTS:
            continue  # Inject into the new module's config, never into official WalkingEngine.
        contract = contracts.CONTRACTS[slot]
        patches.setdefault(contract.cfg_file, {})[contract.cfg_key] = f"forge/{manifest['id']}/{slot}.onnx"
    return patches


def effective_patches(manifest: dict) -> dict[str, dict[str, str]]:
    merged = {name: dict(changes) for name, changes in manifest.get("cfg_patches", {}).items()}
    for name, changes in model_name_patches(manifest).items():
        for key, value in changes.items():
            if key in merged.get(name, {}):
                raise PackError(f"{name}:{key} 同时被网络组件和配置修改指定")
            merged.setdefault(name, {})[key] = value
    return merged
