"""Shared helpers: hashing, timestamps, safe paths."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Tokyo")

SENSITIVE_PATTERNS = (".env", "recovery-key", "id_rsa", "id_ed25519", ".pem", ".key",
                      "credentials", "secret", ".ssh")


def now_local() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="milliseconds")


def stamp() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S_%f")


def sha256_file(path: Path, limit_mb: int = 0) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def training_source_fingerprint(src_root: Path) -> str:
    """Same algorithm as k1-training src/IsaacGymRL/utils/bh_common.py source_hash()."""
    files = sorted(p for p in src_root.rglob("*")
                   if p.suffix in (".py", ".yaml") and "logs" not in p.parts)
    digest = hashlib.sha256()
    for p in files:
        digest.update(str(p.relative_to(src_root)).encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def is_sensitive_name(path: Path) -> bool:
    name = path.name.lower()
    return any(pat in name for pat in SENSITIVE_PATTERNS)


def safe_resolve(path_str: str, allowed_roots) -> Path:
    """Resolve a user-supplied path; reject traversal and symlink escape.

    allowed_roots: iterable of Path. The resolved real path must live under one
    of them and must not look like a sensitive file.
    """
    candidate = Path(path_str)
    if not candidate.is_absolute():
        raise ValueError("需要绝对路径")
    real = Path(os.path.realpath(str(candidate)))
    ok = False
    for root in allowed_roots:
        root_real = Path(os.path.realpath(str(root)))
        try:
            real.relative_to(root_real)
            ok = True
            break
        except ValueError:
            continue
    if not ok:
        raise ValueError("路径不在允许的目录内: " + str(real))
    if any(is_sensitive_name(Path(part)) for part in real.parts):
        raise ValueError("拒绝访问敏感文件: " + real.name)
    return real


def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
