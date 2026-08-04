from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import check_release_alignment


class ReleaseAlignmentTests(unittest.TestCase):
    def _manifest(self, version: str) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "manifest.json"
        path.write_text(f'{{"version": "{version}"}}', encoding="utf-8")
        return path

    def test_matching_tag_passes(self) -> None:
        result = check_release_alignment.check_alignment("v1.3.0", self._manifest("1.3.0"))
        self.assertTrue(result.ok)
        self.assertEqual(result.expected_tag, "v1.3.0")

    def test_mismatched_tag_fails(self) -> None:
        result = check_release_alignment.check_alignment("v1.2.9", self._manifest("1.3.0"))
        self.assertFalse(result.ok)
        self.assertIn("does not match", result.message)

    def test_malformed_tag_fails(self) -> None:
        result = check_release_alignment.check_alignment("1.3.0", self._manifest("1.3.0"))
        self.assertFalse(result.ok)
        self.assertIn("must look like", result.message)


if __name__ == "__main__":
    unittest.main()
