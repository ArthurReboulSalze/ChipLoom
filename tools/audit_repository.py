"""Audit the exact Git index before sharing: no local state or reference media."""
from pathlib import Path, PurePosixPath
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {".venv", ".tools", "__pycache__", ".playwright-mcp", "exports", "private"}
BLOCKED_EXTENSIONS = {".mod", ".xm", ".it", ".zip", ".wav", ".mp3", ".dll", ".exe", ".pyc"}
SECRET = re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    errors, checked = [], 0
    for name in filter(None, names):
        path = PurePosixPath(name)
        checked += 1
        if BLOCKED_PARTS.intersection(path.parts) or path.suffix.lower() in BLOCKED_EXTENSIONS or path.name.startswith(".env"):
            errors.append(f"Excluded local/reference file in index: {name}")
            continue
        content = subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)
        if SECRET.search(content):
            errors.append(f"Possible credential in index: {name}")
        if len(content) > 2 * 1024 * 1024:
            errors.append(f"Unexpectedly large tracked file: {name}")
        if path.parts[0] == "references" and path.suffix == ".json":
            report = json.loads(content)
            def walk(value):
                if isinstance(value, dict):
                    if {"pcm", "events", "recipe"}.intersection(value):
                        errors.append(f"Raw music data in reference report: {name}")
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
