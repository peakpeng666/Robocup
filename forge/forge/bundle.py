"""Offline robot bundle: Booster AArch64 program + B-Human Config + a motion-pack scenario.

Deployment *preparation* only: the archive contains files, a manifest with hashes and a
self-check script. It contains no installer, never touches a robot and is not a claim that
the program runs on a particular robot firmware.

The pack is applied as a scenario ``Forge_<pack>`` whose files are patched from what a real
K1 resolves (``Config/Robots/Default/K1``), not from the simulation-only
``Config/Robots/SimulatedK1`` profile, because the two differ (e.g. walking speed limits).
Selecting that scenario on a robot is an explicit, separate deployment decision.
"""
from __future__ import annotations

import json
import shutil
import tarfile

from . import bhconfig, builds, packs, paths, util

VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""Re-hash every file of this bundle against manifest.json. Prints PASS/FAIL; changes nothing."""
import hashlib, json, sys
from pathlib import Path
root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
bad = []
for rel, digest in manifest["files"].items():
    path = root / rel
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        bad.append(rel)
print("PASS" if not bad else "FAIL " + ", ".join(bad[:20]))
sys.exit(1 if bad else 0)
'''


class BundleError(RuntimeError):
    pass


def make(variant: str, pack_id: str) -> dict:
    pack = packs.load(pack_id)
    if "BoosterNativeMotionProvider" in (pack.get("modules") or {}):
        raise BundleError("原厂运动包当前只有本地仿真后端；SDK 真机后端尚未完成，拒绝生成会误选 B-Human 运控的离线包")
    root = builds.variant_root(variant)
    receipt = util.read_json(root / "_builds/booster-Release/build.json")
    if not receipt or receipt.get("status") != "PASS":
        raise BundleError(f"变体 {variant} 没有通过的 Booster Release 构建")
    elf = root / "Build/Linux/Booster/Release/bhuman"
    if util.sha256_file(elf) != receipt["products"]["Build/Linux/Booster/Release/bhuman"]["sha256"]:
        raise BundleError("Booster 程序与构建记录不一致（构建后被改动？）")
    if packs.verify(pack_id)["status"] != "PASS":
        raise BundleError("运控包校验失败")
    scenario = f"Forge_{util.safe_name(pack_id, 40).replace('-', '_')}"
    stage = paths.RUNS / "bundles" / f"{util.stamp()}_{util.safe_name(variant, 16)}_{util.safe_name(pack_id, 32)}"
    tree = stage / "bhuman-k1-offline"
    (tree / "Build").mkdir(parents=True)
    shutil.copy2(elf, tree / "Build/bhuman")
    shutil.copytree(root / "Config", tree / "Config", symlinks=False,
                    ignore=shutil.ignore_patterns("Scenes", "TensorRTCache"))
    patches = packs.effective_patches(pack)
    overlay = tree / "Config/Scenarios" / scenario / "K1"
    overlay.mkdir(parents=True)
    written = {}
    for name, changes in patches.items():
        base = bhconfig.resolve(tree / "Config", name, robot_name="Default", robot_type="K1")
        if base is None:
            raise BundleError(f"{name} 在真机配置搜索路径中不存在")
        (overlay / name).write_text(bhconfig.CfgDocument.load(base).patched(changes), encoding="utf-8")
        written[name] = {"based_on": base.relative_to(tree / "Config").as_posix()}
    if pack["kind"] != "baseline":
        nn_dir = tree / "Config/NeuralNets/Walk/forge" / pack["id"]
        nn_dir.mkdir(parents=True)
        for slot, entry in pack["components"].items():
            shutil.copy2(packs.pack_dir(pack["id"]) / entry["file"], nn_dir / f"{slot}.onnx")
    for name in ("License.md", "LicenseNaoDevils.txt"):
        if (root / name).is_file():
            shutil.copy2(root / name, tree / name)
    (tree / "verify.py").write_text(VERIFY_SCRIPT)
    files = {p.relative_to(tree).as_posix(): util.sha256_file(p) for p in sorted(tree.rglob("*")) if p.is_file()}
    manifest = {
        "schema": "forge.offline-bundle/1", "created_at": util.now_iso(), "variant": variant,
        "variant_source_sha256": util.read_json(root / "variant.json")["source_sha256"],
        "program": {"path": "Build/bhuman", "sha256": files["Build/bhuman"], "elf": receipt.get("elf")},
        "pack": {"id": pack["id"], "kind": pack["kind"], "content_sha256": pack.get("content_sha256"),
                 "provenance": pack.get("provenance", {})},
        "scenario": scenario, "scenario_files": written,
        "activation_note": f"在机器人 settings.cfg 中选择 scenario = {scenario} 才会生效；本包不执行任何安装或部署。",
        "not_verified": ["目标机器人固件/镜像兼容性", "DDS ABI 与机器人服务", "CompiledNN/ONNX Runtime 在 AArch64 上的数值", "真机闭环"],
        "robot_connected": False,
        "files": {k: v for k, v in files.items()},
    }
    (tree / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    archive = stage / "bhuman-k1-offline.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(tree, arcname="bhuman-k1-offline")
    manifest_out = dict(manifest)
    manifest_out.pop("files")
    manifest_out.update(archive=str(archive), archive_sha256=util.sha256_file(archive), file_count=len(files),
                        size_mb=round(archive.stat().st_size / 1e6, 1))
    util.write_json(stage / "bundle.json", manifest_out)
    return manifest_out
