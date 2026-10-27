"""Real-time playback: libxmp renders small blocks that a QAudioSink plays while the song is edited.

`RealtimeTransport` replaces the render-to-WAV + QMediaPlayer path when libxmp is available. It keeps a
log of the row markers it wrote, so the position that is *heard* (frames written minus frames still queued
in the sink) drives the pattern highlight, the seek slider and the clock. Exports, sample previews and
"Listen to proposal" keep using the rendered path.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
import os

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .level_meter import pcm_levels
from .realtime import RealtimeError, XmpEngine, find_library

SAMPLE_RATE = 48000
FRAME_BYTES = 4                    # 16-bit stereo
TARGET_FRAMES = SAMPLE_RATE // 8   # keep about 120 ms queued
BUFFER_FRAMES = SAMPLE_RATE // 4   # sink buffer: 250 ms of headroom
TICK_MS = 10
LIBXMP_HINT = ("Real-time playback needs libxmp (not found): playing rendered audio instead. Run "
               "`python tools/setup_reference.py`, install libxmp or set CHIPLOOM_LIBXMP.")


def audio_format() -> QAudioFormat:
    fmt = QAudioFormat()
    fmt.setSampleRate(SAMPLE_RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


def output_available() -> bool:
    return not QMediaDevices.defaultAudioOutput().isNull()


def make_sink(volume: float = 1.0):
    """The push-mode audio output. Tests replace this with a fake that has the same small API."""
    sink = QAudioSink(QMediaDevices.defaultAudioOutput(), audio_format())
    sink.setBufferSize(BUFFER_FRAMES * FRAME_BYTES)
    sink.setVolume(volume)
    return sink


def unavailable_reason(preference: bool = True) -> str | None:
    """Why real-time playback cannot be used: "disabled", "libxmp", "output", or None when it can."""
    if os.environ.get("CHIPLOOM_PLAYBACK", "").lower() == "rendered" or not preference:
        return "disabled"
    if find_library() is None:
        return "libxmp"
    if not output_available():
        return "output"
    return None


class RealtimeTransport(QObject):
    """Play/pause/seek/reload around an `XmpEngine`, streamed to an audio sink from the GUI thread."""

    state_changed = Signal()
    finished = Signal()

    def __init__(self, window, engine: XmpEngine | None = None, sink_factory=None):
        super().__init__(window)
        self.window = window
        self.engine = engine or XmpEngine(sample_rate=SAMPLE_RATE)
        self.sink_factory = sink_factory or make_sink
        self.sink = None
        self.device = None
        self.playing = False
        self.idle_ms = 0                       # where playback resumes when not playing
        self.volume = 1.0
        self.underruns = 0
        self.reloads = 0
        self._times_plan, self._times = None, {}
        self._prefix, self._prefix_markers = b"", []   # audio already rendered while moving to a row
        self._reset_stream()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.feed)

    # --- stream bookkeeping --------------------------------------------------------------
    def _reset_stream(self):
        self._rendered = 0       # frames produced by the engine since the stream (re)started
        self._delivered = 0      # frames accepted by the sink
        self._carry = b""
        self._dry = False
        self._skip = 0
        self._draining = False
        self._markers: list[tuple[int, dict]] = []   # (stream frame where the row starts, marker)
        self._levels: deque = deque()                # (stream frame, rms, peaks) per block
        self._row_start = 0

    def _queued_frames(self) -> int:
        if self.sink is None:
            return 0
        return max(0, (self.sink.bufferSize() - self.sink.bytesFree()) // FRAME_BYTES)

    def _open_sink(self):
        self._close_sink()
        self.sink = self.sink_factory(self.volume)
        self.device = self.sink.start()
        self._reset_stream()

    def _close_sink(self):
        if self.sink is not None:
            self.sink.stop()
            if hasattr(self.sink, "deleteLater"):
                self.sink.deleteLater()
        self.sink = self.device = None

    # --- engine control ------------------------------------------------------------------
    def prepare(self, play: bool, position_ms: int = 0):
        """Load the window's module and position it; used when a document is opened or monitoring restarts."""
        self.pause_stream()
        self.engine.set_audible(self.window.audible())
        self.engine.loop = self.window.loop.isChecked()
        self._position(0, 0, self.window.document.module)
        self.idle_ms = 0
        if position_ms:
            self.seek_ms(position_ms)
        if play:
            self.play()
        self.state_changed.emit()

    def reload(self):
        """Swap the edited module in without stopping: the queued audio plays out, the new notes follow it."""
        document = self.window.document
        if document is None:
            return
        self.reloads += 1
        try:
            if self.playing and self.sink is not None:
                self._skip = max(0, self._rendered - self._row_start)  # the row being rendered is already queued
            order, row = self.engine.position["order"], self.engine.position["row"]
            self._position(order, row, document.module)
            self._draining = False
        except RealtimeError as exc:
            self.window.message("Real-time playback failed: {detail}", True, detail=exc)

    def set_audible(self, audible):
        self.engine.set_audible(audible)

    def set_loop(self, loop: bool):
        self.engine.loop = bool(loop)
        if loop:
            self._draining = False

    def set_volume(self, volume: float):
        self.volume = volume
        if self.sink is not None:
            self.sink.setVolume(volume)

    def _position_at(self, seconds: float):
        """Put the engine on the row playing at `seconds` of the song."""
        timeline = (self.engine.plan or {}).get("timeline") or [{"order": 0, "row": 0, "seconds": 0}]
        target = timeline[0]
        for item in timeline:
            if item["seconds"] > seconds:
                break
            target = item
        self._position(target["order"], target["row"])

    def _position(self, order: int, row: int, module=None):
        """Start the engine at order/row with the tempo and speed in force there.

        libxmp restores timing only at the start of an order, and a plain row jump keeps whatever tempo
        was playing (the 125 BPM default after a reload). So go to the order start and play silently up
        to the row (a few ms of CPU); the audio from that row on is kept for the stream."""
        engine = self.engine
        if module is not None:
            engine.load(module, order, 0)
        else:
            engine.seek(order, 0)
        self._prefix, self._prefix_markers = b"", []
        if row <= 0:
            return
        limit = SAMPLE_RATE * 120
        spent = 0
        while spent < limit and not engine.finished:
            pcm, markers = engine.render(2400)
            hit = next((m for m in markers if m["order"] == order and m["row"] >= row), None)
            if hit is not None:
                cut = hit["frame"]
                self._prefix = pcm[cut * FRAME_BYTES:]
                self._prefix_markers = [{**m, "frame": m["frame"] - cut} for m in markers if m["frame"] >= cut]
                return
            if not pcm:
                break
            spent += len(pcm) // FRAME_BYTES

    # --- transport -----------------------------------------------------------------------
    def play(self):
        if self.playing:
            return
        if self.engine.finished:
            self._prefix, self._prefix_markers = b"", []
            self.engine.seek(0, 0)
            self.idle_ms = 0
        self._open_sink()
        self.playing = True
        self.feed()
        self.timer.start()
        self.state_changed.emit()

    def heard(self) -> tuple[int, dict | None]:
        """(milliseconds, row marker) of the audio the speakers are playing right now."""
        if not self.playing:
            return self.idle_ms, None
        heard = self._delivered - self._queued_frames()
        keys = [index for index, _ in self._markers]
        position = bisect_right(keys, heard) - 1
        if position < 0:
            return self.idle_ms, None
        index, marker = self._markers[position]
        if position > 0:
            del self._markers[:position]  # earlier rows are history
        return round(marker["seconds"] * 1000 + max(0, heard - index) * 1000 / SAMPLE_RATE), marker

    def heard_levels(self):
        """RMS and peak of the block being heard, or None."""
        heard = self._delivered - self._queued_frames()
        found = None
        while self._levels and self._levels[0][0] <= heard:
            found = self._levels.popleft()
        return found[1:] if found else None

    def position_ms(self) -> int:
        return self.heard()[0]

    def pause_stream(self):
        """Stop the sound where it is heard and park the engine on that row."""
        if not self.playing:
            return
        milliseconds, marker = self.heard()
        self.timer.stop()
        self.playing = False
        self._close_sink()
        self._reset_stream()
        if marker is not None:
            self.idle_ms = round(marker["seconds"] * 1000)
            self._position(marker["order"], marker["row"])
        else:
            self.idle_ms = milliseconds
            self._position_at(milliseconds / 1000)

    def pause(self):
        was = self.playing
        self.pause_stream()
        if was:
            self.state_changed.emit()

    def stop(self):
        was = self.playing
        self.timer.stop()
        self.playing = False
        self._close_sink()
        self._reset_stream()
        self.idle_ms = 0
        self._prefix, self._prefix_markers = b"", []
        if self.engine.plan is not None:
            self.engine.seek(0, 0)
        if was:
            self.state_changed.emit()

    def seek_ms(self, milliseconds: int):
        milliseconds = max(0, int(milliseconds))
        self._position_at(milliseconds / 1000)
        self.idle_ms = milliseconds
        if self.playing and self.sink is not None:
            # Everything queued belongs to the old position: flush by restarting the same sink.
            self.sink.stop()
            self.device = self.sink.start()
            self._reset_stream()
            self.feed()

    # --- feeding -------------------------------------------------------------------------
    def feed(self):
        """Top the sink up to about 120 ms of audio."""
        if not self.playing or self.sink is None:
            return
        queued = self._queued_frames()
        if self._draining:
            if queued == 0:
                self._finish()
            return
        # PySide cannot receive QAudio::State, so an underrun is detected here: the sink ran dry mid-song.
        if queued == 0 and self._delivered > 0 and not self._dry:
            self.underruns += 1
        self._dry = queued == 0 and self._delivered > 0
        free_frames = self.sink.bytesFree() // FRAME_BYTES
        wanted = TARGET_FRAMES - self._queued_frames() - len(self._carry) // FRAME_BYTES
        frames = min(free_frames, wanted)
        if self._carry:
            written = self.device.write(self._carry)
            self._carry = self._carry[max(0, written):]
            self._delivered += max(0, written) // FRAME_BYTES
            if self._carry:
                return
        if frames < 64:
            return
        try:
            if self._prefix:
                pcm, markers, self._prefix, self._prefix_markers = self._prefix, self._prefix_markers, b"", []
            else:
                pcm, markers = self.engine.render(frames)
        except RealtimeError as exc:
            self.stop()
            self.window.message("Real-time playback failed: {detail}", True, detail=exc)
            return
        if self._skip:
            drop = min(self._skip, len(pcm) // FRAME_BYTES)
            self._skip -= drop
            pcm = pcm[drop * FRAME_BYTES:]
            markers = [{**marker, "frame": marker["frame"] - drop} for marker in markers if marker["frame"] >= drop]
        if not pcm:
            if self.engine.finished:
                self._draining = True
            return
        start = self._rendered
        times = self._song_times()
        for marker in markers:
            # The engine's own clock counts time played since the last seek, not song time: use the plan.
            marker = {**marker, "seconds": times.get((marker["order"], marker["row"]), marker["seconds"])}
            self._markers.append((start + marker["frame"], marker))
        if markers:
            self._row_start = start + markers[-1]["frame"]
        rms, peaks = pcm_levels(pcm)
        self._levels.append((start, rms, peaks))
        self._rendered += len(pcm) // FRAME_BYTES
        written = self.device.write(pcm)
        written = max(0, written)
        self._delivered += written // FRAME_BYTES
        self._carry = pcm[written:]
        if self.engine.finished and not self._prefix:
            self._draining = True

    def _song_times(self) -> dict:
        plan = self.engine.plan
        if plan is not self._times_plan:
            self._times_plan = plan
            self._times = {(item["order"], item["row"]): item["seconds"] for item in (plan or {}).get("timeline", [])}
        return self._times

    def _finish(self):
        """Song over with loop off: let the tail play out, then rest at the start."""
        self.stop()
        self.finished.emit()
        self.window.message("Ready to play")

    def shutdown(self):
        self.timer.stop()
        self.playing = False
        self._close_sink()
        self.engine.close()
