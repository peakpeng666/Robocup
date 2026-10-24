#!/usr/bin/env python3
"""Create a build variant of bhuman-local for the native 1.7 SimRobot bridge.

Modeled on forge/forge/builds.py (same COPY_ENTRIES / linkable-Util /
patch-application discipline), but standalone so the bridge tree in robocup-1
does not depend on forge internals.

A variant is a copy of the validated runnable B-Human tree (Src, Make, Config,
Install, licenses) plus Util (linked read-only per entry, copied when a patch
touches it or the entry refers back into ../Src) plus an ordered patch stack.
The two verified SimRobot patches (delay-ring, then hybrid-actuator) are always
applied first; extra patches are appended in the given order.

Variants are immutable: re-running with an existing name fails. The base tree
is only ever read. Variants live under work/ (gitignored scratch).

Usage:
  make_variant.py [--name NAME] [--base PATH] [--patch FILE ...] [--list]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = BRIDGE_ROOT / "work"
DEFAULT_BASE = Path("/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/bhuman-local")

COPY_ENTRIES = ("Src", "Make", "Config", "Install", "License.md", "LicenseNaoDevils.txt", "README.md", "CITATION.cff")
LINKABLE_UTIL = ("SimRobot", "BoosterRoboticsSDK", "Buildchain", "onnxruntime", "hdf5", "fftw-3.3", "flite",
                 "gtest", "dot", "librealsense2")
ALWAYS_PATCHES = ("simrobot-9deb6ae6-delay-ring.patch", "simrobot-9deb6ae6-hybrid-actuator.patch")
# The two SimRobot patches use paths relative to the Util/SimRobot tree
# (Src/SimRobotCore3/...), unlike B-Human-side patches whose paths are relative
# to the variant root. git apply --directory prepends the root so the patch
# bytes stay identical to the public booster16 branch.
PATCH_ROOTS = {
    "simrobot-9deb6ae6-delay-ring.patch": "Util/SimRobot",
    "simrobot-9deb6ae6-hybrid-actuator.patch": "Util/SimRobot",
}
MANIFEST_ENTRIES = ("Src", "Make", "Config", "Install", "Util")


class VariantError(RuntimeError):
    pass


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def manifest_digest(manifest: dict) -> str:
    blob = json.dumps(manifest, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def tree_manifest(root: Path) -> dict:
    """Content hash of the source entries. Symlinked top-level Util entries are
    hashed through (like forge's source_manifest) so base drift invalidates the
    fingerprint; symlink cycles are recorded, not followed forever."""
    out: dict[str, str] = {}

    def visit(path: Path, seen: set[Path]):
        if path.is_symlink():
            real = path.resolve()
            if real in seen:
                out[path.relative_to(root).as_posix()] = "cycle-link:" + os.readlink(path)
                return
            seen = seen | {real}
        if path.is_dir():
            for child in sorted(path.iterdir()):
                visit(child, seen)
        elif path.is_file():
            out[path.relative_to(root).as_posix()] = sha256_file(path)

    for entry in MANIFEST_ENTRIES:
        p = root / entry
        if p.exists():
            visit(p, set())
    return out


def patch_root(patch: Path) -> str:
    return PATCH_ROOTS.get(patch.name, "")


def touched_util_entries(patch_files: list[Path]) -> set[str]:
    """Util entries a patch writes, honoring each patch's --directory root."""
    touched = set()
    for patch in patch_files:
        root = patch_root(patch)
        prefix = root + "/" if root else ""
        for line in patch.read_text(errors="replace").splitlines():
            m = re.match(r"^(?:\+\+\+|---) [ab]/(\S+)", line)
            if not m:
                continue
            path = prefix + m.group(1)
            if path.startswith("Util/"):
                touched.add(path.split("/")[1])
    return touched


def references_src(directory: Path) -> bool:
    pattern = re.compile(rb"\.\./(?:\.\./)*Src/")
    for path in directory.rglob("*"):
        if path.suffix in (".h", ".hpp", ".hh", ".c", ".cc", ".cpp", ".cmake", ".txt") and path.is_file():
            try:
                if pattern.search(path.read_bytes()):
                    return True
            except OSError:
                continue
    return False


def list_variants() -> list[dict]:
    out = []
    for vjson in sorted(WORK_ROOT.glob("variant-*/variant.json")):
        data = json.loads(vjson.read_text())
        data["dir"] = str(vjson.parent)
        out.append(data)
    return out


def create_variant(name: str, base: Path, extra_patches: list[Path], description: str) -> dict:
    root = WORK_ROOT / name
    if root.exists():
        raise VariantError(f"variant {root} already exists; variants are immutable, pick a new name")
    if not (base / "Make" / "CMake").is_dir():
        raise VariantError(f"base does not look like the B-Human tree: {base}")

    patch_files = [BRIDGE_ROOT / "patches" / p for p in ALWAYS_PATCHES] + [
        Path(p).resolve() for p in extra_patches]
    for patch in patch_files:
        if not patch.is_file():
            raise VariantError(f"patch not found: {patch}")

    staging = root.with_name(root.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        for entry in COPY_ENTRIES:
            source = base / entry
            if source.is_dir():
                shutil.copytree(source, staging / entry, symlinks=True)
            elif source.is_file():
                shutil.copy2(source, staging / entry)

        touched = touched_util_entries(patch_files)
        (staging / "Util").mkdir()
        linked, copied = [], []
        for entry in sorted((base / "Util").iterdir()):
            if entry.name in LINKABLE_UTIL and entry.name not in touched and not _dir_references(entry):
                (staging / "Util" / entry.name).symlink_to(entry)
                linked.append(entry.name)
            elif entry.is_dir():
                shutil.copytree(entry, staging / "Util" / entry.name, symlinks=True)
                copied.append(entry.name)
            else:
                shutil.copy2(entry, staging / "Util" / entry.name)
                copied.append(entry.name)

        applied = []
        # GIT_CEILING_DIRECTORIES: without it git resolves patch paths against the
        # enclosing robocup-1 repository and can silently skip the patch.
        git_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(staging.parent))
        for patch in patch_files:
            proot = patch_root(patch)
            prefix = proot + "/" if proot else ""
            targets = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", patch.read_text(errors="replace"), re.M)))
            staged = {t: prefix + t for t in targets}
            before = {t: sha256_file(staging / s) if (staging / s).is_file() else None
                      for t, s in staged.items()}
            cmd = ["git", "apply"]
            if proot:
                cmd += ["--directory", proot]
            cmd += ["-p1", str(patch)]
            check = subprocess.run(cmd[:2] + ["--check"] + cmd[2:], cwd=staging,
                                   capture_output=True, text=True, env=git_env)
            if check.returncode != 0 or not targets:
                raise VariantError(f"patch does not apply cleanly {patch.name}: "
                                   f"{check.stderr.strip()[:400] or 'no files in patch'}")
            subprocess.run(cmd, cwd=staging, check=True, env=git_env)
            unchanged = [t for t, s in staged.items()
                         if (sha256_file(staging / s) if (staging / s).is_file() else None) == before[t]]
            if unchanged:
                raise VariantError(f"patch {patch.name} left these files unchanged (silent skip?): {unchanged[:5]}")
            applied.append({"file": str(patch), "sha256": sha256_file(patch), "root": proot, "files": targets,
                            "file_hashes": {t: {"before": before[t],
                                                "after": sha256_file(staging / s) if (staging / s).is_file() else None}
                                            for t, s in staged.items()}})

        manifest = tree_manifest(staging)
        data = {
            "schema": "bridge.variant/1",
            "name": root.name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "base": str(base),
            "always_patches": list(ALWAYS_PATCHES),
            "patches": applied,
            "util_linked": linked,
            "util_copied": copied,
            "source_sha256": manifest_digest(manifest),
            "manifest_entries": list(MANIFEST_ENTRIES),
            "tool": "tools/make_variant.py",
        }
        (staging / "variant.json").write_text(json.dumps(data, indent=2) + "\n")
        staging.rename(root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return data


def _dir_references(entry: Path) -> bool:
    return entry.is_dir() and references_src(entry)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default=None, help="variant name (default variant-<timestamp>)")
    ap.add_argument("--base", default=str(DEFAULT_BASE), help="base B-Human tree (read-only)")
    ap.add_argument("--patch", action="append", default=[],
                    help="extra patch applied after the two always-on SimRobot patches (repeatable)")
    ap.add_argument("--description", default="native 1.7 SimRobot bridge variant")
    ap.add_argument("--list", action="store_true", help="list existing variants")
    args = ap.parse_args()

    if args.list:
        for v in list_variants():
            print(f"{v['name']}\t{v['created_at']}\tpatches={len(v['patches'])}\tbase={v['base']}")
        return 0

    name = args.name or f"variant-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    data = create_variant(name, Path(args.base).resolve(), [Path(p) for p in args.patch], args.description)
    print(json.dumps(data, indent=2)[:4000])
    print(f"\nvariant ready: {WORK_ROOT / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
