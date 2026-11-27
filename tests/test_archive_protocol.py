# archive and protocol tests

import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamsort.helpers import archive  # noqa: E402
from dreamsort.platform import protocol  # noqa: E402


class ZipTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ds_zip_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _make(self, entries):
        path = os.path.join(self.root, "a.zip")
        with zipfile.ZipFile(path, "w") as handle:
            for name, body in entries:
                handle.writestr(name, body)
        return path

    def test_extracts_with_progress(self):
        calls = []
        path = self._make([("romfs/a.bin", b"x"), ("manifest.txt", b"id=me/mod")])
        archive.safe_extract(path, os.path.join(self.root, "out"),
                             progress=lambda done, total: calls.append(done))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "out", "romfs", "a.bin")))
        self.assertEqual(calls[-1], 2)

    def test_traversal_is_refused(self):
        path = self._make([("../escape.txt", b"x")])
        with self.assertRaises(archive.ArchiveSafetyError):
            archive.safe_extract(path, os.path.join(self.root, "out"))

    def test_executable_is_refused(self):
        path = self._make([("tool.exe", b"MZ")])
        with self.assertRaises(archive.ArchiveSafetyError):
            archive.safe_extract(path, os.path.join(self.root, "out"))


@unittest.skipUnless(archive.PY7ZR_SUPPORT, "py7zr not installed")
class SevenZipTests(unittest.TestCase):
    # py7zr >= 0.21 refuses a plain function as callback
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ds_7z_")
        self.source = os.path.join(self.root, "src")
        os.makedirs(os.path.join(self.source, "romfs"))
        with open(os.path.join(self.source, "romfs", "a.bin"), "wb") as handle:
            handle.write(b"payload")
        self.path = os.path.join(self.root, "a.7z")
        with archive.py7zr.SevenZipFile(self.path, "w") as handle:
            handle.writeall(self.source, "mod")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_extracts_with_progress(self):
        calls = []
        archive.safe_extract(self.path, os.path.join(self.root, "out"),
                             progress=lambda done, total: calls.append(
                                 (done, total)))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "out", "mod", "romfs", "a.bin")))
        self.assertEqual(calls[-1], (1, 1))

    def test_extracts_without_progress(self):
        archive.safe_extract(self.path, os.path.join(self.root, "out2"))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "out2", "mod")))


class ProtocolTests(unittest.TestCase):
    def test_command_uses_absolute_script(self):
        # a browser click runs with a foreign cwd, -m dreamsort would fail
        command = protocol._launch_command()
        self.assertIn('"%1"', command)
        self.assertTrue(os.path.isabs(protocol._launch_targets()[0]))

    def test_source_command_points_at_existing_files(self):
        if getattr(sys, "frozen", False):
            self.skipTest("frozen build")
        for path in protocol._launch_targets():
            self.assertTrue(os.path.exists(path), path)


if __name__ == "__main__":
    unittest.main()
