"""Cached content identities for evidence, never package/GPU imports."""
import hashlib
from pathlib import Path
import threading
import time

from . import config, util

_cache = {}
_lock = threading.RLock()
_latest = None
_at = 0


def file_identity(path):
    path = Path(path)
    try:
        s = path.stat()
        key = (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        with _lock:
            old = _cache.get(str(path))
            # ext4 can coalesce sub-tick mtime/ctime updates: freshly written
            # same-size files must be hashed again even if their stat tuple matches.
            settled = time.time_ns() - max(s.st_mtime_ns, s.st_ctime_ns) > 2_000_000_000
            if old and old[0] == key and settled:
                return old[1]
            value = util.sha256_file(path)
            _cache[str(path)] = (key, value)
            return value
    except OSError:
        return None


def capture():
    from contracts.regression_check import CONTRACT_PATHS
    p = config.project()
    local = config.rp(p["chains"]["bhuman"]["source"])
    official = config.rp(p["chains"]["bhuman"]["official_source"])
    protected = {rel: {"working": file_identity(local / rel), "official": file_identity(official / rel)}
                 for rel in CONTRACT_PATHS}
    src = config.rp(p["chains"]["training"]["src"])
    tree = hashlib.sha256()
    for f in sorted(f for f in src.rglob("*") if f.suffix in (".py", ".yaml") and "logs" not in f.parts):
        tree.update(str(f.relative_to(src)).encode())
        tree.update(f.read_bytes())
    files = {str(config.rp(rel)): file_identity(config.rp(rel)) for rel in (
        p["models"]["walk_pth"], p["models"]["walk_onnx_match"],
        "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
        "bhuman/k1-training/src/IsaacGymRL/resources/K1/K1_locomotion.xml",
        p["chains"]["bhuman"]["binary_release"])}
    files[str(local / "Build/Linux/SimRobot/Release/libSimulatedRobot.so")] = file_identity(local / "Build/Linux/SimRobot/Release/libSimulatedRobot.so")
    source_tree = hashlib.sha256()
    for folder in ('Src', 'Make/CMake', 'Util/CompiledNN2ONNX'):
        for f in sorted((local / folder).rglob('*')):
            if f.is_file() and f.suffix in ('.cpp','.h','.hpp','.cmake','.txt'):
                source_tree.update(str(f.relative_to(local)).encode())
                source_tree.update((file_identity(f) or 'MISSING').encode())
    return {"training_source": tree.hexdigest(), "files": files,
            "bhuman_source_tree": source_tree.hexdigest(),
            "protected_files": protected,
            "official_contract_matches": bool(protected) and all(v["working"] and v["working"] == v["official"] for v in protected.values())}


def current():
    global _latest, _at
    with _lock:
        if _latest is None or time.monotonic() - _at > 3:
            _latest, _at = capture(), time.monotonic()
        return _latest
