"""Build a pinned independent playback library locally, without installing it."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.7.3"
URL = (
    "https://github.com/libxmp/libxmp/releases/download/"
    f"libxmp-{VERSION}/libxmp-{VERSION}.tar.gz"
)
SHA256 = "b6a98797e4fb9c9a705f5d53112aa5214561857e929a644928b9e658930d9440"


def find_cmake() -> str:
    installed = shutil.which("cmake")
    if installed:
        return installed
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere /= "Microsoft Visual Studio/Installer/vswhere.exe"
    if vswhere.is_file():
        result = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-find",
             "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"],
            check=True, capture_output=True, text=True, timeout=20,
        )
        for candidate in result.stdout.splitlines():
            if Path(candidate).is_file():
                return candidate
    raise RuntimeError("CMake not found. Install the Visual Studio C++/CMake tools.")


def main() -> int:
    target = ROOT / ".tools" / "libxmp"
    target.mkdir(parents=True, exist_ok=True)
    archive = target / f"libxmp-{VERSION}.tar.gz"
    if not archive.is_file():
        print(f"Downloading libxmp {VERSION} from its official repository…", flush=True)
        request = urllib.request.Request(URL, headers={"User-Agent": "tracker4agents-prototype"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read(4_000_001)
        if len(payload) > 4_000_000:
            raise RuntimeError("The archive is unusually large.")
        if hashlib.sha256(payload).hexdigest() != SHA256:
            raise RuntimeError("The archive's SHA256 does not match the expected version.")
        archive.write_bytes(payload)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError(f"Invalid local archive: {archive}")

    source = target / f"libxmp-{VERSION}"
    if not source.is_dir():
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(target, filter="data")

    cmake = find_cmake()
    build = target / "build"
    subprocess.run(
        [cmake, "-S", str(source), "-B", str(build), "-DBUILD_SHARED=ON",
         "-DBUILD_STATIC=OFF", "-DBUILD_LITE=OFF"],
        check=True, timeout=120,
    )
    subprocess.run(
        [cmake, "--build", str(build), "--config", "Release", "--parallel", "4"],
        check=True, timeout=240,
    )
    libraries = list(build.rglob("*xmp*.dll")) if sys.platform == "win32" else list(build.rglob("libxmp.so*"))
    if not libraries:
        raise RuntimeError("The build finished but the shared library was not found.")
    manifest = {
        "name": "libxmp", "version": VERSION, "source_url": URL,
        "archive_sha256": SHA256, "library": str(libraries[0].resolve()),
        "library_sha256": hashlib.sha256(libraries[0].read_bytes()).hexdigest(),
        "license": str((source / "README").resolve()),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
