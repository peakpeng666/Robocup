#!/usr/bin/env python3
"""Bounded, read-only artifact inventory. Never execute or unpack input files."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import struct
import subprocess
import time

SCHEMA_VERSION = 'booster16-artifact-inventory/1'
SECRET = re.compile(r'(^|[._-])(secrets?|credentials?|passwords?|tokens?|private|id_rsa|id_ed25519|recovery)([._-]|$)', re.I)
ARCHIVE = ('.zip', '.tar', '.tgz', '.gz', '.xz', '.bz2', '.7z', '.run', '.deb')
TEXT = ('.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.conf')
VERSION_LINE = re.compile(r'\b(mck|firmware|controller|sdk|version|release|build)\b[^\r\n]{0,60}?\b(v?\d+\.\d+(?:\.\d+){0,3})\b', re.I)

def sensitive(name):
    return name.startswith('.') or bool(SECRET.search(name)) or name.lower().endswith(('.pem', '.key', '.p12', '.pfx'))

def kind(path):
    name = path.name.lower()
    if name.endswith(ARCHIVE): return 'archive_or_installer_unopened'
    if 'booster_robotics_sdk' in name: return 'sdk_not_motion_core'
    if 'webots_interface' in name: return 'simulation_interface_candidate'
    if re.search(r'(^|[._-])mck([._-]|$)', name): return 'motion_core_candidate'
    if name.endswith(('.onnx', '.pt', '.pth', '.tflite', '.engine')): return 'policy_candidate'
    if any(x in name for x in ('version', 'manifest', 'release')): return 'version_metadata_candidate'
    if name.endswith(TEXT): return 'configuration_candidate'
    if '.so' in name: return 'shared_library_candidate'
    return None

def elf_header(data):
    if data[:4] != b'\x7fELF': return None
    if len(data) < 20 or data[4] not in (1, 2) or data[5] not in (1, 2):
        return {'status': 'invalid_or_truncated_header'}
    machine = struct.unpack('<H' if data[5] == 1 else '>H', data[18:20])[0]
    return {'status': 'header_only', 'bits': 32 if data[4] == 1 else 64,
            'endianness': 'little' if data[5] == 1 else 'big', 'machine': machine,
            'architecture': {3: 'x86', 40: 'arm', 62: 'x86_64', 183: 'aarch64'}.get(machine, 'unknown')}

def bounded_capture(argv, pass_fds=(), limit=1048576, timeout=5):
    """Capture at most limit bytes; terminate/reap on output or wall-time limit."""
    proc = subprocess.Popen(argv, pass_fds=pass_fds, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'})
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        os.set_blocking(proc.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 'timeout', b''
                if not selector.select(remaining):
                    return 'timeout', b''
                # One sentinel byte distinguishes exactly-at-limit from overflow.
                chunk = os.read(proc.stdout.fileno(), min(65536, limit - len(output) + 1))
                if not chunk:
                    break
                if len(output) + len(chunk) > limit:
                    return 'output_limit', b''
                output.extend(chunk)
        try:
            code = proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return 'timeout', b''
        return ('ok', bytes(output)) if code == 0 else ('failed', b'')
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()  # Always reap, including timeout, overflow, and exceptions.
        proc.stdout.close()


def dependencies(fd):
    # Never use ldd, the input executable, a shell, or a package-provided readelf.
    reader = next((p for p in ('/usr/bin/readelf', '/bin/readelf') if os.path.isfile(p) and os.access(p, os.X_OK)), None)
    if not reader: return {'status': 'readelf_unavailable', 'needed': []}
    try:
        status, output = bounded_capture([reader, '-d', '--', '/proc/self/fd/' + str(fd)], pass_fds=(fd,))
        if status != 'ok':
            return {'status': 'readelf_' + status, 'needed': []}
        # Never report a partial dependency list as complete.
        names = re.findall(r'\(NEEDED\).*?\[([^\]\n]{1,256})\]', output.decode('utf8', 'replace'))
        return {'status': 'readelf_ok', 'needed': sorted(set(names))}
    except OSError:
        return {'status': 'readelf_failed', 'needed': []}

def open_directory(root, relative):
    """Walk anchored directory descriptors, rejecting symlink replacements."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (*root.parts[1:], *relative.parts):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def inspect(root, max_entries=10000, max_depth=12, max_file_bytes=512*1024*1024,
            max_total_bytes=2*1024*1024*1024, use_readelf=True):
    root = Path(root).absolute()
    # Refuse symlinks anywhere in the supplied root and refuse broad/home scans.
    for p in (root, *root.parents):
        if p.is_symlink(): raise ValueError('root must not contain symlink components')
    if not root.is_dir(): raise ValueError('root must be a selected unpacked package directory')
    if root in (Path('/'), Path('/home'), Path('/root'), Path('/etc'), Path('/usr'), Path('/var'), Path('/proc'), Path('/sys'), Path('/dev'), Path.home()) or any(sensitive(p) for p in root.parts[1:]):
        raise ValueError('broad or sensitive root refused')
    if min(max_entries, max_file_bytes, max_total_bytes) <= 0 or max_depth < 0:
        raise ValueError('limits must be positive (depth may be zero)')
    report = {'schema_version': SCHEMA_VERSION, 'native_1_6_availability': 'unknown',
              'artifacts': [], 'exclusions': {}, 'complete': True,
              'limits': dict(max_entries=max_entries, max_depth=max_depth,
                             max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes),
              'notes': ['Names and version claims are evidence, not authenticity or same-build proof.',
                        'SDK architecture never establishes motion-core availability.',
                        'Archives/installers are hashed but never unpacked or executed.']}
    exclusions = Counter(); seen = 0; total = 0
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        dirfd = None
        try:
            # Bound memory as well as traversal: do not list/sort arbitrary directories.
            dirfd = open_directory(root, directory.relative_to(root))
            with os.scandir(dirfd) as entries:
                for entry in entries:
                    seen += 1
                    if seen > max_entries:
                        exclusions['entry_limit'] += 1; report['complete'] = False; stack.clear(); break
                    if sensitive(entry.name): exclusions['sensitive_name'] += 1; continue
                    if entry.is_symlink(): exclusions['symlink'] += 1; continue
                    path = directory / entry.name
                    if entry.is_dir(follow_symlinks=False):
                        if depth < max_depth: stack.append((path, depth + 1))
                        else: exclusions['depth_limit'] += 1; report['complete'] = False
                        continue
                    category = kind(path)
                    if category is None: exclusions['unselected_name'] += 1; continue
                    try:
                        # O_NONBLOCK avoids blocking on a FIFO; regular-file check precedes read.
                        fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
                        with os.fdopen(fd, 'rb') as handle:
                            info = os.fstat(handle.fileno())
                            if not stat.S_ISREG(info.st_mode): exclusions['nonregular'] += 1; continue
                            if info.st_size > max_file_bytes or total + info.st_size > max_total_bytes:
                                exclusions['byte_limit'] += 1; report['complete'] = False; continue
                            digest = hashlib.sha256(); head = b''; consumed = 0
                            while True:
                                chunk = handle.read(min(1048576, max_file_bytes - consumed + 1))
                                if not chunk: break
                                consumed += len(chunk)
                                if consumed > max_file_bytes or total + consumed > max_total_bytes:
                                    raise ValueError('file grew beyond limit')
                                if len(head) < 65536: head += chunk[:65536-len(head)]
                                digest.update(chunk)
                            total += consumed
                            after = os.fstat(handle.fileno())
                            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                exclusions['changed_during_read'] += 1; report['complete'] = False; continue
                            item = {'path': path.relative_to(root).as_posix(), 'kind': category,
                                    'size_bytes': consumed, 'sha256': digest.hexdigest()}
                            elf = elf_header(head)
                            if elf is not None:
                                item['elf'] = elf
                                item['dynamic'] = dependencies(handle.fileno()) if use_readelf else {'status': 'disabled', 'needed': []}
                            # No binary string mining. Only explicit metadata text, numeric claims, no full lines.
                            if category == 'version_metadata_candidate' and b'\x00' not in head:
                                claims = []
                                for line_no, line in enumerate(head.decode('utf8', 'replace').splitlines(), 1):
                                    for m in VERSION_LINE.finditer(line):
                                        claims.append({'line': line_no, 'label': m[1].lower(), 'value': m[2]})
                                item['version_claims'] = claims
                                item['version_scan_truncated'] = consumed > len(head)
                            report['artifacts'].append(item)
                    except (OSError, ValueError):
                        exclusions['unreadable_or_changed'] += 1; report['complete'] = False
        except OSError:
            exclusions['directory_unreadable'] += 1; report['complete'] = False
        finally:
            if dirfd is not None: os.close(dirfd)
    report['artifacts'].sort(key=lambda x: x['path'])
    report['exclusions'] = dict(sorted(exclusions.items()))
    report['bytes_hashed'] = total
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', help='selected unpacked package directory only')
    parser.add_argument('--no-readelf', action='store_true')
    parser.add_argument('--max-entries', type=int, default=10000)
    parser.add_argument('--max-depth', type=int, default=12)
    parser.add_argument('--max-file-bytes', type=int, default=512*1024*1024)
    parser.add_argument('--max-total-bytes', type=int, default=2*1024*1024*1024)
    args = vars(parser.parse_args()); args['use_readelf'] = not args.pop('no_readelf')
    try: print(json.dumps(inspect(**args), indent=2, sort_keys=True))
    except ValueError as error: parser.error(str(error))

if __name__ == '__main__': main()
