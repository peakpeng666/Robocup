#!/usr/bin/env python3
"""Cross-compile the simulation IO bridge; never execute a vendor program."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def build(output: Path | None = None, headers: Path | None = None, rootfs: Path | None = None,
          *, application_feedback: bool = False) -> Path:
    forge = Path(__file__).resolve().parents[1]
    repo = forge.parent
    headers = headers or repo / "bhuman/local-k1-validation-20261019/bhuman-local/Util/Buildchain/Booster"
    rootfs = rootfs or forge / "third_party/booster-native-arm64/rootfs"
    compiler = shutil.which("clang++")
    linker = shutil.which("mold")
    if not compiler or not linker:
        raise RuntimeError("clang++ and the mold cross-architecture linker are required")
    source = forge / "native/booster_fw16_interposer.cpp"
    wire = source.with_name("booster_fw16_wire.h")
    libc = rootfs / "lib/aarch64-linux-gnu/libc.so.6"
    for required in (headers / "include/stdint.h", libc, source, wire):
        if not required.is_file():
            raise FileNotFoundError(required)
    if output is None:
        output = forge / "runs/native-controller" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_interposer-build")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    obj = output / "booster_fw16_interposer.o"
    library = output / "libforge_booster_fw16_io.so"
    commands = [
        [compiler, "--target=aarch64-linux-gnu", "--sysroot=" + str(headers),
         "-isystem", str(headers / "include"),
         "-isystem", str(headers / "include/aarch64-linux-gnu"),
         "-std=c++17", "-O2", "-g", "-fPIC",
         "-fno-exceptions", "-fno-rtti", "-Wall", "-Wextra", "-Werror", "-c", str(source), "-o", str(obj)],
        [linker, "-m", "aarch64linux", "-shared", "--no-undefined", "-z", "now", "-z", "relro",
         "-soname", library.name, "-o", str(library), str(obj), str(libc)],
    ]
    application = forge / 'native/booster_fw16_application.cpp'
    publisher = forge / 'third_party/booster-k1-1.6.0.10/selected-payload/booster/lib/motion/libmodule_motion_state_publisher.so'
    publisher_sha256 = 'a9a63ffc86b9c65ef1882c300e25b59c4aa082278f353b4d9f7a59cc58c2b092'
    if application_feedback:
        if hashlib.sha256(publisher.read_bytes()).hexdigest() != publisher_sha256:
            raise RuntimeError('original publisher no longer matches reviewed DWARF/accessor ABI')
        app_obj = output / 'application.o'
        application_command = [compiler, '--target=aarch64-linux-gnu', '--sysroot=' + str(headers), '-nostdinc++']
        for include in [headers / 'include/c++/11', headers / 'include/aarch64-linux-gnu/c++/11',
                        headers / 'include', headers / 'include/aarch64-linux-gnu']:
            application_command += ['-isystem', str(include)]
        application_command += ['-std=c++17', '-O2', '-g', '-fPIC', '-fno-rtti', '-Wall', '-Wextra', '-Werror',
                                '-c', str(application), '-o', str(app_obj)]
        commands.insert(1, application_command)
        commands[-1] += [str(app_obj), str(rootfs / 'usr/lib/aarch64-linux-gnu/libstdc++.so.6.0.30'),
                         str(rootfs / 'lib/aarch64-linux-gnu/libgcc_s.so.1'), str(rootfs / 'lib/aarch64-linux-gnu/libm.so.6'),
                         '--eh-frame-hdr']
    for index, command in enumerate(commands):
        result = subprocess.run(command, text=True, capture_output=True)
        (output / f"build-{index}.log").write_text(result.stdout + result.stderr)
        result.check_returncode()
    elf = subprocess.run(["readelf", "-h", "-d", "-Ws", str(library)], check=True, text=True, capture_output=True).stdout
    (output / "elf.txt").write_text(elf)
    if "AArch64" not in elf:
        raise RuntimeError("Unexpected bridge ELF architecture")
    evidence = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "commands": commands,
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "wire_sha256": hashlib.sha256(wire.read_bytes()).hexdigest(),
        "library": str(library),
        "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "vendor_program_executed": False,
        "application_feedback": application_feedback,
        "scope": "Original TLV IO boundary only; no serial/crank kinematic conversion; no high-level command injection.",
    }
    if application_feedback:
        evidence.update(application_source_sha256=hashlib.sha256(application.read_bytes()).hexdigest(),
                        expected_original_publisher_sha256=publisher_sha256,
                        application_header_sha256=hashlib.sha256(application.with_suffix('.h').read_bytes()).hexdigest(),
                        scope='Original motor IO plus original state publisher readback, with ABI pinned to firmware DWARF; no estimator replacement')
    (output / "build.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return library


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--headers", type=Path)
    parser.add_argument("--rootfs", type=Path)
    parser.add_argument('--application-feedback', action='store_true')
    args = parser.parse_args()
    print(build(args.output, args.headers, args.rootfs, application_feedback=args.application_feedback))
