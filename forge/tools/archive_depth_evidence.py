#!/usr/bin/env python3
"""Archive completed-run depth bytes without changing their scientific content.

Only direct camera/*.depth-f32 files in explicitly named completed runs are
eligible. A durable manifest and a re-read, SHA-256-verified retained copy must
exist before the redundant uncompressed file is unlinked. Never delete archives.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs' / 'official-application'
ENCODING = 'float32-byteplanes-0123+gzip-level1'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def restore_bytes(data: bytes) -> bytes:
    planes = gzip.decompress(data)
    if len(planes) % 4:
        raise ValueError('Truncated float32 byteplanes')
    result = bytearray(len(planes))
    count = len(planes) // 4
    for byte in range(4):
        result[byte::4] = planes[byte * count:(byte + 1) * count]
    return bytes(result)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def runtime_references(run: Path) -> dict:
    """Inspect same-user process cwd/exe/fds/maps/arguments; never expose args."""
    refs, denied, session_helpers = [], [], []
    count = 0
    needle = str(run)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            count += 1
            for kind in ('cwd', 'exe'):
                try:
                    if needle in os.readlink(proc / kind):
                        refs.append({'pid': int(proc.name), 'kind': kind})
                except FileNotFoundError:
                    pass
            try:
                for fd in (proc / 'fd').iterdir():
                    try:
                        if needle in os.readlink(fd):
                            refs.append({'pid': int(proc.name), 'kind': 'fd'})
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                pass
            for kind in ('cmdline', 'maps'):
                try:
                    if needle.encode() in (proc / kind).read_bytes():
                        refs.append({'pid': int(proc.name), 'kind': kind})
                except FileNotFoundError:
                    pass
        except ProcessLookupError:
            continue
        except PermissionError:
            # sd-pam is the non-dumpable user-session helper, not a simulator.
            # Keep this explicit inspection limitation in every receipt.
            try:
                cmdline = (proc / 'cmdline').read_bytes()
                ppid = next(line.split()[1] for line in (proc / 'status').read_text().splitlines()
                            if line.startswith('PPid:'))
                parent_name = (Path('/proc') / ppid / 'comm').read_text().strip()
                if cmdline == b'(sd-pam)\0' and parent_name == 'systemd':
                    session_helpers.append({'pid': int(proc.name), 'name': '(sd-pam)',
                                            'parent_pid': int(ppid), 'parent_name': parent_name})
                else:
                    denied.append(int(proc.name))
            except OSError:
                denied.append(int(proc.name))
    return {'time_utc': datetime.now(timezone.utc).isoformat(),
            'run': str(run), 'same_uid_processes': count,
            'references': refs, 'permission_denied': denied,
            'uninspectable_system_session_helpers': session_helpers}


def durable_json(path: Path, value: dict) -> None:
    with path.open('x') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


def completed_run(name: str, excluded: list[str]) -> Path:
    if name in excluded or Path(name).name != name:
        raise ValueError(f'Excluded or invalid run: {name}')
    run = RUNS / name
    if run.is_symlink() or not run.is_dir():
        raise ValueError(f'Not an original local run: {run}')
    for report_name in ('applications-end.json', 'native-processes-end.json',
                        'result.json'):
        report = json.loads((run / report_name).read_text())
        if report_name.endswith('end.json'):
            if not report.get('robots') or any(
                robot.get('exit_code') is None for robot in report['robots'].values()
            ):
                raise ValueError(f'Run has no completed process receipt: {run}')
    return run


def stable_identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


def archive_one(source: Path, manifest) -> dict:
    before = source.lstat()
    if source.resolve() != source.absolute():
        raise ValueError(f'Refusing linked parent path: {source}')
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError(f'Refusing symlink, special or hardlinked file: {source}')
    raw = source.read_bytes()
    if len(raw) % 4:
        raise ValueError(f'Invalid float32 length: {source}')
    encoded = gzip.compress(b''.join(raw[byte::4] for byte in range(4)),
                            compresslevel=1, mtime=0)
    archive = source.with_name(source.name + '-byteplanes.gz')
    if len(encoded) >= len(raw):
        raise ValueError(f'Archive would not reclaim space: {source}')
    with archive.open('xb') as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(archive, stat.S_IMODE(before.st_mode))
    os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
    sync_directory(archive.parent)
    retained = archive.read_bytes()
    original_sha = digest(raw)
    if digest(retained) != digest(encoded) or digest(restore_bytes(retained)) != original_sha:
        raise ValueError(f'Retained archive failed independent disk re-read: {archive}')
    if stable_identity(before) != stable_identity(source.lstat()):
        raise ValueError(f'Original changed during archive: {source}')
    row = {'original_path': str(source), 'original_sha256': original_sha,
           'original_size': len(raw), 'original_mode': stat.S_IMODE(before.st_mode),
           'original_mtime_ns': before.st_mtime_ns, 'original_atime_ns': before.st_atime_ns,
           'original_allocated_bytes': before.st_blocks * 512,
           'archive_path': str(archive), 'archive_sha256': digest(retained),
           'archive_size': len(retained), 'encoding': ENCODING,
           'archive_allocated_bytes': archive.stat().st_blocks * 512,
           'restored_sha256': original_sha, 'retained_copy_verified': True}
    manifest.write(json.dumps(row, separators=(',', ':')) + '\n')
    manifest.flush()
    os.fsync(manifest.fileno())
    source.unlink()
    sync_directory(source.parent)
    return row


def archive(args) -> None:
    runs = [completed_run(name, args.exclude) for name in args.run]
    receipt = args.receipt.resolve()
    receipt.mkdir(parents=True, exist_ok=False)
    initial_free = shutil.disk_usage(ROOT).free
    scans = [runtime_references(run) for run in runs]
    durable_json(receipt / 'runtime-references-before.json', {'scans': scans})
    if any(scan['references'] or scan['permission_denied'] for scan in scans):
        raise ValueError('Run has live or unreadable references; no original files changed')
    files = {run: sorted(run.glob('robot*/camera/*.depth-f32')) for run in runs}
    durable_json(receipt / 'plan.json', {
        'schema': 'forge.depth-evidence-archive/1', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'free_bytes_before': initial_free, 'excluded_runs': args.exclude,
        'runs': [{'path': str(run), 'files': len(paths),
                  'bytes': sum(path.stat().st_size for path in paths)}
                 for run, paths in files.items()], 'encoding': ENCODING,
        'preserved': 'RGB, wire, events, reports, binaries, source, models, environments, Git histories',
        'tool_sha256': digest(Path(__file__).read_bytes())})
    total = reclaimed = raw_bytes = archive_bytes = 0
    started = last_log = time.monotonic()
    per_run = []
    with (receipt / 'manifest.jsonl').open('x') as manifest, \
            (receipt / 'runtime-checks.jsonl').open('x') as checks:
        for run, paths in files.items():
            run_count = run_saved = 0
            for index, source in enumerate(paths):
                if index % 250 == 0:
                    scan = runtime_references(run)
                    checks.write(json.dumps(scan) + '\n')
                    checks.flush()
                    if scan['references'] or scan['permission_denied']:
                        raise ValueError(f'Runtime reference appeared; stopped before {source}')
                row = archive_one(source, manifest)
                saved = row['original_allocated_bytes'] - row['archive_allocated_bytes']
                total += 1
                run_count += 1
                reclaimed += saved
                run_saved += saved
                raw_bytes += row['original_size']
                archive_bytes += row['archive_size']
                if time.monotonic() - last_log >= 15:
                    print(json.dumps({'verified_files': total, 'reclaimed_gib': reclaimed / 2**30,
                                      'free_gib': shutil.disk_usage(ROOT).free / 2**30}), flush=True)
                    last_log = time.monotonic()
            per_run.append({'run': str(run), 'files': run_count, 'allocated_bytes_reclaimed': run_saved})
            print(json.dumps(per_run[-1]), flush=True)
    durable_json(receipt / 'summary.json', {
        'status': 'PASS', 'finished_utc': datetime.now(timezone.utc).isoformat(),
        'verified_files': total, 'raw_bytes': raw_bytes, 'archive_bytes': archive_bytes,
        'allocated_bytes_reclaimed': reclaimed, 'free_bytes_before': initial_free,
        'free_bytes_after': shutil.disk_usage(ROOT).free,
        'elapsed_seconds': time.monotonic() - started, 'runs': per_run})


def read_verified(row: dict) -> bytes:
    archive = Path(row['archive_path'])
    data = archive.read_bytes()
    if digest(data) != row['archive_sha256']:
        raise ValueError(f'Archive hash mismatch: {archive}')
    restored = restore_bytes(data)
    if digest(restored) != row['original_sha256'] or len(restored) != row['original_size']:
        raise ValueError(f'Original hash mismatch: {archive}')
    return restored


def verify_or_restore(args) -> None:
    count = 0
    for line in args.manifest.read_text().splitlines():
        row = json.loads(line)
        if args.original and row['original_path'] != str(args.original.resolve()):
            continue
        restored = read_verified(row)
        if args.command == 'restore':
            destination = args.output or Path(row['original_path'])
            with destination.open('xb') as handle:
                handle.write(restored)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(destination, row['original_mode'])
            os.utime(destination, ns=(row['original_atime_ns'], row['original_mtime_ns']))
            if digest(destination.read_bytes()) != row['original_sha256']:
                raise ValueError(f'Restored file re-read hash mismatch: {destination}')
        count += 1
    if not count:
        raise ValueError('No matching evidence record')
    print(json.dumps({'status': 'PASS', 'operation': args.command, 'verified_files': count}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('archive')
    create.add_argument('--run', action='append', required=True)
    create.add_argument('--exclude', action='append', default=[])
    create.add_argument('--receipt', type=Path, required=True)
    for name in ('verify', 'restore'):
        action = commands.add_parser(name)
        action.add_argument('--manifest', type=Path, required=True)
        action.add_argument('--original', type=Path, required=name == 'restore')
        action.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'archive':
        archive(args)
    else:
        verify_or_restore(args)


if __name__ == '__main__':
    main()
