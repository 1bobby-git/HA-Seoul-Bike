"""Build and verify the manual-install ZIP from the checked-out commit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "seoul_bike"


def main() -> None:
    version = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "seoul_bike.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        for path in sorted(COMPONENT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                package.write(path, path.relative_to(ROOT).as_posix())
    with ZipFile(archive) as package:
        if package.testzip() is not None:
            raise RuntimeError("Release archive integrity check failed")
        bundled = json.loads(package.read("custom_components/seoul_bike/manifest.json"))
        if bundled["version"] != version:
            raise RuntimeError("Release archive version mismatch")
        required = {f"custom_components/seoul_bike/{name}" for name in ("api.py", "site_api.py", "transport.py", "__init__.py")}
        if not required.issubset(package.namelist()):
            raise RuntimeError("Release archive is missing integration modules")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Verified v{version}: {archive.name} ({archive.stat().st_size} bytes), sha256={digest}")


if __name__ == "__main__":
    main()
