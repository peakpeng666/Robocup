"""Verify an extracted offline bundle against its manifest (hashes + ELF checks)."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    bad = []
    for f in manifest["files"]:
        p = (root / f["path"]).resolve()
        if not p.is_relative_to(root):
            bad.append({"path": f["path"], "error": "path escape"})
            continue
        if not p.is_file():
            bad.append({"path": f["path"], "error": "missing"})
            continue
        if sha256_file(p) != f["sha256"] or p.stat().st_size != f["size"]:
            bad.append({"path": f["path"], "error": "sha256 mismatch"})
    elf = root / "bin/bhuman"
    elf_report = None
    if manifest.get("mode") == "full" and not elf.is_file():
        bad.append({"path": "bin/bhuman", "error": "full bundle missing binary"})
    if elf.is_file():
        out = subprocess.run(["readelf", "-h", str(elf)], capture_output=True, text=True,
                             env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"})
        elf_report = {"aarch64": "AArch64" in out.stdout}
        if not elf_report["aarch64"]:
            bad.append({"path": "bin/bhuman", "error": "not AArch64"})
    library_names = {Path(f['path']).name for f in manifest['files'] if f['path'].startswith(('lib/', 'sysroot/'))}
    for entry in manifest.get('dependency_closure', []):
        for name in entry['needed']:
            if name not in library_names:
                bad.append({'path': entry['path'], 'error': 'unresolved NEEDED '+name})
    result = {"bundle_root": str(root), "checked": len(manifest["files"]),
              "mismatches": bad, "elf": elf_report,
              "status": "PASS" if not bad else "FAIL"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not bad else 3


if __name__ == "__main__":
    raise SystemExit(main())
