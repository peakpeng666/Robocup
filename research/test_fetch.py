"""Offline downloader regressions: python -m unittest discover -s research -p 'test_fetch.py'."""
import contextlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('research_fetch', Path(__file__).with_name('fetch.py'))
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
PDF = b'%PDF-1.7\n' + b'x' * 12000 + b'\n%%EOF\n'


class Response:
    def __init__(self, body=PDF, length=None, interrupted=False):
        self.body = body
        self.headers = {} if length is None else {'Content-Length': str(length)}
        self.interrupted = interrupted
        self.done = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, _size):
        if not self.done:
            self.done = True
            return self.body
        if self.interrupted:
            raise http.client.IncompleteRead(b'', 123)
        return b''


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'manifest.json'
        self.out = self.root / 'downloads'
        self.item = {'key': 'one', 'title': 'One', 'url': 'https://example.org/one.pdf', 'file': 'one.pdf'}
        self.write_manifest([self.item])
        self.patch = patch.multiple(fetch, MANIFEST=self.manifest, OUT=self.out)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write_manifest(self, items):
        self.manifest.write_text(json.dumps({'items': items}), encoding='utf-8')

    def run_main(self, args=(), response=None):
        with patch.object(fetch.urllib.request, 'urlopen', return_value=response or Response()) as op, contextlib.redirect_stdout(io.StringIO()):
            result = fetch.main(list(args))
        return result, op.call_count

    def test_success_and_valid_cached_skip(self):
        self.assertEqual(self.run_main(response=Response(length=len(PDF))), (0, 1))
        self.assertEqual((self.out / 'one.pdf').read_bytes(), PDF)
        self.assertEqual(self.run_main(), (0, 0))
        self.assertTrue((self.out / '.gitignore').exists())

    def test_interrupted_download_is_removed_and_retried(self):
        self.assertEqual(self.run_main(response=Response(interrupted=True))[0], 1)
        self.assertFalse((self.out / 'one.pdf').exists())
        self.assertFalse(list(self.out.glob('*.part')))
        self.assertEqual(self.run_main(), (0, 1))

    def test_html_and_truncated_pdf_rejected(self):
        for body in [b'<html>' + b'x'*12000, b'%PDF-1.7\n' + b'x'*12000, b'%PDF-1.7\n%%EOF']:
            with self.subTest(body=body[:10]):
                self.assertEqual(self.run_main(response=Response(body))[0], 1)
                self.assertFalse((self.out / 'one.pdf').exists())
                self.assertFalse(list(self.out.glob('*.part')))

    def test_wrong_content_length_rejected(self):
        self.assertEqual(self.run_main(response=Response(length=len(PDF)+1))[0], 1)
        self.assertFalse((self.out / 'one.pdf').exists())

    def test_legacy_partial_file_redownloaded(self):
        self.out.mkdir()
        (self.out / 'one.pdf').write_bytes(b'x'*11000)
        self.assertEqual(self.run_main(), (0, 1))
        self.assertEqual((self.out / 'one.pdf').read_bytes(), PDF)

    def test_failed_replacement_preserves_old_file(self):
        self.out.mkdir()
        old = b'old invalid file'
        (self.out / 'one.pdf').write_bytes(old)
        self.assertEqual(self.run_main(response=Response(interrupted=True))[0], 1)
        self.assertEqual((self.out / 'one.pdf').read_bytes(), old)
        self.assertFalse(list(self.out.glob('*.part')))

    def test_list_is_read_only(self):
        self.assertEqual(self.run_main(['--list']), (0, 0))
        self.assertFalse(self.out.exists())

    def test_invalid_cli_never_downloads(self):
        for args in [['--only'], ['--bogus'], ['--only', 'missing'], ['--list', '--only', 'one']]:
            with self.subTest(args=args), patch.object(fetch.urllib.request, 'urlopen') as op, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    fetch.main(args)
                self.assertEqual(raised.exception.code, 2)
                op.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_only_selects_one(self):
        other = dict(self.item, key='two', file='two.pdf')
        self.write_manifest([self.item, other])
        self.assertEqual(self.run_main(['--only', 'one']), (0, 1))
        self.assertFalse((self.out / 'two.pdf').exists())

    def test_unsafe_names_and_duplicate_keys_rejected(self):
        for items in [[dict(self.item, file='../escape.pdf')], [dict(self.item, file='..\\escape.pdf')], [self.item, self.item]]:
            self.write_manifest(items)
            self.assertEqual(self.run_main(), (1, 0))
        self.assertFalse(self.out.exists())

    def test_batch_failure_does_not_prevent_remaining_download(self):
        self.write_manifest([self.item, dict(self.item, key='two', file='two.pdf')])
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=[Response(b'<html>'+b'x'*12000), Response()]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch.main([]), 1)
        self.assertFalse((self.out / 'one.pdf').exists())
        self.assertEqual((self.out / 'two.pdf').read_bytes(), PDF)


if __name__ == '__main__':
    unittest.main()
