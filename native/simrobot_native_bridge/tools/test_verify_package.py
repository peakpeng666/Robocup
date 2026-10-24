#!/usr/bin/env python3
"""Self-test for verify_package.py using synthetic packages (never the real evidence).

Covers: volume merge, happy path, size mismatch, content corruption, malicious
members (absolute path, '..', escaping symlink, device node), and manifest
hash mismatch. Run from anywhere; results also land in evidence/.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRIDGE_ROOT = TOOLS.parent


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_package(files: dict[str, bytes], with_manifest: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        if with_manifest:
            manifest = {"files": [{"path": n, "sha256": sha256(d)} for n, d in sorted(files.items())]}
            blob = json.dumps(manifest, indent=2).encode()
            ti = tarfile.TarInfo("artifact_manifest.json")
            ti.size = len(blob)
            tf.addfile(ti, io.BytesIO(blob))
    return buf.getvalue()


def build_malicious(kind: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        normal = b"payload"
        ti = tarfile.TarInfo("ok.txt"); ti.size = len(normal)
        tf.addfile(ti, io.BytesIO(normal))
        if kind == "absolute":
            ti = tarfile.TarInfo("/etc/evil.txt"); ti.size = 5
            tf.addfile(ti, io.BytesIO(b"evil\n"))
        elif kind == "dotdot":
            ti = tarfile.TarInfo("../evil.txt"); ti.size = 5
            tf.addfile(ti, io.BytesIO(b"evil\n"))
        elif kind == "symlink":
            ti = tarfile.TarInfo("lnk"); ti.type = tarfile.SYMTYPE; ti.linkname = "../../outside"
            tf.addfile(ti)
            ti = tarfile.TarInfo("lnk/evil.txt"); ti.size = 5
            tf.addfile(ti, io.BytesIO(b"evil\n"))
        elif kind == "device":
            ti = tarfile.TarInfo("dev0"); ti.type = tarfile.CHRTYPE; ti.devmajor = 1; ti.devminor = 3
            tf.addfile(ti)
    return buf.getvalue()


def run_tool(volumes: list[Path], work_dir: Path, name: str, expected_size: int, expected_sha: str) -> tuple[int, dict]:
    cmd = [sys.executable, str(TOOLS / "verify_package.py")]
    if len(volumes) == 1:
        cmd += [str(volumes[0])]
    else:
        cmd += [arg for v in volumes for arg in ("--volume", str(v))]
    cmd += ["--name", name, "--expected-size", str(expected_size),
            "--expected-sha256", expected_sha, "--work-dir", str(work_dir),
        "--evidence-tag", "selftest-package-verification"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        report = json.loads(proc.stdout[: proc.stdout.rfind("}") + 1]) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        report = {}
    return proc.returncode, report


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = BRIDGE_ROOT / "work" / f"verify-package-selftest-{stamp}"
    base.mkdir(parents=True, exist_ok=True)
    results = []
    ok = True

    def record(case: str, passed: bool, detail: str = ""):
        nonlocal ok
        ok = ok and passed
        results.append({"case": case, "result": "PASS" if passed else "FAIL", "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {case} {detail}")

    # Happy path with split volumes.
    files = {"native_harness_restore/README.md": b"# synthetic\n",
             "official_motion_static/independent_nested_cpp/NestedPolicyMath.hpp": b"// synth\n",
             "state_machine/NativeLifecycle.hpp": b"// synth\n"}
    blob = build_package(files)
    vol_dir = base / "vols"
    vol_dir.mkdir()
    n = 3
    size = (len(blob) + n - 1) // n
    for i in range(n):
        chunk = blob[i * size:(i + 1) * size]
        (vol_dir / f"native_harness_sources_evidence_20261024.tar.gz.part{i:04d}").write_bytes(chunk)
    rc, rep = run_tool(sorted(vol_dir.iterdir()), base / "w1", "native_harness_sources_evidence_20261024.tar.gz",
                       len(blob), sha256(blob))
    record("happy-path-split-volumes", rc == 0 and rep.get("result") == "PASS" and rep.get("steps", {}).get("manifest") == "ok",
           rep.get("error", ""))
    # unpacked must exist and be read-only.
    unpacked = base / "w1" / "unpacked"
    record("unpacked-exists-readonly", (unpacked / "native_harness_restore" / "README.md").is_file()
           and not os.access(unpacked / "native_harness_restore" / "README.md", os.W_OK))

    # Size mismatch.
    rc, rep = run_tool(sorted(vol_dir.iterdir()), base / "w2", "pkg.tar.gz", len(blob) + 1, sha256(blob))
    record("size-mismatch-rejected", rc != 0 and "size mismatch" in rep.get("error", ""))

    # SHA mismatch (corrupt one volume).
    bad_dir = base / "vols_bad"
    bad_dir.mkdir()
    for i, f in enumerate(sorted(vol_dir.iterdir())):
        data = f.read_bytes()
        if i == 1:
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        (bad_dir / f.name).write_bytes(data)
    rc, rep = run_tool(sorted(bad_dir.iterdir()), base / "w3", "pkg.tar.gz", len(blob), sha256(blob))
    record("sha-mismatch-rejected", rc != 0 and "sha256 mismatch" in rep.get("error", ""))

    # Malicious archives.
    for kind, needle in [("absolute", "absolute member path"),
                         ("dotdot", "'..' in member path"),
                         ("symlink", "escaping link"),
                         ("device", "device/fifo member")]:
        evil = build_malicious(kind)
        d = base / f"evil_{kind}"
        d.mkdir()
        (d / "evil.tar.gz").write_bytes(evil)
        rc, rep = run_tool([d / "evil.tar.gz"], base / f"we_{kind}", "evil.tar.gz", len(evil), sha256(evil))
        record(f"malicious-{kind}-rejected", rc != 0 and needle in rep.get("error", ""))

    # Manifest hash mismatch: build package, then tamper one file content but keep manifest.
    files2 = dict(files)
    files2["state_machine/NativeLifecycle.hpp"] = b"// tampered\n"
    tampered = build_package(files2)  # manifest now lists tampered hash; ship original content
    # Simpler: craft package where manifest lies about one file.
    lying = io.BytesIO()
    with tarfile.open(fileobj=lying, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name); ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        ti = tarfile.TarInfo("state_machine/NativeLifecycle.hpp"); ti.size = 10
        tf.addfile(ti, io.BytesIO(b"// changed\n"))
        manifest = {"files": [{"path": n, "sha256": sha256(d)} for n, d in sorted(files.items())]}
        blob_m = json.dumps(manifest, indent=2).encode()
        ti = tarfile.TarInfo("artifact_manifest.json"); ti.size = len(blob_m)
        tf.addfile(ti, io.BytesIO(blob_m))
    evil2 = lying.getvalue()
    d = base / "lying"
    d.mkdir()
    (d / "lying.tar.gz").write_bytes(evil2)
    rc, rep = run_tool([d / "lying.tar.gz"], base / "w_lying", "lying.tar.gz", len(evil2), sha256(evil2))
    record("manifest-hash-mismatch-rejected",
           rc != 0 and "manifest.json verification FAILED" in rep.get("error", "")
           and any(f["file"] == "state_machine/NativeLifecycle.hpp" for f in rep.get("manifest", {}).get("failures", [])))

    ev_dir = BRIDGE_ROOT / "evidence" / f"{stamp}-verify-package-selftest"
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "report.json").write_text(json.dumps(
        {"started": stamp, "results": results, "all_pass": ok}, indent=2) + "\n")
    print(f"\nall_pass={ok}  evidence={ev_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
