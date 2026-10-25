"""Build farm: source variants of the B-Human code and their SimRobot / Booster builds.

A variant is ``bhuman-local`` copied (Src, Make, Config, Install, licenses) plus an ordered
patch stack. ``Util/`` (third-party: Booster sysroot and SDK, ONNX Runtime, SimRobot
sources...) is linked read-only per top-level entry; an entry touched by a patch is copied
first. CMake's OUTPUT_PREFIX is the variant root, so products land in
``variants/<name>/Build`` and never overwrite the validated bhuman-local programs.

Targets
  simrobot  x86_64 SimRobot + SimulatedRobot controller (simulation)
  booster   AArch64 robot program ``bhuman`` linked with the Booster Robotics SDK,
            FastDDS and ONNX Runtime, via clang --target=aarch64-linux-gnu and the
            bundled sysroot. Never deployed: no deploy/install target is invoked.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import paths, source_identity, util

COPY_ENTRIES = ("Src", "Make", "Config", "Install", "License.md", "LicenseNaoDevils.txt", "README.md", "CITATION.cff")
# Large third-party trees that never include B-Human sources through relative paths. They are
# linked read-only; every other Util entry is copied (e.g. Util/X5Camera includes
# ../../../Src/..., which must resolve inside the variant, not inside bhuman-local).
LINKABLE_UTIL = ("SimRobot", "BoosterRoboticsSDK", "Buildchain", "onnxruntime", "hdf5", "fftw-3.3", "flite",
                 "gtest", "dot", "librealsense2")
TARGETS = {
    "simrobot": {"label": "SimRobot 仿真程序 (x86_64)", "cmake": [], "build": ["SimRobot", "SimulatedRobot", "SimRobotCore3"],
                 "products": ["Build/Linux/SimRobot/{kind}/SimRobot", "Build/Linux/SimRobot/{kind}/libSimulatedRobot.so",
                              "Build/Linux/SimRobot/{kind}/libSimRobotCore3.so"]},
    "booster": {"label": "Booster 机器人程序 (AArch64 + Booster SDK)", "cmake": ["-DBUILD_BOOSTER=ON"],
                "build": ["Booster"], "products": ["Build/Linux/Booster/{kind}/bhuman"]},
}


class BuildError(RuntimeError):
    pass


def variant_root(name: str) -> Path:
    return paths.VARIANTS / util.safe_name(name)


def list_variants() -> list[dict]:
    out = []
    for path in sorted(paths.VARIANTS.glob("*/variant.json")):
        data = util.read_json(path)
        if data:
            data["builds"] = {p.parent.name: util.read_json(p) for p in sorted(path.parent.glob("_builds/*/build.json"))}
            out.append(data)
    return out


def _touched_util_entries(patch_files: list[Path]) -> set[str]:
    touched = set()
    for patch in patch_files:
        for line in patch.read_text(errors="replace").splitlines():
            match = re.match(r"^(?:\+\+\+|---) [ab]/Util/([^/\s]+)", line)
            if match:
                touched.add(match.group(1))
    return touched


def _references_src(directory: Path) -> bool:
    """True if a source file refers back into the B-Human tree via ../Src."""
    pattern = re.compile(rb"\.\./(?:\.\./)*Src/")
    for path in directory.rglob("*"):
        if path.suffix in (".h", ".hpp", ".hh", ".c", ".cc", ".cpp", ".cmake", ".txt") and path.is_file():
            try:
                if pattern.search(path.read_bytes()):
                    return True
            except OSError:
                continue
    return False


def create_variant(name: str, patches: list[str] | None = None, description: str = "") -> dict:
    root = variant_root(name)
    if root.exists():
        raise BuildError(f"源码变体 {root.name} 已存在；变体不可变，请换名字")
    patch_files = [Path(p).resolve() for p in (patches or [])]
    for patch in patch_files:
        if not patch.is_file():
            raise BuildError(f"补丁不存在: {patch}")
    staging = root.with_name(root.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for entry in COPY_ENTRIES:
        source = paths.BH_LOCAL / entry
        if source.is_dir():
            shutil.copytree(source, staging / entry, symlinks=True)
        elif source.is_file():
            shutil.copy2(source, staging / entry)
    touched = _touched_util_entries(patch_files)
    (staging / "Util").mkdir()
    linked = []
    for entry in sorted((paths.BH_LOCAL / "Util").iterdir()):
        if entry.name in LINKABLE_UTIL and entry.name not in touched and not _references_src(entry):
            (staging / "Util" / entry.name).symlink_to(entry)
            linked.append(entry.name)
        elif entry.is_dir():
            shutil.copytree(entry, staging / "Util" / entry.name, symlinks=True)
        else:
            shutil.copy2(entry, staging / "Util" / entry.name)
    applied = []
    # The variant lives inside the Robocup git work tree; without a ceiling git would resolve
    # patch paths against that repository and silently skip them.
    git_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(staging.parent))
    for patch in patch_files:
        targets = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", patch.read_text(errors="replace"), re.M)))
        before = {t: util.sha256_file(staging / t) if (staging / t).is_file() else None for t in targets}
        check = subprocess.run(["git", "apply", "--check", "-p1", str(patch)], cwd=staging, capture_output=True,
                               text=True, env=git_env)
        if check.returncode != 0 or not targets:
            shutil.rmtree(staging)
            raise BuildError(f"补丁无法干净应用 {patch.name}: {check.stderr.strip()[:400] or '补丁中没有文件'}")
        subprocess.run(["git", "apply", "-p1", str(patch)], cwd=staging, check=True, env=git_env)
        unchanged = [t for t in targets if (util.sha256_file(staging / t) if (staging / t).is_file() else None) == before[t]]
        if unchanged:
            shutil.rmtree(staging)
            raise BuildError(f"补丁 {patch.name} 应用后这些文件没有变化: {unchanged[:5]}")
        applied.append({"file": str(patch), "sha256": util.sha256_file(patch), "files": targets,
                        "file_hashes": {t: {"before": before[t], "after": util.sha256_file(staging / t)
                                          if (staging / t).is_file() else None} for t in targets}})
    source_manifest = source_identity.source_manifest(staging)
    base_manifest = source_identity.source_manifest(paths.BH_LOCAL)
    changed = sorted(k for k in set(source_manifest) | set(base_manifest) if source_manifest.get(k) != base_manifest.get(k))
    data = {"schema": "forge.variant/2", "name": root.name, "description": description, "created_at": util.now_iso(),
            "base": str(paths.BH_LOCAL), "base_upstream": paths.OFFICIAL_UPSTREAM["BHumanCodeRelease"],
            "patches": applied, "util_linked": linked, "util_copied": sorted(touched),
            "source_sha256": util.manifest_digest(source_manifest), "files_changed_vs_base": changed,
            "source_entries": list(source_identity.SOURCE_ENTRIES)}
    util.write_json(staging / "variant.json", data)
    staging.rename(root)
    return data


def _toolchain_identity() -> dict:
    out = {}
    for name, argv in (("cmake", ["cmake", "--version"]), ("ninja", ["ninja", "--version"]),
                       ("clang++", ["clang++", "--version"]), ("c++", ["c++", "--version"])):
        try:
            text = subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            out[name] = text[0] if text else ""
        except OSError:
            out[name] = None
    return out


def build(name: str, target: str = "booster", kind: str = "Release", jobs: int = 12, on_line=None) -> dict:
    if target not in TARGETS:
        raise BuildError(f"未知目标 {target}")
    if kind not in ("Release", "Develop"):
        raise BuildError("kind 必须是 Release 或 Develop")
    if not 1 <= jobs <= 32:
        raise BuildError("并行数需 1..32")
    root = variant_root(name)
    variant = util.read_json(root / "variant.json")
    if not variant:
        raise BuildError(f"源码变体不存在: {name}")
    identity = source_identity.source_manifest(root, legacy=variant.get("schema") != "forge.variant/2")
    if util.manifest_digest(identity) != variant["source_sha256"]:
        raise BuildError("源码变体指纹变化，拒绝把当前编译归于旧变体")
    spec = TARGETS[target]
    build_dir = root / "_builds" / f"{target}-{kind}"
    log_dir = paths.RUNS / "builds" / f"{util.stamp()}_{root.name}_{target}-{kind}"
    log_dir.mkdir(parents=True)
    env = dict(os.environ, CCACHE_DISABLE="1")
    configure = ["cmake", "-S", str(root / "Make/CMake"), "-B", str(build_dir), "-G", "Ninja",
                 f"-DCMAKE_BUILD_TYPE={kind}", *spec["cmake"]]
    compile_ = ["cmake", "--build", str(build_dir), "--parallel", str(jobs), "--target", *spec["build"]]
    receipt = {"schema": "forge.build/2", "variant": root.name, "variant_source_sha256": variant["source_sha256"],
               "variant_source_schema": variant.get("schema"), "target": target, "kind": kind, "configure": configure, "build": compile_, "jobs": jobs,
               "toolchain": _toolchain_identity(), "started_at": util.now_iso(), "deploy_invoked": False}
    status, steps = "PASS", []
    with (log_dir / "console.log").open("w") as log:
        for step_name, command in (("configure", configure), ("build", compile_)):
            process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors="replace", start_new_session=True)
            for line in process.stdout:
                log.write(line)
                if on_line:
                    on_line(line)
            code = process.wait()
            steps.append({"step": step_name, "exit_code": code})
            if code != 0:
                status = "FAIL"
                break
    products = {}
    for template in spec["products"]:
        product = root / template.format(kind=kind)
        products[template.format(kind=kind)] = {"exists": product.is_file(),
                                                "sha256": util.sha256_file(product) if product.is_file() else None,
                                                "size": product.stat().st_size if product.is_file() else None}
    receipt.update(steps=steps, products=products, ended_at=util.now_iso(), log=str(log_dir / "console.log"))
    if status == "PASS" and not all(p["exists"] for p in products.values()):
        status = "FAIL"
    if status == "PASS" and target == "booster":
        receipt["elf"] = verify_arm_elf(root / spec["products"][0].format(kind=kind))
        status = "PASS" if receipt["elf"]["status"] == "PASS" else "FAIL"
    receipt["status"] = status
    util.write_json(build_dir / "build.json", receipt)
    util.write_json(log_dir / "build.json", receipt)
    return receipt


def verify_arm_elf(path: Path) -> dict:
    """Static checks of the cross-compiled robot program. Never executes it."""
    checks, details = {}, {}
    c_env = dict(os.environ, LC_ALL="C", LANG="C")

    def tool(*argv):
        return subprocess.run(list(argv), capture_output=True, text=True, env=c_env).stdout

    file_out = tool("file", "-b", str(path)).strip()
    header = tool("readelf", "-h", str(path))
    program = tool("readelf", "-l", str(path))
    dynamic = tool("readelf", "-d", str(path))
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dynamic)
    interpreter = re.search(r"Requesting program interpreter: ([^\]]+)\]", program)
    details.update(file=file_out, needed=needed, interpreter=interpreter.group(1) if interpreter else None)
    checks["aarch64"] = "ARM aarch64" in file_out and "AArch64" in header
    checks["interpreter_aarch64"] = bool(interpreter) and "ld-linux-aarch64" in interpreter.group(1)
    checks["dds_runtime_linked"] = any("fastrtps" in n for n in needed) and any("fastcdr" in n for n in needed)
    checks["onnxruntime_linked"] = any("onnxruntime" in n for n in needed)
    # The SDK is a static archive; prove that its client code was linked in.
    strings = tool("strings", "-n", "8", str(path))
    sdk_markers = sorted({m for m in re.findall(r"rt/[A-Za-z_0-9/]+", strings)})[:60]
    details["sdk_topic_markers"] = sdk_markers
    checks["booster_sdk_linked"] = ("rt/low_state" in sdk_markers and "rt/joint_ctrl" in sdk_markers
                                    and "booster_interface::msg::dds_::LowState_" in strings)
    details["sha256"] = util.sha256_file(path)
    details["size"] = path.stat().st_size
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "details": details,
            "scope": "static ELF/linkage evidence only; target firmware, DDS ABI on the robot and runtime are unverified"}
