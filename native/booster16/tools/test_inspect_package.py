import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import inspect_package as tool

class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='booster-inspect-')
        self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    def scan(self, **kw): return tool.inspect(self.root, use_readelf=False, **kw)
    def test_header_hash_and_sdk_is_not_core(self):
        data = bytearray(64); data[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', data, 18, 183)
        self.write('mck', data)
        self.write('lib/x86_64/libbooster_robotics_sdk.a', b'SDK')
        r = self.scan(); self.assertEqual(r['native_1_6_availability'], 'unknown')
        core = next(x for x in r['artifacts'] if x['path'] == 'mck')
        self.assertEqual(core['elf']['architecture'], 'aarch64')
        self.assertEqual(core['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(r['artifacts'][0]['kind'], 'sdk_not_motion_core')
    def test_archives_are_not_unpacked_or_executed(self):
        self.write('booster-runner-full-webots-k1-1.6.run', b'#!/bin/sh\ntouch NEVER\n')
        with patch.object(tool.subprocess, 'run', side_effect=AssertionError('execution')):
            r = tool.inspect(self.root)
        self.assertEqual(len(r['artifacts']), 1)
        self.assertEqual(r['artifacts'][0]['kind'], 'archive_or_installer_unopened')
        self.assertFalse((self.root / 'NEVER').exists())
    def test_symlinks_sensitive_files_and_unrelated_excluded(self):
        self.write('secret-config.json', b'private')
        self.write('.aws/credentials', b'private')
        self.write('id_rsa', b'private'); self.write('unrelated.txt', b'unrelated')
        (self.root / 'mck').symlink_to('/etc/passwd')
        (self.root / 'outside').symlink_to('/etc', target_is_directory=True)
        r = self.scan(); self.assertEqual(r['artifacts'], [])
        self.assertEqual(r['exclusions']['symlink'], 2)
        self.assertNotIn('private', str(r))
    def test_plural_credential_names_excluded_without_content_read(self):
        for name in ('credentials.json', 'secrets.yaml', 'tokens.json', 'passwords.cfg'):
            self.write(name, b'sensitive content')
        with patch.object(tool.os, 'open', side_effect=AssertionError('file open')):
            # Test the predicate directly under the strict no-read assertion.
            for name in ('credentials.json', 'secrets.yaml', 'tokens.json', 'passwords.cfg'):
                self.assertTrue(tool.sensitive(name))
        report = self.scan()
        self.assertEqual(report['artifacts'], [])
        self.assertEqual(report['exclusions']['sensitive_name'], 4)
    def test_version_is_explicit_metadata_only(self):
        self.write('VERSION.txt', b'mck version: 1.6.0.10\nsdk: 1.3.6\n')
        self.write('mck-1.6.0.10', b'firmware 9.9.9')
        r = self.scan(); v = next(x for x in r['artifacts'] if x['path']=='VERSION.txt')
        self.assertEqual(v['version_claims'][0]['value'], '1.6.0.10')
        self.assertNotIn('version_claims', r['artifacts'][1])
        self.assertEqual(r['native_1_6_availability'], 'unknown')
    def test_limits(self):
        self.write('a/mck', b'12345')
        self.assertFalse(self.scan(max_depth=0)['complete'])
        self.assertFalse(self.scan(max_file_bytes=4)['complete'])
        self.write('mck', b'12345')
        self.assertFalse(self.scan(max_entries=1)['complete'])
        self.assertFalse(self.scan(max_total_bytes=5)['complete'])
    def test_root_symlink_and_invalid_limits(self):
        (self.root/'linked').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): tool.inspect(self.root/'linked')
        with self.assertRaises(ValueError): self.scan(max_entries=0)
        with self.assertRaises(ValueError): tool.inspect('/')
    def test_nonregular(self):
        os.mkfifo(self.root/'mck')
        self.assertEqual(self.scan()['exclusions']['nonregular'], 1)
    def test_header_edge_cases(self):
        self.assertIsNone(tool.elf_header(b'not elf'))
        self.assertEqual(tool.elf_header(b'\x7fELF')['status'], 'invalid_or_truncated_header')
        h=bytearray(64); h[:6]=b'\x7fELF\x02\x02'; struct.pack_into('>H',h,18,62)
        self.assertEqual(tool.elf_header(h)['architecture'], 'x86_64')
    def test_capture_output_limit_reaps_process(self):
        launched = []
        real_popen = subprocess.Popen
        def record(*args, **kwargs):
            proc = real_popen(*args, **kwargs); launched.append(proc); return proc
        # Controlled test code, never the inspected artifact.
        with patch.object(tool.subprocess, 'Popen', side_effect=record):
            status, output = tool.bounded_capture(
                [sys.executable, '-c', 'import os; os.write(1, b"x"*2000000)'], limit=4096)
        self.assertEqual((status, output), ('output_limit', b''))
        self.assertIsNotNone(launched[0].returncode)
        self.assertTrue(launched[0].stdout.closed)
    def test_capture_stderr_also_bounded(self):
        status, output = tool.bounded_capture(
            [sys.executable, '-c', 'import os; os.write(2, b"x"*2000000)'], limit=4096)
        self.assertEqual((status, output), ('output_limit', b''))
    def test_capture_timeout(self):
        status, output = tool.bounded_capture(
            [sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.05)
        self.assertEqual((status, output), ('timeout', b''))
    def test_capture_exact_limit(self):
        status, output = tool.bounded_capture(
            [sys.executable, '-c', 'import os; os.write(1, b"x"*4096)'], limit=4096)
        self.assertEqual(status, 'ok'); self.assertEqual(len(output), 4096)
    def test_dependencies_never_return_partial_on_limit(self):
        with patch.object(tool, 'bounded_capture', return_value=('output_limit', b'(NEEDED) [partial.so]')):
            result = tool.dependencies(0)
        if result['status'] == 'readelf_unavailable': self.skipTest('host readelf unavailable')
        self.assertEqual(result, {'status': 'readelf_output_limit', 'needed': []})
    def test_readelf_host_binary_without_execution(self):
        reader = Path('/usr/bin/readelf')
        if not reader.exists(): self.skipTest('host readelf unavailable')
        with open(reader,'rb') as handle:
            result = tool.dependencies(handle.fileno())
        self.assertEqual(result['status'], 'readelf_ok')
        self.assertIsInstance(result['needed'], list)

if __name__ == '__main__': unittest.main()
