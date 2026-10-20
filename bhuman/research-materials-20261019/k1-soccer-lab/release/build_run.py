"""Build a deterministic, tooling-only executable Python zipapp (.run)."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

try:
    from . import installer
except ImportError:
    import installer


SHEBANG = b"#!/usr/bin/env python3\n"
SKIP_DIRECTORIES = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}


def _source_file(path: Path, source: Path):
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise installer.ReleaseError(f"Source symlinks and special files are not accepted: {path}")
    name = path.relative_to(source).as_posix()
    if not installer.allowed_payload(name):
        raise installer.ReleaseError(f"Source is outside the payload allowlist: {name}")
    data = path.read_bytes()
    if len(data) > installer.MAX_FILE_BYTES:
        raise installer.ReleaseError(f"Source file is too large for a tooling package: {name}")
    return name, data, 0o755 if mode & 0o111 else 0o644


def collect_source(source: Path):
    if source.is_symlink() or not source.is_dir():
        raise installer.ReleaseError("--source must be a real project directory")
    result = {}
    for filename in installer.PAYLOAD_ROOT_FILES:
        candidate = source / filename
        if candidate.exists() or candidate.is_symlink():
            name, data, mode = _source_file(candidate, source)
            result[name] = (data, mode)
    for dirname in installer.PAYLOAD_DIRS:
        start = source / dirname
        if start.is_symlink():
            raise installer.ReleaseError(f"Source symlink is not accepted: {start}")
        if not start.exists():
            continue
        if not start.is_dir():
            raise installer.ReleaseError(f"Expected a source directory: {start}")
        for directory, directories, filenames in os.walk(start, followlinks=False):
            for name in list(directories):
                candidate = Path(directory) / name
                if candidate.is_symlink():
                    raise installer.ReleaseError(f"Source symlink is not accepted: {candidate}")
                if name in SKIP_DIRECTORIES:
                    directories.remove(name)
            for filename in filenames:
                candidate = Path(directory) / filename
                if candidate.is_symlink():
                    raise installer.ReleaseError(f"Source symlink is not accepted: {candidate}")
                if candidate.suffix in (".pyc", ".pyo"):
                    continue
                name, data, mode = _source_file(candidate, source)
                result[name] = (data, mode)
    if not result:
        raise installer.ReleaseError("No allowlisted tooling files were found")
    if sum(len(value[0]) for value in result.values()) > installer.MAX_TOTAL_BYTES:
        raise installer.ReleaseError("Source exceeds the tooling package size limit")
    return dict(sorted(result.items()))


def _zip_write(archive, name: str, data: bytes, mode=0o644):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def build(source: Path, output: Path, version: str):
    installer.validate_version(version)
    if source.is_symlink():
        raise installer.ReleaseError("Source directory must not be a symlink")
    source = source.resolve(strict=True)
    output = output.absolute()
    if output.suffix != ".run":
        raise installer.ReleaseError("--output must end in .run")
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise installer.ReleaseError("Refusing a symlink or non-file output path")
    for dirname in installer.PAYLOAD_DIRS:
        if output == source / dirname or source / dirname in output.parents:
            raise installer.ReleaseError("Build output must be outside the packaged source directories")
    payload = collect_source(source)
    bootstrap = Path(__file__).with_name("installer.py").read_bytes()
    manifest = {
        "schema_version": installer.SCHEMA_VERSION,
        "project_id": installer.PROJECT_ID,
        "artifact_kind": "tooling",
        "version": version,
        "contains_trained_policy": False,
        "robot_flash_supported": False,
        "checksum_role": "integrity_only_not_signature",
        "bootstrap": {"sha256": hashlib.sha256(bootstrap).hexdigest(), "size": len(bootstrap)},
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": mode}
                  for name, (data, mode) in payload.items()},
    }
    installer.validate_manifest(manifest)
    raw = installer.canonical_json(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".k1-build-", suffix=".run", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(SHEBANG)
            with zipfile.ZipFile(stream, mode="w") as archive:
                _zip_write(archive, "__main__.py", bootstrap)
                _zip_write(archive, "manifest.json", raw)
                _zip_write(archive, "manifest.sha256", (hashlib.sha256(raw).hexdigest() + "\n").encode("ascii"))
                for name, (data, mode) in payload.items():
                    _zip_write(archive, "payload/" + name, data, mode)
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as archive:
            installer.verify_archive(archive)
        temporary.chmod(0o755)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"output": str(output), "version": version, "artifact_kind": "tooling",
            "contains_trained_policy": False, "robot_flash_supported": False,
            "checksum_role": "integrity_only_not_signature", "files": len(payload),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Build a tooling-only .run zipapp. No trained robot policy or robot flashing support. "
        "SHA-256 checks do not authenticate the publisher."
    ))
    parser.add_argument("--source", type=Path, required=True, help="Project root")
    parser.add_argument("--output", type=Path, required=True, help="Destination .run file")
    parser.add_argument("--version", required=True, help="Version such as 0.1.0")
    args = parser.parse_args(argv)
    try:
        result = build(args.source, args.output, args.version)
        print(installer.canonical_json(result).decode("utf-8"), end="")
        return 0
    except (installer.ReleaseError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
