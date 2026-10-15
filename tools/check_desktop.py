"""Optional native-window smoke check. Playback is muted; no source is edited.

Run twice in separate processes, the second time without --source, to check
session restoration. --keep-open leaves the checked window ready for the user.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer

from tracker4agents import __version__, audio, project
from tracker4agents.desktop import TrackerWindow, application
from tracker4agents.themes import THEMES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--theme", choices=THEMES)
    parser.add_argument("--language", choices=("en", "fr"))
    parser.add_argument("--capture-playing", action="store_true")
    args = parser.parse_args()
    app = application()
    window = TrackerWindow(args.source, args.state_dir)
    if args.theme:
        window.set_theme(args.theme)
    if args.language:
        window.set_language(args.language)
    window.output.setMuted(True)
    window.show()
    deadline, phase = time.monotonic() + 35, "loading"
    completed = False
    timer = QTimer(window)

    def check():
        nonlocal phase, completed
        if time.monotonic() > deadline:
            project.write_json(args.report, {"ok": False, "message": window.statusBar().currentMessage()})
            window.close()
            app.exit(2)
        elif phase == "loading" and window._audio_ready:
            window.toggle_play()
            phase = "playing"
        elif phase == "playing" and window.player.position() >= 500:
            position, state = window.player.position(), window.player.playbackState().name
            levels, peaks, buffers = window.meter.levels, window.meter.raw_peaks, window.meter.buffer_count
            if not args.capture_playing:
                window.stop()
            window.table.setCurrentIndex(window.pattern_model.index(0, 9))
            window._sync_position()
            app.processEvents()
            report = {
                "ok": window.player.error() == QMediaPlayer.Error.NoError,
                "version": __version__, "pyside6": qt_version, "platform": app.platformName(),
                "title": window.document.module.title, "source": str(window.document.path),
                "source_sha256": audio.sha256(window.document.path),
                "session": str(window.state.path), "duration_ms": window.player.duration(),
                "playback_state_checked": state, "playback_position_checked_ms": position,
                "volume": window.volume.value(), "loop": window.loop.isChecked(),
                "follow": window.follow.isChecked(), "error": window.player.errorString(),
                "theme": window.theme, "language": window.language,
                "meter_buffers": buffers, "meter_rms": levels, "meter_peaks": peaks,
                "not_checked": ["physical speakers", "Linux", "Amiga hardware"],
            }
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                report["screenshot_saved"] = window.grab().save(str(args.screenshot))
            project.write_json(args.report, report)
            window.stop()
            window.output.setMuted(False)
            completed = True
            timer.stop()
            if not args.keep_open:
                window.close()
                app.quit()

    timer.timeout.connect(check)
    timer.start(30)
    result = app.exec()
    return result if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
