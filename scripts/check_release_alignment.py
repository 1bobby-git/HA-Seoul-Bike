from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MANIFEST = Path("custom_components/seoul_bike/manifest.json")
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class AlignmentResult:
    ok: bool
    expected_tag: str
    actual_tag: str
    message: str


def read_manifest_version(manifest_path: Path = DEFAULT_MANIFEST) -> str:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(payload.get("version") or "").strip()
    if not version:
        raise ValueError(f"{manifest_path} does not define version")
    return version


def check_alignment(tag: str, manifest_path: Path = DEFAULT_MANIFEST) -> AlignmentResult:
    actual_tag = str(tag or "").strip()
    version = read_manifest_version(manifest_path)
    expected_tag = f"v{version}"

    if not TAG_RE.fullmatch(actual_tag):
        return AlignmentResult(
            ok=False,
            expected_tag=expected_tag,
            actual_tag=actual_tag,
            message=f"tag must look like vX.Y.Z: {actual_tag!r}",
        )
    if actual_tag != expected_tag:
        return AlignmentResult(
            ok=False,
            expected_tag=expected_tag,
            actual_tag=actual_tag,
            message=f"tag {actual_tag!r} does not match manifest version tag {expected_tag!r}",
        )
    return AlignmentResult(
        ok=True,
        expected_tag=expected_tag,
        actual_tag=actual_tag,
        message=f"release tag {actual_tag!r} matches manifest version {version!r}",
    )


def _tag_from_environment() -> str:
    ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()
    if ref_name:
        return ref_name
    ref = os.environ.get("GITHUB_REF", "").strip()
    prefix = "refs/tags/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release tag alignment with manifest.version.")
    parser.add_argument("tag", nargs="?", default="", help="Release tag to validate, for example v1.3.0.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to Home Assistant manifest.json.",
    )
    args = parser.parse_args(argv)

    tag = args.tag or _tag_from_environment()
    if not tag:
        print("release tag is required as an argument or GITHUB_REF_NAME/GITHUB_REF", file=sys.stderr)
        return 2

    try:
        result = check_alignment(tag, args.manifest)
    except Exception as err:
        print(f"release alignment check failed: {err}", file=sys.stderr)
        return 1

    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
