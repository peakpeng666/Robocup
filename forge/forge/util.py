"""Hashing, JSON and time helpers shared by every Forge module."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def stamp() -> str:
    return datetime.now(TZ).strftime("%Y%m%d_%H%M%S_%f")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(root: Path, exclude_dirs=()) -> dict:
    """{relative posix path: sha256} for every regular file below root."""
    root = Path(root)
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in exclude_dirs:
            continue
        out[relative.as_posix()] = sha256_file(path)
    return out


def manifest_digest(manifest: dict) -> str:
    return sha256_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return default


def write_json(path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, path)
    return path


def safe_name(text: str, limit=48) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.strip().lower())
    keep = "-".join(part for part in keep.split("-") if part)
    return keep[:limit] or "unnamed"
