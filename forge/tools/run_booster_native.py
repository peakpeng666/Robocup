#!/usr/bin/env python3
"""Run the retained ARM controller only inside an isolated local simulator sandbox.

This never runs an archive, installer, service, or robot startup script. The
controller's argc=2 CopyRobotConfig path is deliberately excluded. At present
the supported probes are dependency resolution and help; a closed-loop launch
requires the separately verified simulator interposer and transport.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime

FORGE = Path(__file__).resolve().parents[1]
VENDOR = FORGE / "third_party/booster-k1-1.6.0.10/selected-payload/booster"
NATIVE = FORGE / "third_party/booster-native-arm64"
QEMU = FORGE / "third_party/qemu-user-static-local/root/usr/bin/qemu-aarch64-static"
LIB_PATH = "/vendor/lib/motion:/vendor/frame_work/lib:/vendor-extra/booster/lib:/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sandbox_command(work: Path, arguments: list[str], *, preload: Path | None = None,
                    controller_graph: bool = False, rpc: Path | None = None,
                    physics: Path | None = None) -> list[str]:
    """No host filesystem, network, IPC namespace, shell, or hardware exposure."""
    for path in (NATIVE / "rootfs", VENDOR, QEMU, work):
        if not path.exists():
            raise FileNotFoundError(path)
    cmd = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--clearenv", "--ro-bind", str(NATIVE / "rootfs"), "/",
        "--ro-bind", str(VENDOR), "/vendor",
        "--ro-bind", str(NATIVE / "vendor-extra"), "/vendor-extra",
        "--ro-bind", str(QEMU), "/qemu",
        "--ro-bind", str(work / "controller"), "/controller",
        "--bind", str(work / "output"), "/output",
        "--tmpfs", "/tmp", "--tmpfs", "/run", "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/bin", "--tmpfs", "/sbin",
        "--tmpfs", "/usr/bin", "--tmpfs", "/usr/sbin",
        "--setenv", "HOME", "/output", "--setenv", "TMPDIR", "/tmp",
        "--setenv", "LC_ALL", "C", "--setenv", "OMP_NUM_THREADS", "1",
        "--setenv", "OPENBLAS_NUM_THREADS", "1",
    ]
    if controller_graph:
        if preload is None or not (work / "controller/booster/Gait/forge_sim.lua").is_file():
            raise ValueError("a graph run requires an explicit simulation config and IO interposer")
        cmd += ["--ro-bind", str(work / "controller/booster"), "/opt/booster",
                "--chdir", "/opt/booster/Gait",
                "--setenv", "FORGE_BOOSTER_SOCKET", "/output/firmware.sock",
                "--setenv", "FORGE_BOOSTER_RS_LIBRARY", "/vendor/lib/motion/librs_sdk_interface.so"]
        if rpc is not None:
            cmd += ["--setenv", "FORGE_BOOSTER_RPC_LIBRARY", "/vendor/lib/motion/librsm_modules.so"]
    else:
        cmd += ["--chdir", "/output"]
    if preload is not None:
        cmd += ["--ro-bind", str(preload.resolve(strict=True)), "/controller/interposer.so"]
    if rpc is not None:
        if preload is None:
            raise ValueError("RPC extension requires the strict IO interposer")
        if sha256(VENDOR / 'lib/motion/librsm_modules.so') != '62ffcc60cd7b11ca15e8d3e9cdced695f01e1b97e0c88a07ea5d0d12b76d72a0':
            raise ValueError('RPC/visual-kick calling convention is only audited for the pinned 1.6.0.10 module')
        (work / "controller/rpc.so").touch()
        cmd += ["--ro-bind", str(rpc.resolve(strict=True)), "/controller/rpc.so",
                "--setenv", "FORGE_BOOSTER_RPC_REQUIRED", "1"]
    if physics is not None:
        if preload is None or not controller_graph:
            raise ValueError("serial physics requires an explicit controller graph and IO interposer")
        (work / "controller/physics.so").touch()
        cmd += ["--ro-bind", str(physics.resolve(strict=True)), "/controller/physics.so",
                "--setenv", "FORGE_BOOSTER_SERIAL_IO", "1"]
    cmd += ["/qemu", "-L", "/", "-E", f"LD_LIBRARY_PATH={LIB_PATH}"]
    if preload is not None:
        cmd += ["-E", "LD_PRELOAD=/controller/interposer.so" + (":/controller/rpc.so" if rpc else "")
                + (":/controller/physics.so" if physics else "")]
    return cmd + arguments


def new_work(label: str) -> Path:
    work = FORGE / "runs/native-controller" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + label)
    (work / "controller").mkdir(parents=True, exist_ok=False)
    (work / "output").mkdir()
    shutil.copyfile(VENDOR / "bin/mck", work / "controller/mck")
    (work / "controller/mck").chmod(0o755)
    (work / "controller/interposer.so").touch()
    return work


def prepare_graph(work: Path) -> None:
    """Retain the original parallel graph; only redirect sandbox-local paths."""
    target = work / "controller/booster"
    gait = target / "Gait"
    (gait / "configs").mkdir(parents=True)
    shutil.copytree(VENDOR / "Gait/configs/K1", gait / "configs/K1")
    (gait / "lib").symlink_to("/vendor/lib/motion")
    (target / "lib").symlink_to("/vendor-extra/booster/lib")
    (target / "frame_work").symlink_to("/vendor/frame_work")
    (target / "configs").mkdir()
    (target / "configs/K1").symlink_to("/opt/booster/Gait/configs/K1")
    shutil.copyfile(NATIVE / "vendor-extra/booster/configs/common/system_settings_config.yaml",
                    target / "configs/system_settings_config.yaml")
    shutil.copyfile(NATIVE / "vendor-extra/booster/version.txt", target / "version.txt")
    # This is explicit virtual identity, never copied from a connected robot.
    (target / "robot_info.txt").write_text("Name: Forge Local Simulation\nModel: Booster K1\n"
        "Model Version: 1.0.2\nPlatform: Single\nEdition: K1 Professional\nRegion: Global\n")
    (gait / "robot_info.txt").symlink_to("/opt/booster/robot_info.txt")
    (gait / "version.txt").symlink_to("/opt/booster/version.txt")
    (gait / "forge_sim.lua").write_text('''-- Original 1.6 controller graph with isolated virtual RsSdk IO.
-- is_real_bot selects the native parallel graph; the IO methods are intercepted
-- by the mandatory local simulator bridge, inside a no-hardware sandbox.
package.path = package.path .. ";/opt/booster/Gait/configs/K1/?.lua"
local result = dofile("/opt/booster/Gait/configs/K1/config.lua")
return result
''')
    manifest = {str(p.relative_to(target)): sha256(p) for p in sorted(target.rglob("*"))
                if p.is_file() and not p.is_symlink()}
    (work / "graph-manifest.json").write_text(json.dumps({
        "schema": "forge.native-graph-stage/1", "domain": "original_parallel_motors",
        "isolation": "mandatory interposer; all network/IPC namespaces isolated; no hardware devices or shells",
        "files": manifest,
    }, indent=2) + "\n")


def probe(kind: str) -> dict:
    work = new_work(kind)
    arguments = (["/lib/ld-linux-aarch64.so.1", "--list", "/controller/mck"]
                 if kind == "dependencies" else ["/controller/mck", "--help"])
    cmd = sandbox_command(work, arguments)
    with (work / "probe.log").open("w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=30)
    report = {
        "schema": "forge.native-controller-probe/1", "kind": kind,
        "returncode": result.returncode, "work": str(work), "command": cmd,
        "controller_sha256": sha256(work / "controller/mck"), "qemu_sha256": sha256(QEMU),
        "source_controller_sha256": sha256(VENDOR / "bin/mck"),
        "scope": "isolated local probe; no controller graph, robot, firmware script, or service started",
    }
    (work / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", choices=("dependencies", "help"))
    args = parser.parse_args()
    print(json.dumps(probe(args.probe), indent=2))
