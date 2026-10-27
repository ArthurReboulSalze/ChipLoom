"""Real-time playback: libxmp renders small blocks that a QAudioSink plays while the song is edited.

`RealtimeTransport` replaces the render-to-WAV + QMediaPlayer path when libxmp is available. The engine
and the sink run in their own thread (`AudioCore`), commanded by queued signals, so a stalled GUI thread
(window drags, dialogs, heavy redraws) cannot starve the sound card. The core keeps a log of the row
markers it wrote, so the position that is *heard* (frames written minus frames still queued in the sink)
drives the pattern highlight, the seek slider and the clock through a thread-safe snapshot. Exports,
sample previews and "Listen to proposal" keep using the rendered path.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
import os
import threading

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .level_meter import pcm_levels
from .realtime import RealtimeError, XmpEngine, find_library

SAMPLE_RATE = 48000
FRAME_BYTES = 4                    # 16-bit stereo
# Audio buffer choices: how much audio is kept queued in the sink. The audio thread already keeps a
# stalled GUI from starving it (0 underruns at every size, 600 ms GUI stalls included); the buffer is
# the margin for the audio thread's own scheduling, paid for as latency between an edit and the sound.
# Normal is the shortest size that stayed clean in every measurement.
BUFFER_CHOICES = (("low", 80), ("normal", 150), ("high", 300), ("very_high", 600))
DEFAULT_BUFFER = "normal"
TICK_MS = 10
LIBXMP_HINT = ("Real-time playback needs libxmp (not found): playing rendered audio instead. Run "
               "`python tools/setup_reference.py`, install libxmp or set CHIPLOOM_LIBXMP.")


def valid_buffer(value: object) -> str:
    """Session values are untrusted: anything unknown means the default."""
    return value if isinstance(value, str) and value in dict(BUFFER_CHOICES) else DEFAULT_BUFFER


def buffer_frames(milliseconds: int) -> int:
    """Sink capacity for a queue target: half again as much, so a late tick never overflows it."""
    return round(SAMPLE_RATE * milliseconds * 1.5 / 1000)


def audio_format() -> QAudioFormat:
    fmt = QAudioFormat()
    fmt.setSampleRate(SAMPLE_RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


def output_available() -> bool:
    return not QMediaDevices.defaultAudioOutput().isNull()


def make_sink(volume: float = 1.0, frames: int = 0):
    """The push-mode audio output. Tests replace this with a fake that has the same small API."""
    sink = QAudioSink(QMediaDevices.defaultAudioOutput(), audio_format())
    sink.setBufferSize((frames or buffer_frames(150)) * FRAME_BYTES)
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


class AudioCore(QObject):
    """The audio side: engine, sink and feeding timer. It lives in the audio thread and is only driven
    by queued commands (`run`); it publishes a position snapshot for the GUI after every tick and command."""

    failed = Signal(str, bool)      # message, fatal (the module could not be loaded at all)
    finished = Signal()             # the song ended with loop off

    def __init__(self, engine: XmpEngine, sink_factory, latency_ms: int, publish):
        super().__init__()
        self.engine, self.sink_factory, self._publish_fn = engine, sink_factory, publish
        self.sink = None
        self.device = None
        self.playing = False
        self.idle_ms = 0                       # where playback resumes when not playing
        self.volume = 1.0
        self.latency_ms = 0
        self.set_latency(latency_ms, restart=False)
        self.underruns = 0
        self.processed = 0                     # commands handled, so the GUI knows when its view is current
        self._level_seq, self._last_levels = 0, None
        self._times_plan, self._times = None, {}
        self._prefix, self._prefix_markers = b"", []   # audio already rendered while moving to a row
        self._reset_stream()
        self.timer = None

    @Slot()
    def start(self):
        self.timer = QTimer(self)   # created in the audio thread: its timeouts run there
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.feed)

    @Slot(str, object)
    def run(self, name: str, args: tuple):
        try:
            getattr(self, "cmd_" + name)(*args)
        except (RealtimeError, ValueError) as exc:
            if name != "load":
                self.cmd_stop()
            self.failed.emit(str(exc), name == "load")
        self.processed += 1
        self._publish()

    @Slot()
    def shutdown(self):
        if self.timer is not None:
            self.timer.stop()
        self.playing = False
        self._close_sink()
        self.engine.close()

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
        self.sink = self.sink_factory(self.volume, self.buffer_frames)
        self.device = self.sink.start()
        self._reset_stream()

    def _close_sink(self):
        if self.sink is not None:
            self.sink.stop()
            if hasattr(self.sink, "deleteLater"):
                self.sink.deleteLater()
        self.sink = self.device = None

    def _publish(self):
        milliseconds, marker = self._heard()
        levels = self._heard_levels()
        if levels:
            self._level_seq += 1
            self._last_levels = levels
        self._publish_fn({"playing": self.playing, "ms": milliseconds, "marker": marker,
                          "queued": self._queued_frames(), "rendered": self._rendered, "underruns": self.underruns,
                          "levels": self._last_levels, "level_seq": self._level_seq, "processed": self.processed,
                          "sink_state": self.sink.state().name if hasattr(self.sink, "state") else "",
                          "thread": threading.get_ident()})

    # --- commands (audio thread) ---------------------------------------------------------
    def cmd_load(self, module, play: bool, position_ms: int, audible, loop: bool):
        """Load a module and position it: a document was opened, or the real-time engine restarts."""
        self._stop_stream()
        self.engine.set_audible(audible)
        self.engine.loop = bool(loop)
        self._position(0, 0, module)
        self.idle_ms = 0
        if position_ms:
            self.cmd_seek(position_ms)
        if play:
            self.cmd_play()

    def cmd_reload(self, module):
        """Swap the edited module in without stopping: the queued audio plays out, the new notes follow it."""
        if self.playing and self.sink is not None:
            self._skip = max(0, self._rendered - self._row_start)  # the row being rendered is already queued
        order, row = self.engine.position["order"], self.engine.position["row"]
        self._position(order, row, module)
        self._draining = False

    def cmd_audible(self, audible):
        self.engine.set_audible(audible)

    def cmd_loop(self, loop: bool):
        self.engine.loop = bool(loop)
        if loop:
            self._draining = False

    def cmd_volume(self, volume: float):
        self.volume = volume
        if self.sink is not None:
            self.sink.setVolume(volume)

    def cmd_latency(self, milliseconds: int):
        self.set_latency(milliseconds)

    def set_latency(self, milliseconds: int, restart: bool = True):
        """Change how much audio is queued; a running stream is rebuilt on the row being heard."""
        self.latency_ms = int(milliseconds)
        self.target_frames = SAMPLE_RATE * self.latency_ms // 1000
        self.buffer_frames = buffer_frames(self.latency_ms)
        if restart and self.playing:
            self._stop_stream()   # parks the engine on the heard row...
            self.cmd_play()       # ...and a sink of the new size resumes from it

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

    def cmd_play(self):
        if self.playing:
            return
        if self.engine.finished:
            self._prefix, self._prefix_markers = b"", []
            self.engine.seek(0, 0)
            self.idle_ms = 0
        self._open_sink()
        self.playing = True
        self._feed()
        self.timer.start()

    def _heard(self) -> tuple[int, dict | None]:
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

    def _heard_levels(self):
        """RMS and peak of the block being heard, or None when nothing new has been reached."""
        heard = self._delivered - self._queued_frames()
        found = None
        while self._levels and self._levels[0][0] <= heard:
            found = self._levels.popleft()
        return found[1:] if found else None

    def _stop_stream(self):
        """Stop the sound where it is heard and park the engine on that row."""
        if not self.playing:
            return
        milliseconds, marker = self._heard()
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

    def cmd_pause(self):
        self._stop_stream()

    def cmd_stop(self):
        if self.timer is not None:
            self.timer.stop()
        self.playing = False
        self._close_sink()
        self._reset_stream()
        self.idle_ms = 0
        self._prefix, self._prefix_markers = b"", []
        if self.engine.plan is not None:
            self.engine.seek(0, 0)

    def cmd_seek(self, milliseconds: int):
        milliseconds = max(0, int(milliseconds))
        self._position_at(milliseconds / 1000)
        self.idle_ms = milliseconds
        if self.playing and self.sink is not None:
            # Everything queued belongs to the old position: flush by restarting the same sink.
            self.sink.stop()
            self.device = self.sink.start()
            self._reset_stream()
            self._feed()

    # --- feeding -------------------------------------------------------------------------
    def feed(self):
        """Timer tick: top the sink up to the chosen queue length, then publish the position."""
        self._feed()
        self._publish()

    def _feed(self):
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
        wanted = self.target_frames - queued - len(self._carry) // FRAME_BYTES
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
            self.cmd_stop()
            self.failed.emit(str(exc), False)
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
        written = max(0, self.device.write(pcm))
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
        """Song over with loop off: the tail has played out; rest at the start."""
        self.cmd_stop()
        self.finished.emit()


class RealtimeTransport(QObject):
    """What the window talks to. The engine and the audio sink live in a dedicated thread; this facade
    sends queued commands and reads a thread-safe snapshot of what is being heard."""

    state_changed = Signal()
    finished = Signal()
    failed = Signal(str, bool)
    _command = Signal(str, object)
    _stop_thread = Signal()

    def __init__(self, window, engine: XmpEngine | None = None, sink_factory=None,
                 latency_ms: int = dict(BUFFER_CHOICES)[DEFAULT_BUFFER]):
        super().__init__(window)
        self.window = window
        self.engine = engine or XmpEngine(sample_rate=SAMPLE_RATE)   # driven from the audio thread only
        self.latency_ms = int(latency_ms)
        self.volume = 1.0
        self.reloads = 0
        self.audible, self.loop = (True,) * 4, True
        self._playing = False
        self._sent = 0                      # commands sent; compared with the thread's `processed`
        self._override: tuple[int, int] | None = None   # (milliseconds, command count) shown until the thread catches up
        self._level_seen = 0
        self._closed = False
        self._lock = threading.Lock()
        self._snap = {"playing": False, "ms": 0, "marker": None, "queued": 0, "rendered": 0, "underruns": 0,
                      "levels": None, "level_seq": 0, "processed": 0, "sink_state": ""}
        self.core = AudioCore(self.engine, sink_factory or make_sink, self.latency_ms, self._store)
        self.thread = QThread()
        self.thread.setObjectName("chiploom-audio")
        self.core.moveToThread(self.thread)
        self.thread.started.connect(self.core.start)
        self._command.connect(self.core.run, Qt.ConnectionType.QueuedConnection)
        self._stop_thread.connect(self.core.shutdown, Qt.ConnectionType.BlockingQueuedConnection)
        self.core.failed.connect(self._core_failed, Qt.ConnectionType.QueuedConnection)
        self.core.finished.connect(self._core_finished, Qt.ConnectionType.QueuedConnection)
        self.thread.start(QThread.Priority.HighPriority)

    # --- plumbing ------------------------------------------------------------------------
    def _store(self, snapshot: dict):
        with self._lock:
            self._snap = snapshot

    def snapshot(self) -> dict:
        with self._lock:
            return self._snap

    def _send(self, name: str, *args):
        self._sent += 1
        self._command.emit(name, args)

    def _core_failed(self, message: str, fatal: bool):
        self._playing = False
        self._override = None
        self.state_changed.emit()
        self.failed.emit(message, fatal)

    def _core_finished(self):
        snap = self.snapshot()
        if self._playing and snap["processed"] >= self._sent and not snap["playing"]:
            self._playing = False
            self._override = (0, self._sent)
            self.state_changed.emit()
            self.finished.emit()

    @property
    def playing(self) -> bool:
        """The requested state at once; once the thread has caught up it is the thread's own (end of song)."""
        snap = self.snapshot()
        if self._playing and snap["processed"] >= self._sent and not snap["playing"]:
            self._core_finished()
        return self._playing

    @property
    def underruns(self) -> int:
        return self.snapshot()["underruns"]

    @property
    def queued_frames(self) -> int:
        return self.snapshot()["queued"]

    @property
    def rendered_frames(self) -> int:
        return self.snapshot()["rendered"]

    @property
    def sink_state(self) -> str:
        return self.snapshot()["sink_state"]

    # --- commands ------------------------------------------------------------------------
    def prepare(self, play: bool, position_ms: int = 0):
        """Load the window's module and position it; used when a document is opened or monitoring restarts."""
        self.audible, self.loop = self.window.audible(), self.window.loop.isChecked()
        self._playing = bool(play)
        self._send("load", self.window.document.module, bool(play), int(position_ms), self.audible, self.loop)
        self._override = (int(position_ms), self._sent)
        self.state_changed.emit()

    def reload(self):
        """Swap the edited module in without stopping."""
        document = self.window.document
        if document is not None:
            self.reloads += 1
            self._send("reload", document.module)

    def set_audible(self, audible):
        self.audible = tuple(bool(value) for value in audible)
        self._send("audible", self.audible)

    def set_loop(self, loop: bool):
        self.loop = bool(loop)
        self._send("loop", self.loop)

    def set_latency(self, milliseconds: int):
        """Resize the queue and the sink at once; a running stream resumes on the row being heard."""
        self.latency_ms = int(milliseconds)
        self._send("latency", self.latency_ms)
        self.state_changed.emit()

    def set_volume(self, volume: float):
        self.volume = volume
        self._send("volume", volume)

    def play(self):
        if not self._playing:
            self._playing = True
            self._send("play")
            self.state_changed.emit()

    def pause(self):
        if self._playing:
            self._playing = False
            self._send("pause")
            self.state_changed.emit()

    def stop(self):
        was = self._playing
        self._playing = False
        self._send("stop")
        self._override = (0, self._sent)
        if was:
            self.state_changed.emit()

    def seek_ms(self, milliseconds: int):
        milliseconds = max(0, int(milliseconds))
        self._send("seek", milliseconds)
        if not self._playing:
            self._override = (milliseconds, self._sent)

    # --- what is heard ---------------------------------------------------------------------
    def heard(self) -> tuple[int, dict | None]:
        """(milliseconds, row marker) of the audio the speakers are playing right now."""
        snap = self.snapshot()
        if self._override is not None:
            if snap["processed"] < self._override[1]:
                return self._override[0], None
            self._override = None
        return snap["ms"], snap["marker"]

    def position_ms(self) -> int:
        return self.heard()[0]

    def heard_levels(self):
        """(rms, peaks) reached since the last call, or None."""
        snap = self.snapshot()
        if snap["level_seq"] != self._level_seen and snap["playing"]:
            self._level_seen = snap["level_seq"]
            return snap["levels"]
        return None

    def core_thread_id(self) -> int:
        """Python thread id of the audio thread (what built the sink); mainly for tests and diagnostics."""
        return self.snapshot().get("thread", 0)

    def wait_idle(self, seconds: float = 5.0) -> bool:
        """Wait until the audio thread has handled every command sent so far (tests, shutdown)."""
        import time
        deadline = time.monotonic() + seconds
        while self.snapshot()["processed"] < self._sent and time.monotonic() < deadline:
            time.sleep(0.002)
        return self.snapshot()["processed"] >= self._sent

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._playing = False
        if self.thread.isRunning():
            self._stop_thread.emit()    # blocks until the audio thread has closed the sink and the engine
            self.thread.quit()
            self.thread.wait(3000)
