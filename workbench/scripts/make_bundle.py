"""Build an offline, inspectable .run bundle for the ARM64 Booster target.

The .run supports --info / --verify / --extract DIR only. It never installs,
never touches services or firmware, and never runs on the host. If the ARM64
ELF is missing, the bundle is named resources-only and says so in the manifest.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import config, util  # noqa: E402

ROOT = config.root()
BHLOCAL = config.rp("bhuman/local-k1-validation-20261019/bhuman-local")

HEADER = """#!/bin/sh
# Offline B-Human K1 ARM64 bundle. Inspectable only: --info/--verify/--extract DIR.
# This script never installs anything, never changes services, never touches firmware.
set -eu
PAYLOAD_LINE=$(awk '/^__PAYLOAD_BELOW__$/ {print NR + 1; exit 0; }' "$0")
mode="${1:---info}"
case "$mode" in
  --info)
    echo "bundle: $(basename "$0")"; echo "payload bytes: $(wc -c < "$0")"
    echo "run --verify to check sha256, --extract DIR to unpack"; exit 0 ;;
  --verify)
    actual=$(tail -n +$PAYLOAD_LINE "$0" | sha256sum | cut -d' ' -f1)
    expected="__PAYLOAD_SHA256__"
    [ "$actual" = "$expected" ] || { echo "payload sha256 不匹配" >&2; exit 3; }
    echo "payload sha256 OK"; exit 0 ;;
  --extract)
    dest="${2:?--extract 需要目标目录}"
    [ -e "$dest" ] && { echo "目标已存在，拒绝覆盖: $dest" >&2; exit 2; }
    actual=$(tail -n +$PAYLOAD_LINE "$0" | sha256sum | cut -d' ' -f1)
    [ "$actual" = "__PAYLOAD_SHA256__" ] || { echo "payload sha256 不匹配，拒绝解包" >&2; exit 3; }
    mkdir -p "$dest"
    tail -n +$PAYLOAD_LINE "$0" | tar -xzf - -C "$dest"
    echo "已解包到 $dest（未安装；验证见 manifest.json 与 verify_bundle.py）"; exit 0 ;;
  *) echo "用法: $0 [--info|--verify|--extract DIR]" >&2; exit 2 ;;
esac
__PAYLOAD_BELOW__
"""


def sha256(path: Path) -> str:
    return util.sha256_file(path)


def collect(kind: str):
    """Return list of (absolute src, arcname) for the bundle."""
    items = []

    def add(src, arc):
        src = Path(src)
        if src.is_file():
            items.append((src, arc))

    elf = BHLOCAL / "Build/Linux/Booster/Release/bhuman"
    if kind == "full":
        if not elf.is_file():
            raise SystemExit("ARM64 ELF 不存在，不能用 full 模式；请用 --mode resources")
        add(elf, "bin/bhuman")
    # Resolve real NEEDED recursively, using the bundled ARM libraries/sysroot.
    sdk_lib = BHLOCAL / "Util/BoosterRoboticsSDK/lib/LinuxArm64"
    ort = BHLOCAL / "Util/onnxruntime/lib/LinuxArm64"
    bc = BHLOCAL / "Util/Buildchain/Booster/lib"
    search = [sdk_lib, ort, BHLOCAL / "Util/librealsense2/lib/LinuxArm64",
              BHLOCAL / "Util/libduerwen/lib/LinuxArm64", bc]
    external = config.WB_DIR/'third_party/ubuntu-arm64-jammy'
    search += [external/'extracted/lib/aarch64-linux-gnu',external/'extracted/usr/lib/aarch64-linux-gnu']
    sonames = {}
    for folder in search:
        for candidate in sorted(folder.glob('*.so*')):
            if not candidate.is_file():
                continue
            dyn = subprocess.run(['readelf','-d',str(candidate)],capture_output=True,text=True,env=dict(os.environ,LC_ALL='C'))
            soname = re.search(r'Library soname:\s*\[([^\]]+)\]', dyn.stdout)
            if soname:
                sonames.setdefault(soname.group(1),candidate)
    closure, seen = [], set()
    queue = [(elf, "bin/bhuman")] if kind == "full" else []
    while queue:
        src, arc = queue.pop(0)
        if arc in seen:
            continue
        seen.add(arc)
        header = subprocess.check_output(["readelf", "-h", str(src)], text=True, env=dict(os.environ, LC_ALL="C"))
        if "AArch64" not in header:
            raise SystemExit("拒绝打包非 ARM64 依赖: " + str(src))
        dyn = subprocess.check_output(["readelf", "-d", str(src)], text=True, env=dict(os.environ, LC_ALL="C"))
        needed = re.findall(r"Shared library:\s*\[([^\]]+)\]", dyn)
        closure.append({"path": arc, "needed": needed, "source": str(src.resolve())})
        for name in needed:
            dep = next((d / name for d in search if (d / name).is_file()), None)
            if dep is None:
                dep = sonames.get(name)
            if dep is None:
                raise SystemExit("缺少目标依赖 " + name + " (required by " + str(src) + ")")
            dep_arc = ("sysroot/" if dep.parent == bc else "lib/") + name
            if dep_arc not in seen and all(a != dep_arc for _, a in items):
                add(dep, dep_arc)
                queue.append((dep, dep_arc))
    if kind == "full":
        add(bc / "ld-linux-aarch64.so.1", "sysroot/ld-linux-aarch64.so.1")
        add(ort / "libonnxruntime_providers_shared.so", "lib/libonnxruntime_providers_shared.so")
    # configs & models actually used by the robot target
    for sub in ["Config/NeuralNets", "Config/Robots", "Config/Locations", "Config/Scenarios", "Config/Sounds"]:
        base = BHLOCAL / sub
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and not any(part in ("TensorRTCache", "CoreMLCache", "Logs") for part in p.parts):
                    add(p, str(p.relative_to(BHLOCAL)))
    for p in sorted((BHLOCAL / "Config").iterdir()):
        if p.is_file() and p.suffix in (".cfg", ".def"):
            add(p, str(p.relative_to(BHLOCAL)))
    # licenses & attribution
    add(BHLOCAL / "License.md", "licenses/B-Human-License.md")
    add(BHLOCAL / "LicenseNaoDevils.txt", "licenses/LicenseNaoDevils.txt")
    sdk_lic = ROOT / "booster/booster_robotics_sdk/LICENSE"
    add(sdk_lic, "licenses/BoosterSDK-LICENSE")
    for part in ["onnxruntime", "BoosterRoboticsSDK", "librealsense2", "libduerwen", "CompiledNN2ONNX"]:
        folder = BHLOCAL / "Util" / part
        if folder.is_dir():
            for p in folder.iterdir():
                if p.is_file() and any(s in p.name.lower() for s in ("license", "notice", "copyright")):
                    add(p, "licenses/" + part + "/" + p.name)
    add(external/'manifest.json','licenses/ubuntu-arm64-package-manifest.json')
    for p in (external/'extracted/usr/share/doc').glob('*/copyright'):
        add(p,'licenses/ubuntu/'+p.parent.name+'/copyright')
    return items, closure


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出 .run 路径（必须不存在）")
    ap.add_argument("--mode", choices=["full", "resources"], default="full")
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        raise SystemExit("输出文件必须新建: " + str(out))
    if out.suffix != ".run":
        raise SystemExit("输出名必须以 .run 结尾，并明确为离线可检查产物")

    items, closure = collect(args.mode)
    manifest = {
        "created_at": util.now_local(),
        "mode": args.mode,
        "robot_connected": False,
        "auto_install": False,
        "target": {"arch": "aarch64", "interpreter": "/lib/ld-linux-aarch64.so.1",
                   "runpath": "/home/booster/Config"},
        "sdk_identity": {"actual_library": str(BHLOCAL / "Util/BoosterRoboticsSDK/lib/LinuxArm64/libbooster_robotics_sdk.a"),
                         "actual_library_sha256": sha256(BHLOCAL / "Util/BoosterRoboticsSDK/lib/LinuxArm64/libbooster_robotics_sdk.a"),
                         "external_sdk_reference_only": "fw-1.6 @324946e7c885de6cd6d37220eca64ed4e0f8d418; not substituted for bundled SDK",
                         "bhuman": "2e3374ba896da8288607f9a1881b876642fe18b8"},
        "dependency_closure": closure,
        "validation_scope": "offline integrity and static ARM dependencies; no hardware/runtime certification",
        "assumptions_and_gaps": [
            "固件兼容性未验证（booster_deploy 文档要求口径不一：>=1.7.2 或 >=1.4；B-Human 测试镜像 1.7.1）",
            "SDK/推理后端在真机上未执行验证（L5 未授权）",
            "libduerwen_wakeup 为语音唤醒库，按 NEEDED 带入；实际使用与否未裁剪",
            "sysroot 为离线依赖核验材料，不自动替换机器人系统的 glibc/加载器",
            "机器人身份、相机标定和现场配置尚未选定，本包不自动安装或直接启动",
        ],
        "files": [],
    }
    stage = Path(tempfile.mkdtemp(prefix=out.stem+"-stage-", dir=out.parent))
    for src, arc in items:
        dest = stage / arc
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        manifest["files"].append({"path": arc, "sha256": sha256(src),
                                  "size": src.stat().st_size})
    # embedded verifier + manifest
    shutil.copy2(Path(__file__).parent / "verify_bundle.py", stage / "verify_bundle.py")
    manifest["files"].append({"path": "verify_bundle.py", "sha256": sha256(stage / "verify_bundle.py"), "size": (stage / "verify_bundle.py").stat().st_size})
    util.write_json(stage / "manifest.json", manifest)
    util.write_json(out.parent / "bundle-manifest.json", manifest)
    checked = subprocess.run([sys.executable, "-I", "-B", str(stage / "verify_bundle.py"), str(stage)], capture_output=True, text=True)
    if checked.returncode:
        raise SystemExit("离线包核验失败: " + checked.stdout + checked.stderr)
    verification = json.loads(checked.stdout)
    payload = out.parent / (out.stem + ".payload.tar.gz")
    with tarfile.open(payload, "w:gz") as tar:
        tar.add(stage, arcname=".")
    payload_sha = sha256(payload)
    header = HEADER.replace("__PAYLOAD_SHA256__", payload_sha)
    with open(out, "wb") as fh:
        fh.write(header.encode())
        with open(payload, "rb") as pf:
            shutil.copyfileobj(pf, fh)
    os.chmod(out, 0o755)
    verification.update({"bundle": str(out), "bundle_sha256": sha256(out), "scope": manifest["validation_scope"]})
    subprocess.run(["bash", str(out), "--verify"], check=True, capture_output=True)
    util.write_json(out.parent / "bundle-verification.json", verification)
    shutil.rmtree(stage)
    payload.unlink()
    print(json.dumps({"bundle": str(out), "mode": args.mode, "files": len(items),
                      "payload_sha256": payload_sha, "size": out.stat().st_size}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
