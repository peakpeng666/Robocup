"""Pinned review of opt-in simulator extensions; metadata cannot grant compatibility."""
from __future__ import annotations

import os
from pathlib import Path

from . import util
from .native_simulator_review import NATIVE_IO_EXTENSIONS

SOURCE_ENTRIES = ("Src", "Make", "Config", "Install", "Util", "License.md", "LicenseNaoDevils.txt", "README.md", "CITATION.cff")
# Review: full actuator default-off branch and unchanged original servo body;
# tests/test_full_actuator.py independently exercises the generated native code.
# This literal allowlist is deliberately not loaded from variant/patch metadata.
REVIEWED_SIMULATOR_EXTENSIONS = {'a17005f9535741f48cb299fb421fa9aff7013b4aa7e7a3a9ca0f9cd085893f5e': {'name': 'full-actuator-transport-v1', 'files': {'Util/SimRobot/Src/SimRobotCore3/FullActuatorCore.h': {'before': None, 'after': '82470819fe4dce8b82503e343199c0339f7e99d2317ee5d6f51a679b5e87e798'}, 'Src/Representations/Infrastructure/FullActuatorCommand.h': {'before': None, 'after': '8f77489ea05965b8168a1f6a522fb694099ff1a99a1d276ea4d199f63d397825'}, 'Src/Representations/Infrastructure/JointRequest.h': {'before': 'fcbc3674748a5edc171e0459942c2d8a2a113a986444717fe37e106d241edd0f', 'after': '24057b40b039f6ad6232126df198f986385fb93fa2abcf9cf80fa754e1b165d4'}, 'Src/Representations/Infrastructure/SensorData/JointSensorData.h': {'before': '06719ce466b7ad5ef0ac9d423221a687ce1a9bba2c379ef7dd379ee3729b4d73', 'after': 'd756323a7946a5f0417e01fcf4648afa2290eff0defa5fd32f3369b7c428726d'}, 'Util/SimRobot/Src/SimRobotCore3/SimRobotCore3.h': {'before': '79b8b7a0bb5f561451090cdca87902a7d6ee17cafef0ea6c67555227a5b53b70', 'after': 'd5ea682dab55e3889bb668f48168b7695ac97203152d08430f87ee3553c040c5'}, 'Util/SimRobot/Src/SimRobotCore3/Simulation/Motors/ServoMotor.h': {'before': 'ff0319331e6e29ad05f061755927ec16989464eb0ecd239b98753f13fd2c1919', 'after': '397874272da10713133f89f97261f20675ed2a8a6be52bb5ef8577254cf9ecac'}, 'Util/SimRobot/Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp': {'before': 'd5cffdfb8002f3ae499c8134d0775527e3a3b625d3d255381a023059af0fd589', 'after': 'dbb1a487e225456ea85b6e1c96245278f7c2cf0b57d7de79125cfe65ebf19df8'}, 'Src/Libs/SimulatedRobot/SimulatedRobot3D.h': {'before': '5f54261dad6f33cf01360015ee13eebadb49b4746ebfdd149147c49087b10ae3', 'after': '672d9171cc319127ae112e13ecd311f0989e1a104ba53fda707e6c4f62968367'}, 'Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp': {'before': 'b48588a48241e866fa80a2b481477d5a094fd86a9d1c44c742407423d7d212a7', 'after': '4ff0adc0cb1d0c9ac9fccf14424bb8fe49d981d01d6331ff91330f86e9828fff'}}}}


REVIEWED_SIMULATOR_EXTENSIONS.update(NATIVE_IO_EXTENSIONS)


def source_manifest(root: Path, *, legacy=False) -> dict:
    """Hash actual file contents, following dependency links and detecting cycles."""
    root = Path(root)
    if legacy:
        return {f"{entry}/{p}": h for entry in ("Src", "Make", "Config")
                for p, h in util.tree_manifest(root / entry).items()}
    result = {}

    def visit(path, parents):
        real = path.resolve()
        if path.is_dir():
            if real in parents:
                result[path.relative_to(root).as_posix()] = "cycle-link:" + os.readlink(path)
                return
            for child in sorted(path.iterdir()):
                visit(child, parents | {real})
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = util.sha256_file(path)
        elif path.is_symlink():
            # Retain dangling links in identity rather than silently omit them.
            result[path.relative_to(root).as_posix()] = "symlink:" + os.readlink(path)

    for entry in SOURCE_ENTRIES:
        visit(root / entry, set())
    return result


def classify(source: Path, base: Path, variant: dict) -> dict:
    current, original = source_manifest(source), source_manifest(base)
    changed = sorted(p for p in current.keys() | original.keys() if current.get(p) != original.get(p))
    modified = [p for p in changed if p in original]
    modern = variant.get("schema") == "forge.variant/2"
    recorded = current if modern else source_manifest(source, legacy=True)
    consistent = util.manifest_digest(recorded) == variant.get("source_sha256")
    util_unchanged = not any(p.startswith("Util/") for p in changed)
    additive = not modified and consistent and (modern or util_unchanged)
    reviewed = []
    approved_files = set()
    for patch in variant.get("patches", []):
        approval = REVIEWED_SIMULATOR_EXTENSIONS.get(patch.get("sha256"))
        if not approval or not modern:
            continue
        expected = approval["files"]
        file_path = Path(patch.get("file", ""))
        if (not file_path.is_file() or util.sha256_file(file_path) != patch["sha256"]
                or set(patch.get("files", [])) != set(expected)
                or patch.get("file_hashes") != expected):
            continue
        if all(original.get(p) == pair["before"] and current.get(p) == pair["after"]
               for p, pair in expected.items()):
            reviewed.append({"name": approval["name"], "patch_sha256": patch["sha256"]})
            approved_files.update(expected)
    # Make/Python contains source-directory symlinks. The manifest follows them
    # so their contents are protected too; approve only aliases of the exact
    # reviewed file on BOTH source and original sides, not matching hashes alone.
    for alias in modified:
        if any((source / alias).resolve() == (source / approved).resolve()
               and (base / alias).resolve() == (base / approved).resolve()
               for approved in tuple(approved_files)):
            approved_files.add(alias)
    compatible = additive or (consistent and bool(reviewed) and not (set(modified) - approved_files))
    return {"kind": "shared_simulator_extension" if reviewed else "variant", "name": variant["name"],
            "additive": additive, "baseline_compatible": compatible, "changed": changed,
            "manifest_matches_source": consistent, "modified_existing": modified, "identical": not changed,
            "source_schema": variant.get("schema"), "reviewed_extensions": reviewed,
            "baseline_scope": "official default servo/motion path; shared binaries rebuilt" if reviewed else
                              "official source with additive candidate modules"}


def build_identity(source: Path) -> dict:
    """New variants must bind all three runtime products to their source digest."""
    source = Path(source)
    variant = util.read_json(source / "variant.json") or {}
    if variant.get("schema") != "forge.variant/2":
        return {"ok": True, "scope": "legacy build; runtime executable and libraries checked separately"}
    receipt = util.read_json(source / "_builds/simrobot-Release/build.json") or {}
    checks = {"completed": receipt.get("status") == "PASS" and receipt.get("schema") == "forge.build/2",
              "source": receipt.get("variant_source_sha256") == variant.get("source_sha256")}
    for name in ("SimRobot", "libSimulatedRobot.so", "libSimRobotCore3.so"):
        relative = "Build/Linux/SimRobot/Release/" + name
        path = source / relative
        checks[name] = bool(path.is_file() and receipt.get("products", {}).get(relative, {}).get("sha256")
                            == util.sha256_file(path))
    return {"ok": all(checks.values()), "checks": checks, "scope": "source-bound three-product build"}
