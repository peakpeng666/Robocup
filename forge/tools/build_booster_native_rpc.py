#!/usr/bin/env python3
"""Compile only the local command ingress shim; do not execute vendor code."""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(application_api: bool = False) -> Path:
    forge = Path(__file__).resolve().parents[1]
    repo = forge.parent
    headers = repo / "bhuman/local-k1-validation-20261019/bhuman-local/Util/Buildchain/Booster"
    sdk = repo / "booster/booster_robotics_sdk/include"
    rootfs = forge / "third_party/booster-native-arm64/rootfs"
    native_rsm = forge / 'third_party/booster-k1-1.6.0.10/selected-payload/booster/lib/motion/librsm_modules.so'
    native_rsm_sha = hashlib.sha256(native_rsm.read_bytes()).hexdigest()
    if native_rsm_sha != '62ffcc60cd7b11ca15e8d3e9cdced695f01e1b97e0c88a07ea5d0d12b76d72a0':
        raise RuntimeError('Original RPC/visual-kick ABI differs from the audited 1.6.0.10 module')
    work = forge / "runs/native-controller" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") +
                                             ("_application-rpc-build" if application_api else "_rpc-build"))
    work.mkdir(parents=True)
    source = forge / "native/booster_fw16_rpc.cpp"
    obj, lib = work / "rpc.o", work / "libforge_booster_fw16_rpc.so"
    command = ["clang++", "--target=aarch64-linux-gnu", "--sysroot=" + str(headers), "-nostdinc++"]
    for include in [headers / "include/c++/11", headers / "include/aarch64-linux-gnu/c++/11",
                    headers / "include", headers / "include/aarch64-linux-gnu", sdk]:
        command += ["-isystem", str(include)]
    command += ["-std=c++17", "-O2", "-g", "-fPIC", "-Wall", "-Wextra", "-Werror", "-c", str(source), "-o", str(obj)]
    if application_api:
        command.insert(1, "-DFORGE_FW16_APPLICATION_API")
    link = ["mold", "-m", "aarch64linux", "-shared", "--no-undefined", "--eh-frame-hdr", "-z", "now", "-z", "relro",
            "-soname", lib.name, "-o", str(lib), str(obj),
            str(rootfs / "usr/lib/aarch64-linux-gnu/libstdc++.so.6.0.30"),
            str(rootfs / "lib/aarch64-linux-gnu/libgcc_s.so.1"),
            str(rootfs / "lib/aarch64-linux-gnu/libm.so.6"), str(rootfs / "lib/aarch64-linux-gnu/libc.so.6")]
    for i, cmd in enumerate((command, link)):
        result = subprocess.run(cmd, capture_output=True, text=True)
        (work / f"build-{i}.log").write_text(result.stdout + result.stderr)
        result.check_returncode()
    git_root = Path(subprocess.check_output(['git', '-C', str(sdk.parent), 'rev-parse', '--show-toplevel'], text=True).strip())
    workspace_commit = subprocess.check_output(['git', '-C', str(sdk.parent), 'rev-parse', 'HEAD'], text=True).strip()
    header_manifest = {str(path.relative_to(sdk)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(sdk.rglob('*')) if path.is_file()}
    (work / 'sdk-header-manifest.json').write_text(json.dumps(header_manifest, indent=2) + '\n')
    provenance = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "commands": [command, link],
        "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "adapter_headers": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (forge / 'native').glob('booster_fw16_*.h')},
        "library": str(lib), "library_sha256": hashlib.sha256(lib.read_bytes()).hexdigest(),
        "sdk_headers": str(sdk),
        "sdk_commit": workspace_commit if git_root.resolve() == sdk.parent.resolve() else None,
        "enclosing_git_root": str(git_root), "enclosing_workspace_commit": workspace_commit,
        "sdk_header_manifest_sha256": hashlib.sha256(json.dumps(header_manifest, sort_keys=True).encode()).hexdigest(),
        "scope": "Official SDK request/response layout matched to firmware DWARF; original HandleRequest dispatch; no private state writes, no DDS client, no physical robot connection.",
        "vendor_program_executed": False,
        "application_api": application_api,
        "original_rpc_module": str(native_rsm), "original_rpc_module_sha256": native_rsm_sha,
    }
    (work / "build.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return lib


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-api', action='store_true', help='Forward original public SDK JSON without fixture rewrites')
    args = parser.parse_args()
    print(build(application_api=args.application_api))
