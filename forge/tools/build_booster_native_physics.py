#!/usr/bin/env python3
"""Build the explicit serial-joint adapter for the retained original ARM controller."""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import argparse
import hashlib
import json
import subprocess


def build(output: Path | None = None) -> Path:
    forge = Path(__file__).resolve().parents[1]
    sysroot = forge.parent / 'bhuman/local-k1-validation-20261019/bhuman-local/Util/Buildchain/Booster'
    runtime = forge / 'third_party/booster-native-arm64/rootfs'
    crt = forge / 'third_party/booster-native-arm64/crt/usr/lib/gcc/aarch64-linux-gnu/11'
    for name in ('crtbeginS.o', 'crtendS.o'):
        if not (crt / name).is_file():
            raise FileNotFoundError(crt / name)
    source = forge / 'native/booster_fw16_physics.cpp'
    stamp = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d_%H%M%S_%f')
    output = (output or forge / 'runs/native-controller' / (stamp + '_physics-build')).resolve()
    output.mkdir(parents=True, exist_ok=False)
    obj, library = output / 'physics.o', output / 'libforge_booster_fw16_physics.so'
    command = ['clang++', '--target=aarch64-linux-gnu', '--sysroot=' + str(sysroot), '-nostdinc++']
    for include in [sysroot / 'include/c++/11', sysroot / 'include/aarch64-linux-gnu/c++/11',
                    sysroot / 'include', sysroot / 'include/aarch64-linux-gnu', Path('/usr/include/eigen3')]:
        command += ['-isystem', str(include)]
    command += ['-std=c++17', '-O2', '-g', '-fPIC', '-Wall', '-Wextra', '-Werror', '-c', str(source), '-o', str(obj)]
    link = ['mold', '-m', 'aarch64linux', '-shared', '--no-undefined', '--eh-frame-hdr', '-z', 'now', '-z', 'relro',
            '-soname', library.name, '-o', str(library), str(sysroot / 'lib/crti.o'),
            str(crt / 'crtbeginS.o'), str(obj),
            str(runtime / 'usr/lib/aarch64-linux-gnu/libstdc++.so.6.0.30'),
            str(runtime / 'lib/aarch64-linux-gnu/libgcc_s.so.1'),
            str(runtime / 'lib/aarch64-linux-gnu/libm.so.6'), str(runtime / 'lib/aarch64-linux-gnu/libc.so.6'),
            str(crt / 'crtendS.o'), str(sysroot / 'lib/crtn.o')]
    for index, args in enumerate([command, link]):
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        (output / f'build-{index}.log').write_text(proc.stdout + proc.stderr)
        proc.check_returncode()
    inputs = [source, forge / 'native/booster_fw16_wire.h', forge / 'native/booster_fw16_physics.h',
              forge / 'tools/booster_parallel_bridge.hpp']
    receipt = {'schema': 'forge.native-physics-build/1', 'commands': [command, link],
               'sources': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               'library': str(library), 'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
               'wire_version': 2, 'robot_connected': False, 'vendor_program_executed': False}
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return library


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(build(args.output))
