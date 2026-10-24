#!/usr/bin/env python3
"""Verify and safely unpack the native-harness sources evidence package.

Implements the handoff protocol for the cloud-built Booster K1 1.7 native
motion reconstruction package:

  1. merge split volumes (several naming schemes) in order,
  2. verify total size and SHA-256 against expected values,
  3. store the original read-only under work/package/original/,
  4. unpack defensively under work/package/unpacked/ (reject absolute paths,
     "..", escaping or absolute links, device/fifo members; walk-up symlink
     parents are rejected too), then drop write permissions,
  5. verify every per-file hash listed in artifact_manifest.json,
  6. write evidence/<timestamp>/package-verification.json.

Nothing is downloaded and no code from the package is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DEFAULT_EXPECTED_SIZE = 63_478_869
DEFAULT_EXPECTED_SHA256 = "94e2ddeec14525f303958aa61e89eb57102a9814eb9b1f68534b6b4146b09ae5"
DEFAULT_PACKAGE_NAME = "native_harness_sources_evidence_20261024.tar.gz"

BRIDGE_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = BRIDGE_ROOT / "evidence"

NUMERIC_SUFFIX = re.compile(r"^(?P<stem>.+?)[.\-_ ](?P<idx>\d{2,6})$")
ALPHA_SUFFIX = re.compile(r"^(?P<stem>.+?)[.\-_ ](?P<idx>[a-z]{2,3})$")


class VerificationError(RuntimeError):
    pass


def display_path(p: Path) -> str:
    try:
        return str(p.relative_to(BRIDGE_ROOT))
    except ValueError:
        return str(p)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def discover_volumes(source: Path) -> list[Path]:
    """Turn a path (file, directory, or glob) into an ordered volume list."""
    if source.is_file():
        return [source]
    if source.is_dir():
        files = sorted(p for p in source.iterdir() if p.is_file())
        # Prefer numeric suffixed parts sharing one stem.
        groups: dict[str, list[tuple[int, str, Path]]] = {}
        for p in files:
            m = NUMERIC_SUFFIX.match(p.name)
            if m:
                groups.setdefault(m.group("stem"), []).append((int(m.group("idx")), p.name, p))
        if groups:
            stem, items = max(groups.items(), key=lambda kv: len(kv[1]))
            if len(items) >= 2:
                items.sort()
                return [p for _, _, p in items]
        # split(1) default two/three-letter suffixes, lexicographic order.
        groups_a: dict[str, list[Path]] = {}
        for p in files:
            m = ALPHA_SUFFIX.match(p.name)
            if m:
                groups_a.setdefault(m.group("stem"), []).append(p)
        if groups_a:
            stem, items = max(groups_a.items(), key=lambda kv: len(kv[1]))
            if len(items) >= 2:
                return sorted(items)
        if len(files) == 1:
            return files
        raise VerificationError(
            "cannot auto-detect volume order in directory; pass files explicitly via --volume"
        )
    raise VerificationError(f"source not found: {source}")


def merge_volumes(volumes: list[Path], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as dst:
        for v in volumes:
            with v.open("rb") as src:
                shutil.copyfileobj(src, dst, 1 << 20)


def drop_write_bits(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(p.stat().st_mode & ~0o222)
        for name in dirnames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(p.stat().st_mode & ~0o222)


class UnsafeMember(VerificationError):
    pass


def _check_member(m: tarfile.TarInfo) -> None:
    name = m.name
    if name.startswith("/") or name.startswith("\\") or (len(name) > 1 and name[1] == ":"):
        raise UnsafeMember(f"absolute member path: {name!r}")
    parts = PurePosixPath(name).parts
    if any(p == ".." for p in parts):
        raise UnsafeMember(f"'..' in member path: {name!r}")
    if m.ischr() or m.isblk() or m.isfifo():
        raise UnsafeMember(f"device/fifo member: {name!r} type={m.type}")
    if m.issym() or m.islnk():
        target = m.linkname
        if target.startswith("/") or (len(target) > 1 and target[1] == ":"):
            raise UnsafeMember(f"absolute link target: {name!r} -> {target!r}")
        base = PurePosixPath(name).parent if m.issym() else PurePosixPath(".")
        resolved = os.path.normpath(str(base / target))
        if resolved.split(os.sep)[0] == ".." or resolved.startswith("../"):
            raise UnsafeMember(f"escaping link: {name!r} -> {target!r}")


def _check_parents_not_symlinks(root: Path, name: str, known_links: set[str]) -> None:
    """Reject members placed under a symlinked directory inside the extraction root."""
    parent = PurePosixPath(name).parent
    parts = parent.parts if str(parent) != "." else ()
    acc = root
    for part in parts:
        acc = acc / part
        rel = str(acc.relative_to(root))
        if rel in known_links or acc.is_symlink():
            raise UnsafeMember(f"member {name!r} writes through symlinked directory {rel!r}")


def safe_unpack(archive: Path, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    links: set[str] = set()
    members = 0
    with tarfile.open(archive, "r:*") as tf:
        for m in tf:
            _check_member(m)
            _check_parents_not_symlinks(dest, m.name, links)
            if m.isdir():
                (dest / m.name).mkdir(parents=True, exist_ok=True)
            elif m.issym():
                (dest / m.name).parent.mkdir(parents=True, exist_ok=True)
                (dest / m.name).symlink_to(m.linkname)
                links.add(m.name)
            elif m.islnk():
                target = dest / os.path.normpath(m.linkname)
                (dest / m.name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest / m.name)
            else:
                src = tf.extractfile(m)
                if src is None:
                    raise UnsafeMember(f"unextractable member: {m.name!r} type={m.type}")
                out_path = dest / m.name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with src, out_path.open("wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                os.utime(out_path, (m.mtime, m.mtime))
            members += 1
    return {"members": members}


def parse_manifest(unpacked: Path) -> tuple[dict | None, str, list[str]]:
    """Return (entries {relpath: sha256}, shape, problems). Tolerates common shapes."""
    candidates = ["artifact_manifest.json", "manifest.json", "ARTIFACT_MANIFEST.json"]
    path = None
    for c in candidates:
        p = unpacked / c
        if p.is_file():
            path = p
            break
    if path is None:
        # one level deep
        for p in sorted(unpacked.rglob("*.json")):
            if p.name in candidates and p.parent == unpacked:
                path = p
        if path is None:
            for p in sorted(unpacked.rglob("artifact_manifest.json")):
                path = p
                break
    if path is None:
        return None, "missing", ["artifact_manifest.json not found in package"]
    try:
        data = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return None, "invalid-json", [f"manifest JSON parse error: {e}"]

    entries: dict[str, str] = {}
    shape = "unknown"

    def take(obj, keys_path, keys_hash):
        if isinstance(obj, dict) and keys_path & obj.keys() and keys_hash & obj.keys():
            p = next(obj[k] for k in keys_path if k in obj)
            h = next(obj[k] for k in keys_hash if k in obj)
            entries[str(p)] = str(h).lower()
            return True
        return False

    if isinstance(data, list):
        shape = "list"
        for obj in data:
            take(obj, {"path", "file", "name"}, {"sha256", "hash", "digest"})
    elif isinstance(data, dict):
        if isinstance(data.get("files"), list):
            shape = "files-list"
            for obj in data["files"]:
                take(obj, {"path", "file", "name"}, {"sha256", "hash", "digest"})
        elif isinstance(data.get("files"), dict):
            shape = "files-map"
            for p, meta in data["files"].items():
                if isinstance(meta, str):
                    entries[str(p)] = meta.lower()
                elif isinstance(meta, dict):
                    take({"path": p, **meta}, {"path"}, {"sha256", "hash", "digest"})
        elif isinstance(data.get("hashes"), dict):
            shape = "hashes-map"
            for p, h in data["hashes"].items():
                entries[str(p)] = str(h).lower()
        elif all(isinstance(v, str) for v in data.values()):
            shape = "flat-map"
            for p, h in data.items():
                entries[str(p)] = str(h).lower()
    problems = []
    if not entries and shape != "missing":
        problems.append(f"manifest shape not recognized (top-level type {type(data).__name__}); record sample")
    return entries, shape, problems


def verify_manifest(unpacked: Path) -> dict:
    entries, shape, problems = parse_manifest(unpacked)
    result = {"manifest_shape": shape, "listed_files": len(entries), "problems": problems,
              "failures": [], "verified": 0, "missing_in_package": [], "not_in_manifest": []}
    if entries is None:
        return result
    for rel, expected in sorted(entries.items()):
        p = unpacked / rel
        if not p.is_file():
            # tolerate a single leading directory difference
            alt = unpacked / Path(rel).name
            p = alt if alt.is_file() and not p.exists() else p
        if not p.is_file():
            result["missing_in_package"].append(rel)
            continue
        actual = sha256_file(p)
        if actual != expected:
            result["failures"].append({"file": rel, "expected": expected, "actual": actual})
        else:
            result["verified"] += 1
    listed = set(entries)
    present = {str(p.relative_to(unpacked)) for p in unpacked.rglob("*") if p.is_file()}
    result["not_in_manifest"] = sorted(present - listed)[:200]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", nargs="?", help="single archive, one volume, or directory with volumes")
    ap.add_argument("--volume", action="append", default=[], help="explicit ordered volume file (repeatable)")
    ap.add_argument("--name", default=DEFAULT_PACKAGE_NAME, help="expected archive file name")
    ap.add_argument("--expected-size", type=int, default=DEFAULT_EXPECTED_SIZE)
    ap.add_argument("--expected-sha256", default=DEFAULT_EXPECTED_SHA256)
    ap.add_argument("--work-dir", default=None,
                    help="override unpack workspace (default work/package); used by self-tests")
    ap.add_argument("--evidence-tag", default="package-verification",
                    help="evidence subdirectory label; self-tests use selftest-package-verification")
    args = ap.parse_args()
    work_package = Path(args.work_dir).resolve() if args.work_dir else BRIDGE_ROOT / "work" / "package"

    report: dict = {
        "started": datetime.now(timezone.utc).isoformat(),
        "tool": "tools/verify_package.py",
        "expected": {"name": args.name, "size": args.expected_size, "sha256": args.expected_sha256},
        "steps": {},
    }
    try:
        if args.volume:
            volumes = [Path(v) for v in args.volume]
        elif args.source:
            volumes = discover_volumes(Path(args.source))
        else:
            ap.error("give a source or --volume list")
        report["volumes"] = [str(v) for v in volumes]
        report["steps"]["merge"] = "ok"

        merged = work_package / "merged.tar.gz"
        merge_volumes(volumes, merged)
        actual_size = merged.stat().st_size
        actual_sha = sha256_file(merged)
        report["merged"] = {"size": actual_size, "sha256": actual_sha}
        if actual_size != args.expected_size:
            raise VerificationError(f"size mismatch: expected {args.expected_size}, got {actual_size}")
        if actual_sha != args.expected_sha256:
            raise VerificationError(f"sha256 mismatch: expected {args.expected_sha256}, got {actual_sha}")
        report["steps"]["identity"] = "ok"

        original = work_package / "original" / args.name
        original.parent.mkdir(parents=True, exist_ok=True)
        if original.exists():
            original.unlink()
        shutil.move(str(merged), original)
        original.chmod(original.stat().st_mode & ~0o222)
        report["original"] = {"path": display_path(original),
                              "size": original.stat().st_size}
        report["steps"]["original_archived"] = "ok"

        unpacked = work_package / "unpacked"
        if unpacked.exists():
            raise VerificationError("work/package/unpacked already exists; move it aside first")
        stats = safe_unpack(original, unpacked)
        drop_write_bits(unpacked)
        report["unpacked"] = {"path": display_path(unpacked), **stats}
        report["steps"]["safe_unpack"] = "ok"

        manifest_result = verify_manifest(unpacked)
        report["manifest"] = manifest_result
        if manifest_result["failures"] or manifest_result["missing_in_package"]:
            raise VerificationError("artifact_manifest.json verification FAILED")
        if not manifest_result["listed_files"]:
            raise VerificationError("artifact_manifest.json could not be parsed; manual review required")
        report["steps"]["manifest"] = "ok"
        report["result"] = "PASS"
    except (VerificationError, UnsafeMember) as e:
        report["result"] = "FAIL"
        report["error"] = str(e)
        report["steps"].setdefault("failure", str(e))
    report["finished"] = datetime.now(timezone.utc).isoformat()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ev_dir = EVIDENCE_ROOT / f"{stamp}-{args.evidence_tag}"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "package-verification.json"
    ev_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nevidence: {ev_file}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
