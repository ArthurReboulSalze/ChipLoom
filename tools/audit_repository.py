"""Audit the exact Git index before sharing: no local state or reference media."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {".venv", ".tools", "__pycache__", ".playwright-mcp", "exports", "private"}
BLOCKED_EXTENSIONS = {".mod", ".xm", ".it", ".zip", ".wav", ".mp3", ".mp4", ".mov", ".webm", ".pcm", ".dll", ".exe", ".pyc"}
BLOCKED_NAMES = {"library.json", "provenance.json"}
# Owner-approved original compositions only, pinned to the reviewed bytes.
PUBLIC_DEMOS = {
    "docs/listen/media/pixel_rush.mod": "1ce068afb51e239fb090ff8b1cf3adca9ab96991d12bad6c618573d873516281",
    "docs/listen/media/pixel_rush.mp3": "d503741a5a83faa79940fb6513b129021c8cc10ae5e1f1b50e911ca6200c55c3",
    "docs/listen/media/voltage_odyssey_v2.mod": "a4822a56be18d66145dac91706a096e6efbfcfa97b9e5a392c3d79f128234197",
    "docs/listen/media/voltage_odyssey_v2.mp3": "2b2d18c7370e5e42877edf87c5c8eae7f5b496bb347cc48bd3563f83b9ada4dc",
    "docs/listen/media/copper_skies.xm": "77547086ed2d94f627ee1a8be54c3fda3d8f19c794064f14ac2b2ea704a78247",
    "docs/listen/media/chiploom-explainer.mp4": "3e18c72f856df595a157500522a7ac6bfe1f3264a120e092b4c550de56def18c",
    "docs/listen/media/copper_skies.mp3": "f5f931436c10b232ca18af1f9c953051df096266f5101c03588d19b299b407d1",
}
SECRET = re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    errors, checked = [], 0
    for name in filter(None, names):
        path = PurePosixPath(name)
        checked += 1
        if BLOCKED_PARTS.intersection(path.parts) or path.name.lower() in BLOCKED_NAMES or (path.suffix.lower() in BLOCKED_EXTENSIONS and name not in PUBLIC_DEMOS) or path.name.startswith(".env"):
            errors.append(f"Excluded local/reference file in index: {name}")
            continue
        content = subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)
        if name in PUBLIC_DEMOS and hashlib.sha256(content).hexdigest() != PUBLIC_DEMOS[name]:
            errors.append(f"Public demo differs from approved bytes: {name}")
        if SECRET.search(content):
            errors.append(f"Possible credential in index: {name}")
        if len(content) > 2 * 1024 * 1024 and name not in PUBLIC_DEMOS:
            errors.append(f"Unexpectedly large tracked file: {name}")
        if path.suffix.lower() == ".json":
            document = json.loads(content)
            if isinstance(document, dict) and document.get("schema") in {"chiploom.sample-library.v1", "chiploom.sample-provenance.v1"}:
                errors.append(f"Local sample bank data in index: {name}")
        if path.parts[0] == "references" and path.suffix == ".json":
            report = json.loads(content)
            def walk(value):
                if isinstance(value, dict):
                    if {"pcm", "events", "recipe"}.intersection(value):
                        errors.append(f"Raw music data in reference report: {name}")
                    if {"source", "filename", "title", "sha256", "source_sha256", "pcm_sha256"}.intersection(value):
                        errors.append(f"Identifying metadata in public reference report: {name}")
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
            walk(report)
    if not checked:
        errors.append("No staged/tracked files to audit.")
    print(json.dumps({"ok": not errors, "files_checked": checked, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
