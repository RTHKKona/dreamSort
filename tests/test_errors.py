# error system tests

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamsort.errors import (  # noqa: E402
    DreamSortError,
    ErrorCode,
    Severity,
    capture,
    error_guard,
    guard,
    spec,
)
from dreamsort import packs  # noqa: E402


class CatalogTests(unittest.TestCase):
    def test_starts_at_zero(self):
        self.assertEqual(int(ErrorCode.UNKNOWN), 0)

    def test_pixelpack_is_1337(self):
        self.assertEqual(int(ErrorCode.PIXELPACK_DETECTED), 1337)

    def test_codes_are_unique(self):
        values = [int(code) for code in ErrorCode]
        self.assertEqual(len(values), len(set(values)))

    def test_every_code_has_a_spec(self):
        for code in ErrorCode:
            message, severity, retryable = spec(code)
            self.assertTrue(message)
            self.assertIn(severity, (Severity.INFO, Severity.WARNING,
                                     Severity.ERROR, Severity.CRITICAL))
            self.assertIsInstance(retryable, bool)


class ExceptionTests(unittest.TestCase):
    def test_str_carries_number(self):
        err = DreamSortError(ErrorCode.PIXELPACK_DETECTED,
                             context="HD Pixel Pack")
        self.assertEqual(err.number, 1337)
        self.assertTrue(str(err).startswith("[E1337]"))
        self.assertIn("HD Pixel Pack", str(err))

    def test_severity_property(self):
        self.assertEqual(
            DreamSortError(ErrorCode.PIXELPACK_DETECTED).severity,
            Severity.WARNING)

    def test_capture_builtin_mapping(self):
        self.assertEqual(capture(ValueError("x")).code,
                         ErrorCode.INVALID_ARGUMENT)
        self.assertEqual(capture(FileNotFoundError("x")).code,
                         ErrorCode.PATH_NOT_FOUND)

    def test_capture_passthrough_and_chain(self):
        original = DreamSortError(ErrorCode.DISK_FULL)
        self.assertIs(capture(original), original)

        wrapped = capture(PermissionError("x"))
        self.assertEqual(wrapped.code, ErrorCode.ACCESS_DENIED)
        self.assertIsInstance(wrapped.__cause__, PermissionError)
        self.assertTrue(wrapped.traceback_text)


class PixelpackTests(unittest.TestCase):
    def _finding(self):
        return {
            "id": "hd_pixel_pack",
            "name": "HD Pixel Pack",
            "score": 8,
            "signals": ["component: HD Textures v2"],
            "where": "E:\\mods",
            "note": "a repack",
        }

    def test_pixelpack_error(self):
        err = packs.pixelpack_error(self._finding())
        self.assertEqual(err.code, ErrorCode.PIXELPACK_DETECTED)
        self.assertEqual(err.number, 1337)
        self.assertIn("HD Pixel Pack", str(err))
        self.assertTrue(str(err).startswith("[E1337]"))

    def test_assert_clean_raises(self):
        # monkeypatch the scan to avoid touching the filesystem
        packs.scan_inputs = lambda _items: [self._finding()]
        with self.assertRaises(DreamSortError) as raised:
            packs.assert_clean(["whatever"])
        self.assertEqual(raised.exception.code,
                         ErrorCode.PIXELPACK_DETECTED)


class GuardTests(unittest.TestCase):
    def test_decorator_swallows(self):
        seen = []

        @guard(on_error=seen.append, reraise=False)
        def risky():
            raise RuntimeError("boom")

        self.assertIsNone(risky())
        self.assertEqual(seen[0].code, ErrorCode.UNKNOWN)

    def test_decorator_reraises_normalized(self):
        @guard()
        def risky():
            raise ValueError("bad")

        with self.assertRaises(DreamSortError) as raised:
            risky()
        self.assertEqual(raised.exception.code, ErrorCode.INVALID_ARGUMENT)

    def test_context_guard_suppresses(self):
        seen = []
        with error_guard(on_error=seen.append):
            raise TimeoutError("slow")
        self.assertEqual(seen[0].code, ErrorCode.NETWORK_TIMEOUT)

    def test_context_guard_reraises(self):
        with self.assertRaises(FileNotFoundError):
            with error_guard(reraise=True):
                raise FileNotFoundError("missing")


if __name__ == "__main__":
    unittest.main()
