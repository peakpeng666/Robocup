"""Verify an ARM64 ELF product: arch, interpreter, NEEDED, symbol versions.

Uses file/readelf on the host (never executes the ARM binary).
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import util  # noqa: E402


def run(argv):
    import os
    env = dict(os.environ, LC_ALL="C")
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env)
    return out.returncode, out.stdout + out.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    elf = Path(args.elf)
    checks = {}
    details = {}

    code, out = run(["file", str(elf)])
    details["file"] = out.strip()
    checks["file_reports_aarch64"] = ("aarch64" in out.lower() or "ARM aarch64" in out) and "ELF" in out

    code, out = run(["readelf", "-h", str(elf)])
    details["elf_header"] = out
    checks["machine_aarch64"] = "AArch64" in out
    checks["is_executable_or_pie"] = ("EXEC" in out) or ("DYN" in out)

    code, out = run(["readelf", "-l", str(elf)])
    m = re.search(r"interpreter:\s*([^\]]+)\]", out)
    interp = m.group(1) if m else None
    details["interpreter"] = interp
    checks["interpreter_aarch64_ld"] = interp == "/lib/ld-linux-aarch64.so.1"

    code, out = run(["readelf", "-d", str(elf)])
    needed = re.findall(r"Shared library:\s*\[([^\]]+)\]", out)
    details["needed"] = needed
    checks["has_needed_libraries"] = len(needed) > 0
    details["needed_count"] = len(needed)

    code, out = run(["readelf", "-V", str(elf)])
    versions = sorted(set(re.findall(r"Name:\s*(GLIBCXX_\S+|GLIBC_\S+|CXXABI_\S+)", out)))
    details["symbol_versions"] = versions[:40]

    result = {
        "elf": str(elf),
        "sha256": util.sha256_file(elf),
        "size": elf.stat().st_size,
        "checks": checks,
        "details": details,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "note": "宿主 file/readelf 静态检查；未在 ARM 上执行，不代表真机/DDS 兼容。",
    }
    util.write_json(Path(args.out), result)
    print(json.dumps({"status": result["status"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
