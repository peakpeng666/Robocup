"""Standard-library installer embedded as __main__.py in a tooling-only zipapp.

This installs research tooling. It does not flash robots or contain trained policies.
SHA-256 checks detect inconsistency; they are not a publisher signature.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid
import zipfile


PROJECT_ID = "k1-soccer-lab"
SCHEMA_VERSION = 1
ROOT_MARKER = ".k1-soccer-lab-root.json"
LOCK_NAME = ".install.lock"
INSTALLED_MANIFEST = ".release-manifest.json"
INSTALLED_DIGEST = ".release-manifest.sha256"
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_FILES = 50000
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
PAYLOAD_DIRS = ("k1lab", "configs", "docs", "tools")
PAYLOAD_ROOT_FILES = ("README.md", "sources.lock.json", "source-lock.json", "upstream.lock.json")


class ReleaseError(Exception):
    """A package or installation root failed a required check."""


def validate_version(value: str) -> str:
    if not isinstance(value, str) or len(value) > 96 or not VERSION_RE.fullmatch(value):
        raise ReleaseError("Invalid release version; use a version such as 0.1.0 or 0.1.0-rc.1")
    return value


def safe_name(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ReleaseError(f"Unsafe archive path: {value!r}")
    return value


def allowed_payload(value: str) -> bool:
    safe_name(value)
    parts = value.split("/")
    return (len(parts) == 1 and value in PAYLOAD_ROOT_FILES) or (
        len(parts) >= 2 and parts[0] in PAYLOAD_DIRS
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Invalid JSON metadata: {exc}") from exc


def canonical_json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _check_record(record, *, payload: bool):
    expected = {"sha256", "size", "mode"} if payload else {"sha256", "size"}
    if not isinstance(record, dict) or set(record) != expected:
        raise ReleaseError("Invalid manifest file record")
    if not isinstance(record["sha256"], str) or not SHA_RE.fullmatch(record["sha256"]):
        raise ReleaseError("Invalid SHA-256 value")
    if type(record["size"]) is not int or not 0 <= record["size"] <= MAX_FILE_BYTES:
        raise ReleaseError("Invalid or oversized manifest file size")
    if payload and (type(record["mode"]) is not int or record["mode"] not in (0o644, 0o755)):
        raise ReleaseError("Invalid payload file mode")


def validate_manifest(manifest):
    required = {
        "schema_version", "project_id", "artifact_kind", "version",
        "contains_trained_policy", "robot_flash_supported", "checksum_role",
        "bootstrap", "files",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ReleaseError("Invalid manifest schema")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION
            or manifest["project_id"] != PROJECT_ID
            or manifest["artifact_kind"] != "tooling"
            or manifest["contains_trained_policy"] is not False
            or manifest["robot_flash_supported"] is not False
            or manifest["checksum_role"] != "integrity_only_not_signature"):
        raise ReleaseError("This installer accepts tooling-only packages; robot flashing is unsupported")
    validate_version(manifest["version"])
    _check_record(manifest["bootstrap"], payload=False)
    files = manifest["files"]
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ReleaseError("Manifest must contain a bounded, nonempty file mapping")
    total = 0
    for name, record in files.items():
        if not allowed_payload(name):
            raise ReleaseError(f"Payload path is outside the tooling allowlist: {name}")
        _check_record(record, payload=True)
        total += record["size"]
    if total > MAX_TOTAL_BYTES:
        raise ReleaseError("Payload exceeds the tooling size limit")
    return manifest


def _read_metadata(archive, name):
    if archive.getinfo(name).file_size > MAX_METADATA_BYTES:
        raise ReleaseError(f"Oversized metadata: {name}")
    return archive.read(name)


def _check_bytes(raw: bytes, record, name: str):
    if len(raw) != record["size"]:
        raise ReleaseError(f"Size mismatch: {name}")
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ReleaseError(f"SHA-256 mismatch: {name}")


def _hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            return digest.hexdigest(), size
        size += len(block)
        if size > MAX_FILE_BYTES:
            raise ReleaseError("File exceeds the tooling size limit")
        digest.update(block)


def verify_archive(archive: zipfile.ZipFile):
    infos = archive.infolist()
    if len(infos) > MAX_FILES + 3:
        raise ReleaseError("Too many archive members")
    seen = set()
    total = 0
    for info in infos:
        safe_name(info.filename)
        if info.filename in seen:
            raise ReleaseError(f"Duplicate ZIP member: {info.filename}")
        seen.add(info.filename)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ReleaseError(f"ZIP symlink is not accepted: {info.filename}")
        if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
            raise ReleaseError(f"Only regular ZIP files are accepted: {info.filename}")
        if info.flag_bits & 1:
            raise ReleaseError("Encrypted ZIP members are not supported")
        if info.file_size > MAX_FILE_BYTES:
            raise ReleaseError(f"Oversized ZIP member: {info.filename}")
        total += info.file_size
    if total > MAX_TOTAL_BYTES + 3 * MAX_METADATA_BYTES:
        raise ReleaseError("Archive exceeds the tooling size limit")
    for name in ("__main__.py", "manifest.json", "manifest.sha256"):
        if name not in seen:
            raise ReleaseError(f"Missing archive metadata: {name}")
    raw = _read_metadata(archive, "manifest.json")
    try:
        declared_digest = _read_metadata(archive, "manifest.sha256").decode("ascii").strip()
    except UnicodeError as exc:
        raise ReleaseError("Invalid manifest checksum encoding") from exc
    if not SHA_RE.fullmatch(declared_digest) or hashlib.sha256(raw).hexdigest() != declared_digest:
        raise ReleaseError("Manifest SHA-256 mismatch")
    manifest = validate_manifest(parse_json(raw))
    expected = {"__main__.py", "manifest.json", "manifest.sha256"}
    expected.update("payload/" + name for name in manifest["files"])
    if seen != expected:
        raise ReleaseError("ZIP member set does not match the manifest")
    _check_bytes(_read_metadata(archive, "__main__.py"), manifest["bootstrap"], "__main__.py")
    for name, record in manifest["files"].items():
        archive_name = "payload/" + name
        if archive.getinfo(archive_name).file_size != record["size"]:
            raise ReleaseError(f"ZIP size disagrees with manifest: {name}")
        with archive.open(archive_name) as stream:
            digest, size = _hash_stream(stream)
        if size != record["size"] or digest != record["sha256"]:
            raise ReleaseError(f"Payload SHA-256 or size mismatch: {name}")
    return manifest, raw


def _no_symlink_components(path: Path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ReleaseError(f"Symlink path component is not accepted: {current}")


def absolute_root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise ReleaseError("--install-root must be an absolute directory path below a writable parent")
    _no_symlink_components(path)
    return path


def _regular_file(path: Path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ReleaseError(f"Required file is missing: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ReleaseError(f"Expected a regular file, not a symlink or other object: {path}")


def _fsync_dir(path: Path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, content: bytes, mode=0o644):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _root_identity():
    return {"project_id": PROJECT_ID, "schema_version": SCHEMA_VERSION, "artifact_kind": "tooling"}


def _check_root_identity(root: Path):
    if not root.is_dir() or root.is_symlink():
        raise ReleaseError("Installation root must be a real directory")
    marker = root / ROOT_MARKER
    if not marker.exists() and not marker.is_symlink():
        raise ReleaseError("Refusing an existing non-project directory: ownership marker is missing")
    _regular_file(marker)
    if marker.stat().st_size > MAX_METADATA_BYTES or parse_json(marker.read_bytes()) != _root_identity():
        raise ReleaseError("Refusing an existing non-project directory: ownership marker does not match")


def prepare_root(root: Path, *, create: bool):
    if root.exists():
        _check_root_identity(root)
        return
    if not create:
        raise ReleaseError("Installation root does not exist")
    root.parent.mkdir(parents=True, exist_ok=True)
    _no_symlink_components(root.parent)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        _check_root_identity(root)
        return
    _write_new(root / ROOT_MARKER, canonical_json(_root_identity()), 0o600)
    _fsync_dir(root)


@contextlib.contextmanager
def root_lock(root: Path):
    try:
        import fcntl
    except ImportError as exc:
        raise ReleaseError("The installer requires a POSIX host with fcntl; Linux is the target") from exc
    descriptor = os.open(root / LOCK_NAME, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError("Installation lock must be a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReleaseError("Another installation or rollback holds the installation lock") from exc
        _check_root_identity(root)
        yield
    finally:
        os.close(descriptor)


def verify_installed_release(path: Path):
    if not path.is_dir() or path.is_symlink():
        raise ReleaseError(f"Release target is not a real directory: {path}")
    manifest_path, digest_path = path / INSTALLED_MANIFEST, path / INSTALLED_DIGEST
    for item in (manifest_path, digest_path):
        _regular_file(item)
        if item.stat().st_size > MAX_METADATA_BYTES:
            raise ReleaseError("Oversized installed metadata")
    raw = manifest_path.read_bytes()
    try:
        digest = digest_path.read_text(encoding="ascii").strip()
    except UnicodeError as exc:
        raise ReleaseError("Invalid installed checksum encoding") from exc
    if not SHA_RE.fullmatch(digest) or hashlib.sha256(raw).hexdigest() != digest:
        raise ReleaseError("Installed manifest SHA-256 mismatch")
    manifest = validate_manifest(parse_json(raw))
    expected = set(manifest["files"]) | {INSTALLED_MANIFEST, INSTALLED_DIGEST}
    actual = set()
    for directory, directories, files in os.walk(path, followlinks=False):
        for name in directories:
            candidate = Path(directory) / name
            if candidate.is_symlink():
                raise ReleaseError(f"Installed release contains a symlink: {candidate}")
        for name in files:
            candidate = Path(directory) / name
            _regular_file(candidate)
            actual.add(candidate.relative_to(path).as_posix())
    if actual != expected:
        raise ReleaseError("Installed file set differs from its manifest; releases must remain immutable")
    for name, record in manifest["files"].items():
        candidate = path / name
        _regular_file(candidate)
        with candidate.open("rb") as stream:
            actual_digest, size = _hash_stream(stream)
        if size != record["size"] or actual_digest != record["sha256"]:
            raise ReleaseError(f"Installed payload SHA-256 or size mismatch: {name}")
    return manifest, raw


def _release_directory(root: Path) -> Path:
    releases = root / "releases"
    if releases.is_symlink():
        raise ReleaseError("The releases directory must not be a symlink")
    if releases.exists() and not releases.is_dir():
        raise ReleaseError("The releases path is not a directory")
    releases.mkdir(mode=0o755, exist_ok=True)
    return releases


def _read_pointer(root: Path, name: str):
    pointer = root / name
    if not pointer.exists() and not pointer.is_symlink():
        return None
    if not pointer.is_symlink():
        raise ReleaseError(f"Refusing to replace a non-symlink managed pointer: {pointer}")
    target = os.readlink(pointer)
    safe_name(target)
    parts = target.split("/")
    if len(parts) != 2 or parts[0] != "releases":
        raise ReleaseError(f"Managed pointer leaves the project releases: {name}")
    validate_version(parts[1])
    manifest, _ = verify_installed_release(root / target)
    if manifest["version"] != parts[1]:
        raise ReleaseError(f"Release directory and manifest version disagree: {target}")
    return target


def _activate(root: Path, target: str, old_current, old_previous):
    """Each pointer replacement is atomic; current is the final commit point."""
    if target == old_current:
        return
    temporary_current = root / (".current-" + uuid.uuid4().hex)
    temporary_previous = root / (".previous-" + uuid.uuid4().hex)
    restore_previous = root / (".restore-previous-" + uuid.uuid4().hex)
    previous_changed = False
    try:
        os.symlink(target, temporary_current)
        if old_current is not None:
            os.symlink(old_current, temporary_previous)
        if old_previous is not None:
            os.symlink(old_previous, restore_previous)
        _fsync_dir(root)
        if old_current is not None:
            os.replace(temporary_previous, root / "previous")
            previous_changed = True
        try:
            os.replace(temporary_current, root / "current")
        except BaseException:
            if previous_changed:
                if old_previous is None:
                    (root / "previous").unlink()
                else:
                    os.replace(restore_previous, root / "previous")
            raise
        # The activation has committed. A durability error must not be reported
        # as a failed installation after a valid current pointer was published.
        try:
            _fsync_dir(root)
        except OSError:
            pass
    finally:
        for path in (temporary_current, temporary_previous, restore_previous):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def install(archive, manifest, raw: bytes, root: Path):
    prepare_root(root, create=True)
    with root_lock(root):
        releases = _release_directory(root)
        old_current = _read_pointer(root, "current")
        old_previous = _read_pointer(root, "previous")
        if old_previous is not None and old_current is None:
            raise ReleaseError("A previous pointer without current requires manual inspection")
        final = releases / manifest["version"]
        if final.exists() or final.is_symlink():
            _, installed_raw = verify_installed_release(final)
            if installed_raw != raw:
                raise ReleaseError("Refusing to overwrite an existing version with different contents")
        else:
            stage = releases / (".staging-" + uuid.uuid4().hex)
            stage.mkdir(mode=0o700)
            try:
                for name, record in manifest["files"].items():
                    destination = stage / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), record["mode"])
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open("payload/" + name) as source, os.fdopen(descriptor, "wb") as output:
                        while True:
                            block = source.read(1024 * 1024)
                            if not block:
                                break
                            size += len(block)
                            if size > record["size"]:
                                raise ReleaseError(f"Payload grew while extracting: {name}")
                            output.write(block)
                            digest.update(block)
                        output.flush()
                        os.fsync(output.fileno())
                    if size != record["size"] or digest.hexdigest() != record["sha256"]:
                        raise ReleaseError(f"Payload changed while extracting: {name}")
                _write_new(stage / INSTALLED_MANIFEST, raw)
                _write_new(stage / INSTALLED_DIGEST, (hashlib.sha256(raw).hexdigest() + "\n").encode("ascii"))
                verify_installed_release(stage)
                _fsync_dir(stage)
                os.rename(stage, final)
                _fsync_dir(releases)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        target = "releases/" + manifest["version"]
        _activate(root, target, old_current, old_previous)
    return {"status": "installed", "version": manifest["version"], "install_root": str(root), "current": target}


def rollback(root: Path):
    prepare_root(root, create=False)
    with root_lock(root):
        _release_directory(root)
        current = _read_pointer(root, "current")
        previous = _read_pointer(root, "previous")
        if current is None or previous is None or current == previous:
            raise ReleaseError("No distinct, verified previous release is available for rollback")
        _activate(root, previous, current, previous)
    return {"status": "rolled_back", "install_root": str(root), "current": previous, "previous": current}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Install or verify K1 research tooling only. No trained policy or robot flashing. "
        "SHA-256 checks are integrity checks, not publisher signatures."
    ))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--verify", action="store_true", help="Verify package metadata, all members, SHA-256 and sizes without installing")
    action.add_argument("--rollback", action="store_true", help="Swap verified current and previous releases")
    parser.add_argument("--install-root", help="Absolute user-writable project installation directory; no sudo")
    args = parser.parse_args(argv)
    if args.verify and args.install_root:
        parser.error("--verify does not use --install-root")
    if not args.verify and not args.install_root:
        parser.error("--install-root is required for installation or rollback; use --verify to inspect")
    try:
        root = absolute_root(args.install_root) if args.install_root else None
        with zipfile.ZipFile(Path(sys.argv[0]).resolve()) as archive:
            manifest, raw = verify_archive(archive)
            if args.verify:
                result = {"status": "verified", "version": manifest["version"], "files": len(manifest["files"])}
            elif args.rollback:
                result = rollback(root)
            else:
                result = install(archive, manifest, raw, root)
        result.update({"artifact_kind": "tooling", "contains_trained_policy": False,
                       "robot_flash_supported": False, "checksum_role": "integrity_only_not_signature"})
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
