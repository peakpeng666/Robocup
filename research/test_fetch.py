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

    def test_missing_length_and_redirected_pdf_response(self):
        response = Response()
        response.geturl = lambda: 'https://cdn.example.org/paper.pdf'
        self.assertEqual(self.run_main(response=response), (0, 1))
        self.assertEqual((self.out / 'one.pdf').read_bytes(), PDF)

    def test_invalid_content_length_rejected(self):
        self.assertEqual(self.run_main(response=Response(length='invalid'))[0], 1)
        self.assertFalse((self.out / 'one.pdf').exists())
        self.assertFalse(list(self.out.glob('*.part')))

    def test_redirect_landing_on_html_is_not_success(self):
        response = Response(b'<html>' + b'captcha' * 2000)
        response.geturl = lambda: 'https://example.org/login'
        self.assertEqual(self.run_main(response=response)[0], 1)
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

    def test_complete_but_untrusted_legacy_pdf_is_redownloaded(self):
        self.out.mkdir()
        (self.out / 'one.pdf').write_bytes(PDF)
        self.assertEqual(self.run_main(), (0, 1))

    def test_middle_corruption_or_wrong_complete_pdf_is_redownloaded(self):
        self.assertEqual(self.run_main(), (0, 1))
        changed = PDF[:100] + b'CORRUPT' + PDF[107:]
        (self.out / 'one.pdf').write_bytes(changed)
        self.assertEqual(self.run_main(), (0, 1))
        self.assertEqual((self.out / 'one.pdf').read_bytes(), PDF)

    def test_changed_source_invalidates_cache(self):
        self.run_main()
        self.write_manifest([dict(self.item, url='https://example.org/updated.pdf')])
        self.assertEqual(self.run_main(), (0, 1))

    def test_malformed_receipt_redownloads(self):
        self.run_main()
        fetch.receipt_path(self.out / 'one.pdf').write_text('not JSON')
        self.assertEqual(self.run_main(), (0, 1))

    def test_failed_new_source_preserves_old_pdf_and_receipt(self):
        self.run_main()
        dest = self.out / 'one.pdf'
        receipt = fetch.receipt_path(dest).read_bytes()
        self.write_manifest([dict(self.item, url='https://example.org/updated.pdf')])
        self.assertEqual(self.run_main(response=Response(interrupted=True))[0], 1)
        self.assertEqual(dest.read_bytes(), PDF)
        self.assertEqual(fetch.receipt_path(dest).read_bytes(), receipt)

    def test_receipt_publish_failure_is_nonzero_and_cache_is_not_trusted(self):
        self.run_main()
        dest = self.out / 'one.pdf'
        old_receipt = fetch.receipt_path(dest).read_bytes()
        self.write_manifest([dict(self.item, url='https://example.org/updated.pdf')])
        new_pdf = PDF.replace(b'x', b'y')
        original_replace = fetch.os.replace
        def replace(source, target):
            if Path(target) == fetch.receipt_path(dest):
                raise OSError('simulated receipt rename failure')
            original_replace(source, target)
        with patch.object(fetch.os, 'replace', side_effect=replace):
            self.assertEqual(self.run_main(response=Response(new_pdf))[0], 1)
        # Publication is not a two-file transaction: PDF can be new, receipt old.
        self.assertEqual(dest.read_bytes(), new_pdf)
        self.assertEqual(fetch.receipt_path(dest).read_bytes(), old_receipt)
        self.assertFalse(list(self.out.glob('*.part')))
        self.assertEqual(self.run_main(), (0, 1))
        self.assertEqual(self.run_main(), (0, 0))

    def test_interleaved_publish_never_trusts_mismatched_receipt(self):
        self.out.mkdir()
        dest = self.out / 'one.pdf'
        other_pdf = PDF.replace(b'x', b'y')
        original_replace = fetch.os.replace
        concurrent_once = [False]
        def replace(source, target):
            original_replace(source, target)
            if Path(target) == dest and not concurrent_once[0]:
                concurrent_once[0] = True
                # Another writer finishes between this writer's PDF and receipt.
                dest.write_bytes(other_pdf)
                fetch.receipt_path(dest).write_text(json.dumps({'url': self.item['url'], 'sha256': fetch.checksum(dest)}))
        with patch.object(fetch.os, 'replace', side_effect=replace):
            self.assertEqual(self.run_main(), (0, 1))
        self.assertEqual(self.run_main(), (0, 1))
        self.assertEqual(dest.read_bytes(), PDF)
        self.assertEqual(self.run_main(), (0, 0))
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
