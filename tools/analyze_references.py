"""Compatibility entry point for the reusable read-only reference analyzer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker4agents.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["analyze", *sys.argv[1:]]))
