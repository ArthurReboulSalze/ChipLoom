"""Render a section of a song to a WAV for the browser's audio element (MOD with 2-32 channels, or XM).

With libxmp (`realtime.XmpEngine`) a section renders in a fraction of its length, from any
order/row and with channel mutes, and needs no FFmpeg. Without libxmp the FFmpeg/libopenmpt path
of `audio.py` renders from the start of the order (the row is ignored; muted channels keep only
their flow and timing effects). Both paths are bounded by `MAX_SECONDS`.
"""

from __future__ import annotations

import io
import math
import shutil
import tempfile
import wave
from pathlib import Path

from .. import audio, formats, realtime
from ..model import EMPTY, Cell, Module, Pattern, ValidationError, playback_plan, require_int

SAMPLE_RATE = 44100
DEFAULT_SECONDS = 20.0
MAX_SECONDS = 60.0
BLOCK_FRAMES = 4096
FLOW_COMMANDS = (0xB, 0xD, 0xF)        # position jump, pattern break, speed/tempo (the same numbers in MOD and XM)
FLOW_EXTENDED = (0x6, 0xE)             # E6x pattern loop and EEx pattern delay change the row flow too


class RenderUnavailable(ValidationError):
    """Neither libxmp nor FFmpeg can render on this machine."""

    def __init__(self, message: str):
        super().__init__(message, "LIVE_RENDER_UNAVAILABLE")


def engine_name() -> str | None:
    """"libxmp" (fast, any row), "ffmpeg" (from the start of an order) or None."""
    if realtime.find_library() is not None:
        return "libxmp"
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None


def check_params(module: Module, order: object, row: object, seconds: object, audible: object) -> tuple:
    order = require_int(order, "order", 0, len(module.orders) - 1)
    row = require_int(row, "row", 0, module.patterns[module.orders[order]].rows - 1)   # XM patterns have 1-256 rows
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0.5 <= seconds <= MAX_SECONDS:
        raise ValidationError(f"seconds: a number between 0.5 and {MAX_SECONDS:g} expected.", "LIVE_RENDER")
    if audible is None:
        audible = (True,) * module.channels
    if (not isinstance(audible, (list, tuple)) or len(audible) != module.channels
            or not all(type(item) is bool for item in audible)):
        raise ValidationError(f"audible: {module.channels} true/false values (one per channel) expected.", "LIVE_RENDER")
    if not any(audible):
        raise ValidationError("audible: at least one channel must stay on.", "LIVE_RENDER")
    return order, row, float(seconds), tuple(audible)


def _wav(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((2, 2, rate, len(pcm) // 4, "NONE", "not compressed"))
        writer.writeframes(pcm)
    return buffer.getvalue()


def _with_libxmp(module: Module, order: int, row: int, seconds: float, audible: tuple) -> tuple[bytes, dict]:
    try:
        engine = realtime.XmpEngine(sample_rate=SAMPLE_RATE)
    except realtime.RealtimeError as exc:
        raise RenderUnavailable(str(exc)) from exc
    try:
        engine.audible, engine.loop = audible, False
        try:
            engine.load(module, order, row)
        except realtime.RealtimeError as exc:
            raise ValidationError(f"The section cannot be rendered: {exc}", "LIVE_RENDER") from exc
        start = {"order": engine.position["order"], "row": engine.position["row"]}
        wanted, chunks, frames = round(seconds * SAMPLE_RATE), [], 0
        while frames < wanted:
            data, _ = engine.render(min(BLOCK_FRAMES, wanted - frames))
            if not data:
                break
            chunks.append(data)
            frames += len(data) // 4
    except realtime.RealtimeError as exc:
        raise ValidationError(f"The section cannot be rendered: {exc}", "LIVE_RENDER") from exc
    finally:
        engine.close()
    if not frames:
        raise ValidationError("Nothing to play from that position.", "LIVE_RENDER")
    return _wav(b"".join(chunks), SAMPLE_RATE), {"engine": "libxmp", "sample_rate": SAMPLE_RATE, **start,
                                                 "seconds": round(frames / SAMPLE_RATE, 3)}


def _muted_copy(module: Module, audible: tuple) -> Module:
    if all(audible):
        return module
    clone = Module(module.title, list(module.samples),
                   [Pattern(item.name, dict(item.cells), item.rows) for item in module.patterns],
                   list(module.orders), module.metadata, module.channels, module.format)
    for pattern in clone.patterns:
        for (row, channel), value in list(pattern.cells.items()):
            if not audible[channel]:
                flow = value.command in FLOW_COMMANDS or (value.command == 0xE and value.param >> 4 in FLOW_EXTENDED)
                pattern.put(row, channel, Cell(0, 0, value.command, value.param) if flow else EMPTY)
    return clone


def _with_ffmpeg(module: Module, order: int, row: int, seconds: float, audible: tuple) -> tuple[bytes, dict]:
    with tempfile.TemporaryDirectory(prefix="chiploom-web-") as directory:
        source, output = Path(directory) / f"section{formats.extension(module)}", Path(directory) / "section.wav"
        source.write_bytes(formats.encode(_muted_copy(module, audible)))
        try:
            audio.render(source, output, "openmpt", seconds=min(seconds, audio.MAX_RENDER_SECONDS),
                         sample_rate=SAMPLE_RATE, from_order=order)
        except audio.RenderError as exc:
            raise RenderUnavailable(str(exc)) from exc
        data = output.read_bytes()
    return data, {"engine": "ffmpeg", "sample_rate": SAMPLE_RATE, "order": order, "row": 0,
                  "seconds": round(min(seconds, audio.MAX_RENDER_SECONDS), 3),
                  "note": "FFmpeg starts at the beginning of the order; install libxmp to start at a row."}


def render_wav(module: Module, order: int = 0, row: int = 0, seconds: float = DEFAULT_SECONDS,
               audible: object = None, engine: str | None = None) -> tuple[bytes, dict]:
    """A 16-bit stereo WAV of `module` from `order`/`row`, at most `seconds` long, plus its description."""
    order, row, seconds, audible = check_params(module, order, row, seconds, audible)
    playback_plan(module)  # validates the module; a broken song is refused before any native code runs
    chosen = engine or engine_name()
    if chosen is None:
        raise RenderUnavailable("Listening in the browser needs libxmp (python tools/setup_reference.py) or FFmpeg with "
                                "libopenmpt; neither was found on the computer running ChipLoom.")
    data, info = (_with_libxmp if chosen == "libxmp" else _with_ffmpeg)(module, order, row, seconds, audible)
    return data, {**info, "audible": list(audible), "bytes": len(data)}
