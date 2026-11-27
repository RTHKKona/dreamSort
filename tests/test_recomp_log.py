# recomp log analyzer tests

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamsort.analyzers import recomp_log  # noqa: E402

SAMPLE = """\
Starting MHGU Recomp
Loading mods...
ERROR: Failed to mount romfs: not found
Could not load plugin coolmod.nro: file missing
Vulkan device lost during frame
std::bad_alloc: out of memory
FATAL: unhandled exception, aborting
"""

EXPECTED_TITLES = [
    "Game data (romfs) not found",
    "Plugin (.nro) failed to load",
    "Graphics driver / GPU error",
    "Out of memory",
    "Recomp crashed",
]


class RecompLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write_log(self, text):
        path = os.path.join(self.tmp, recomp_log.LOG_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_missing_log(self):
        report = recomp_log.analyze(self.tmp)
        self.assertFalse(report["found"])
        self.assertTrue(report["path"].endswith(recomp_log.LOG_NAME))

    def test_patterns_map_to_titles(self):
        self._write_log(SAMPLE)
        report = recomp_log.analyze(self.tmp)
        self.assertTrue(report["found"])
        titles = [f["title"] for f in report["findings"]]
        self.assertEqual(titles, EXPECTED_TITLES)

    def test_each_finding_has_suggestion(self):
        self._write_log(SAMPLE)
        report = recomp_log.analyze(self.tmp)
        for finding in report["findings"]:
            self.assertTrue(finding["suggestion"])
            self.assertTrue(finding["line"])
            self.assertIn(finding["severity"],
                          ("info", "warning", "error", "critical"))

    def test_clean_log_no_findings(self):
        self._write_log("Everything is fine\nMods loaded\n")
        report = recomp_log.analyze(self.tmp)
        self.assertTrue(report["found"])
        self.assertEqual(report["findings"], [])
        self.assertIn("No obvious problems", report["summary"])


if __name__ == "__main__":
    unittest.main()
