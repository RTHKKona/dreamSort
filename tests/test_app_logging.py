# file logging tests

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamsort import app_logging  # noqa: E402
from dreamsort.errors import DreamSortError, ErrorCode  # noqa: E402


class LoggingToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        app_logging.init_logging(True, log_dir=self.tmp)

    def test_enabled_writes_file(self):
        self.assertTrue(app_logging.is_enabled())
        app_logging.info("hello %s", "world")
        path = app_logging.log_path()
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("hello world", content)

    def test_disable_keeps_file_but_stops_writes(self):
        app_logging.warning("first")
        path = app_logging.log_path()
        size_before = os.path.getsize(path)

        app_logging.set_enabled(False)
        self.assertFalse(app_logging.is_enabled())
        app_logging.warning("after off")
        # handler detached; file stays on disk, no new content
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), size_before)

    def test_reenable_appends(self):
        app_logging.set_enabled(False)
        app_logging.set_enabled(True)
        self.assertTrue(app_logging.is_enabled())
        app_logging.info("back on")
        with open(app_logging.log_path(), encoding="utf-8") as handle:
            self.assertIn("back on", handle.read())

    def test_log_error_records_code(self):
        err = DreamSortError(ErrorCode.PIXELPACK_DETECTED, context="HD Pixel Pack")
        app_logging.log_error(err)
        with open(app_logging.log_path(), encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[E1337]", content)
        self.assertIn("Pixelpack", content)


if __name__ == "__main__":
    unittest.main()
