"""End-to-end checks for the tooling .run package; only the standard library."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT / "release" / "build_run.py"
SHEBANG = b"#!/usr/bin/env python3\n"


@unittest.skipUnless(os.name == "posix", "The .run installation target is Linux/POSIX")
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="k1-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.source = self.directory / "source"
        self.source.mkdir()
        self.root = self.directory / "installed"
        files = {
            "README.md": "Research tooling, version one.\n",
            "k1lab/__init__.py": 'VERSION = "one"\n',
            "configs/example.json": '{"mode": "simulation"}\n',
            "docs/intro.md": "Tooling only.\n",
            "tools/show_version.py": 'print("one")\n',
            "sources.lock.json": '{"schema_version": 1, "sources": []}\n',
        }
        for name, contents in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

    def build(self, version="0.1.0", *, filename=None, success=True):
        output = self.directory / (filename or f"tooling-{version}.run")
        completed = subprocess.run(
            [sys.executable, str(BUILDER), "--source", str(self.source),
             "--output", str(output), "--version", version],
            cwd=self.directory, capture_output=True, text=True, timeout=20,
        )
        if success:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(os.access(output, os.X_OK))
            metadata = json.loads(completed.stdout)
            self.assertEqual(metadata["artifact_kind"], "tooling")
            self.assertFalse(metadata["contains_trained_policy"])
            self.assertFalse(metadata["robot_flash_supported"])
            self.assertEqual(metadata["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        return output, completed

    def run_package(self, package, *args, success=True):
        # Execute the file directly to exercise the shebang and executable mode.
        completed = subprocess.run(
            [str(package), *args], cwd=self.directory,
            capture_output=True, text=True, timeout=20,
        )
        if success:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            metadata = json.loads(completed.stdout)
            self.assertEqual(metadata["artifact_kind"], "tooling")
            self.assertFalse(metadata["contains_trained_policy"])
            self.assertFalse(metadata["robot_flash_supported"])
            self.assertEqual(metadata["checksum_role"], "integrity_only_not_signature")
        else:
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return completed

    def rewrite(self, package, name, transform=None, append=()):
        output = self.directory / name
        with zipfile.ZipFile(package) as archive:
            members = [(copy.copy(info), archive.read(info)) for info in archive.infolist()]
        with output.open("wb") as stream:
            stream.write(SHEBANG)
            with zipfile.ZipFile(stream, "w") as archive:
                for info, data in members:
                    if transform:
                        info, data = transform(info, data)
                    archive.writestr(info, data)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    for info, data in append:
                        archive.writestr(info, data)
        output.chmod(0o755)
        return output

    def install_two_versions(self):
        one, _ = self.build()
        self.run_package(one, "--install-root", str(self.root))
        (self.source / "README.md").write_text("Research tooling, version two.\n", encoding="utf-8")
        two, _ = self.build("0.2.0")
        self.run_package(two, "--install-root", str(self.root))
        return one, two

    def test_verify_install_upgrade_and_rollback(self):
        one, _ = self.build()
        result = self.run_package(one, "--verify")
        self.assertEqual(json.loads(result.stdout)["status"], "verified")
        self.assertFalse(self.root.exists())
        self.run_package(one, "--install-root", str(self.root))
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.1.0")
        self.assertFalse((self.root / "previous").exists())
        old_contents = (self.root / "current" / "README.md").read_bytes()
        (self.source / "README.md").write_text("Research tooling, version two.\n", encoding="utf-8")
        two, _ = self.build("0.2.0")
        self.run_package(two, "--install-root", str(self.root))
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.2.0")
        self.assertEqual(os.readlink(self.root / "previous"), "releases/0.1.0")
        self.assertNotEqual((self.root / "current" / "README.md").read_bytes(), old_contents)
        result = self.run_package(two, "--rollback", "--install-root", str(self.root))
        self.assertEqual(json.loads(result.stdout)["status"], "rolled_back")
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.1.0")
        self.assertEqual(os.readlink(self.root / "previous"), "releases/0.2.0")
        self.assertEqual((self.root / "current" / "README.md").read_bytes(), old_contents)

    def test_identical_install_is_idempotent(self):
        one, two = self.install_two_versions()
        self.run_package(two, "--install-root", str(self.root))
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.2.0")
        self.assertEqual(os.readlink(self.root / "previous"), "releases/0.1.0")

    def test_relative_install_root_is_rejected(self):
        package, _ = self.build()
        result = self.run_package(package, "--install-root", "relative-root", success=False)
        self.assertIn("absolute", result.stderr)
        self.assertFalse((self.directory / "relative-root").exists())

    def test_existing_non_project_directory_is_untouched(self):
        package, _ = self.build()
        self.root.mkdir()
        user_file = self.root / "my-notes.txt"
        user_file.write_text("keep me", encoding="utf-8")
        result = self.run_package(package, "--install-root", str(self.root), success=False)
        self.assertIn("non-project", result.stderr)
        self.assertEqual(user_file.read_text(encoding="utf-8"), "keep me")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"my-notes.txt"})

    def test_existing_empty_directory_is_also_protected(self):
        package, _ = self.build()
        self.root.mkdir()
        self.run_package(package, "--install-root", str(self.root), success=False)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_payload_corruption_is_rejected_and_old_current_survives(self):
        one, _ = self.build()
        self.run_package(one, "--install-root", str(self.root))
        two, _ = self.build("0.2.0")

        def damage(info, data):
            return info, b"X" * len(data) if info.filename == "payload/README.md" else data

        broken = self.rewrite(two, "broken.run", transform=damage)
        result = self.run_package(broken, "--install-root", str(self.root), success=False)
        self.assertIn("SHA-256", result.stderr)
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.1.0")
        self.assertFalse((self.root / "releases" / "0.2.0").exists())

    def test_manifest_digest_corruption_is_rejected(self):
        package, _ = self.build()

        def damage(info, data):
            return info, (b"0" * 64 + b"\n") if info.filename == "manifest.sha256" else data

        broken = self.rewrite(package, "manifest-broken.run", transform=damage)
        result = self.run_package(broken, "--verify", success=False)
        self.assertIn("Manifest SHA-256", result.stderr)

    def test_self_consistent_non_tooling_manifest_is_rejected(self):
        package, _ = self.build()
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        manifest["artifact_kind"] = "robot_firmware"
        changed = json.dumps(manifest, sort_keys=True).encode("utf-8")

        def change_metadata(info, data):
            if info.filename == "manifest.json":
                data = changed
            elif info.filename == "manifest.sha256":
                data = (hashlib.sha256(changed).hexdigest() + "\n").encode("ascii")
            return info, data

        broken = self.rewrite(package, "not-tooling.run", transform=change_metadata)
        result = self.run_package(broken, "--install-root", str(self.root), success=False)
        self.assertIn("tooling-only", result.stderr)
        self.assertFalse(self.root.exists())

    def test_wrong_payload_size_is_rejected(self):
        package, _ = self.build()

        def damage(info, data):
            return info, data + b"extra" if info.filename == "payload/README.md" else data

        broken = self.rewrite(package, "size-broken.run", transform=damage)
        result = self.run_package(broken, "--verify", success=False)
        self.assertIn("size", result.stderr.lower())

    def test_duplicate_zip_entry_is_rejected(self):
        package, _ = self.build()
        duplicate = zipfile.ZipInfo("payload/README.md")
        broken = self.rewrite(package, "duplicate.run", append=[(duplicate, b"duplicate")])
        result = self.run_package(broken, "--verify", success=False)
        self.assertIn("Duplicate ZIP", result.stderr)

    def test_zip_path_traversal_is_rejected(self):
        package, _ = self.build()
        traversal = zipfile.ZipInfo("payload/../../escaped")
        broken = self.rewrite(package, "traversal.run", append=[(traversal, b"bad")])
        result = self.run_package(broken, "--install-root", str(self.root), success=False)
        self.assertIn("Unsafe archive path", result.stderr)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.directory / "escaped").exists())

    def test_zip_symlink_is_rejected(self):
        package, _ = self.build()

        def replace_with_symlink(info, data):
            if info.filename == "payload/README.md":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                data = b"/tmp/unrelated"
            return info, data

        broken = self.rewrite(package, "symlink.run", transform=replace_with_symlink)
        result = self.run_package(broken, "--verify", success=False)
        self.assertIn("symlink", result.stderr.lower())

    def test_source_symlink_is_rejected(self):
        outside = self.directory / "outside.py"
        outside.write_text("do not package me", encoding="utf-8")
        (self.source / "k1lab" / "linked.py").symlink_to(outside)
        output, result = self.build(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(output.exists())

    def test_install_root_symlink_is_rejected(self):
        package, _ = self.build()
        other = self.directory / "other"
        other.mkdir()
        self.root.symlink_to(other, target_is_directory=True)
        result = self.run_package(package, "--install-root", str(self.root), success=False)
        self.assertIn("Symlink", result.stderr)
        self.assertEqual(list(other.iterdir()), [])

    def test_version_collision_does_not_replace_old_release(self):
        one, _ = self.build()
        self.run_package(one, "--install-root", str(self.root))
        original = (self.root / "current" / "README.md").read_bytes()
        (self.source / "README.md").write_text("changed under the same version", encoding="utf-8")
        collision, _ = self.build(filename="collision.run")
        result = self.run_package(collision, "--install-root", str(self.root), success=False)
        self.assertIn("overwrite an existing version", result.stderr)
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.1.0")
        self.assertEqual((self.root / "current" / "README.md").read_bytes(), original)

    def test_concurrent_installation_lock_is_respected(self):
        import fcntl

        one, _ = self.build()
        self.run_package(one, "--install-root", str(self.root))
        two, _ = self.build("0.2.0")
        with (self.root / ".install.lock").open("r+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_package(two, "--install-root", str(self.root), success=False)
        self.assertIn("installation lock", result.stderr)
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.1.0")

    def test_damaged_previous_version_cannot_be_activated(self):
        _, two = self.install_two_versions()
        (self.root / "releases" / "0.1.0" / "README.md").write_text("damaged", encoding="utf-8")
        result = self.run_package(two, "--rollback", "--install-root", str(self.root), success=False)
        self.assertIn("SHA-256", result.stderr)
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.2.0")

    def test_commit_io_failure_preserves_current_and_previous(self):
        self.install_two_versions()
        third, _ = self.build("0.3.0")
        spec = importlib.util.spec_from_file_location("k1_test_installer", PROJECT / "release" / "installer.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        original_replace = os.replace

        def fail_commit(source, destination):
            if Path(destination) == self.root / "current":
                raise OSError("simulated current-pointer commit failure")
            return original_replace(source, destination)

        with zipfile.ZipFile(third) as archive:
            manifest, raw = installer.verify_archive(archive)
            with mock.patch.object(installer.os, "replace", side_effect=fail_commit):
                with self.assertRaisesRegex(OSError, "simulated current-pointer"):
                    installer.install(archive, manifest, raw, self.root)
        self.assertEqual(os.readlink(self.root / "current"), "releases/0.2.0")
        self.assertEqual(os.readlink(self.root / "previous"), "releases/0.1.0")
        self.assertFalse(list((self.root / "releases").glob(".staging-*")))

    def test_regular_file_at_current_is_not_overwritten(self):
        one, _ = self.build()
        self.run_package(one, "--install-root", str(self.root))
        (self.root / "current").unlink()
        (self.root / "current").write_text("unrelated file", encoding="utf-8")
        two, _ = self.build("0.2.0")
        result = self.run_package(two, "--install-root", str(self.root), success=False)
        self.assertIn("non-symlink", result.stderr)
        self.assertEqual((self.root / "current").read_text(encoding="utf-8"), "unrelated file")

    def test_allowlist_and_reproducible_build(self):
        for relative in ("release/secret.py", "tests/private.txt", "downloaded/large-source.txt", "k1lab/__pycache__/ignored.pyc"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not in payload", encoding="utf-8")
        one, _ = self.build(filename="one.run")
        two, _ = self.build(filename="two.run")
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with zipfile.ZipFile(one) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(set(manifest["files"]), {
            "README.md", "k1lab/__init__.py", "configs/example.json",
            "docs/intro.md", "tools/show_version.py", "sources.lock.json",
        })


if __name__ == "__main__":
    unittest.main()
