from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import check_release_alignment


CURRENT_VERSION = "1.3.1"


class ReleaseAlignmentTests(unittest.TestCase):
    def _manifest(self, version: str) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "manifest.json"
        path.write_text(f'{{"version": "{version}"}}', encoding="utf-8")
        return path

    def test_matching_tag_passes(self) -> None:
        result = check_release_alignment.check_alignment(
            f"v{CURRENT_VERSION}",
            self._manifest(CURRENT_VERSION),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.expected_tag, f"v{CURRENT_VERSION}")

    def test_mismatched_tag_fails(self) -> None:
        result = check_release_alignment.check_alignment(
            "v1.2.9",
            self._manifest(CURRENT_VERSION),
        )
        self.assertFalse(result.ok)
        self.assertIn("does not match", result.message)

    def test_malformed_tag_fails(self) -> None:
        result = check_release_alignment.check_alignment(
            CURRENT_VERSION,
            self._manifest(CURRENT_VERSION),
        )
        self.assertFalse(result.ok)
        self.assertIn("must look like", result.message)

    def _run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = check_release_alignment.main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_main_matching_tag_exits_zero(self) -> None:
        exit_code, stdout, stderr = self._run_main(
            [
                f"v{CURRENT_VERSION}",
                "--manifest",
                str(self._manifest(CURRENT_VERSION)),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("matches manifest version", stdout)
        self.assertEqual(stderr, "")

    def test_main_mismatched_tag_exits_one(self) -> None:
        exit_code, stdout, stderr = self._run_main(
            ["v1.2.9", "--manifest", str(self._manifest(CURRENT_VERSION))]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("does not match", stderr)

    def test_main_malformed_tag_exits_one(self) -> None:
        exit_code, stdout, stderr = self._run_main(
            [CURRENT_VERSION, "--manifest", str(self._manifest(CURRENT_VERSION))]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("must look like", stderr)

    def test_main_missing_tag_exits_two_with_clear_error(self) -> None:
        with patch.dict(
            "os.environ",
            {"GITHUB_REF_NAME": "", "GITHUB_REF": ""},
            clear=False,
        ):
            exit_code, stdout, stderr = self._run_main(
                ["--manifest", str(self._manifest(CURRENT_VERSION))]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("release tag is required", stderr)
        self.assertIn("GITHUB_REF_NAME/GITHUB_REF", stderr)


if __name__ == "__main__":
    unittest.main()
