"""Real-time MOD playback through libxmp, without Qt.

The engine renders 16-bit stereo PCM in small blocks on demand, so an audio output
can stream it while the song is edited: a reload keeps the playback position,
channel mutes apply on the next block, and every block carries the order/row it
came from so a view can follow what is actually heard. The exported MOD and the
rendered WAV/MP3 files still use the FFmpeg/libopenmpt path in `audio.py`.
"""

from __future__ import annotations

import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import sys

from . import formats
from ._xmp_worker import FrameInfo, replay_style
from .model import Module, ValidationError, playback_plan

ROOT = Path(__file__).resolve().parents[1]
XMP_END = -1
PLAYER_AMP, PLAYER_MIX, PLAYER_CFLAGS, PLAYER_DEFPAN, PLAYER_MODE = 0, 1, 5, 10, 11
MODE_PROTRACKER = 3
FLAGS_VBLANK_OFF_PAL = 8  # Same player flags as the libxmp reference worker (PAL CIA timing).


class RealtimeError(RuntimeError):
    pass


def find_library() -> Path | None:
    """Locate libxmp: CHIPLOOM_LIBXMP, a frozen build, the local reference build, then the system."""
    candidates = []
    if os.environ.get("CHIPLOOM_LIBXMP"):
        candidates.append(Path(os.environ["CHIPLOOM_LIBXMP"]))
    frozen = getattr(sys, "_MEIPASS", None)
    for folder in filter(None, (frozen, Path(sys.executable).parent if getattr(sys, "frozen", False) else None)):
        candidates += [Path(folder) / name for name in ("libxmp.dll", "xmp.dll", "libxmp.so.4", "libxmp.dylib")]
    manifest = ROOT / ".tools/libxmp/manifest.json"
    try:
        candidates.append(Path(json.loads(manifest.read_text(encoding="utf-8"))["library"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    name = ctypes.util.find_library("xmp")
    if name:
        return Path(name)
    if sys.platform.startswith("linux"):
        for name in ("libxmp.so.4", "libxmp.so"):
            try:
                C.CDLL(name)
                return Path(name)
            except OSError:
                continue
    return None


class XmpEngine:
    """One libxmp player context. Not thread-safe: drive it from a single thread."""

    def __init__(self, library: Path | None = None, sample_rate: int = 48000):
        library = library or find_library()
        if library is None:
            raise RealtimeError("libxmp was not found; real-time playback is unavailable. Run "
                                "`python tools/setup_reference.py`, install libxmp, or set CHIPLOOM_LIBXMP.")
        try:
            self._dll = C.CDLL(str(library))
        except OSError as exc:
            raise RealtimeError(f"libxmp could not be loaded from {library}: {exc}") from exc
        prototypes = {
            "xmp_create_context": ([], C.c_void_p),
            "xmp_free_context": ([C.c_void_p], None),
            "xmp_load_module_from_memory": ([C.c_void_p, C.c_void_p, C.c_long], C.c_int),
            "xmp_release_module": ([C.c_void_p], None),
            "xmp_start_player": ([C.c_void_p, C.c_int, C.c_int], C.c_int),
            "xmp_end_player": ([C.c_void_p], None),
            "xmp_play_frame": ([C.c_void_p], C.c_int),
            "xmp_get_frame_info": ([C.c_void_p, C.POINTER(FrameInfo)], None),
            "xmp_set_player": ([C.c_void_p, C.c_int, C.c_int], C.c_int),
            "xmp_get_player": ([C.c_void_p, C.c_int], C.c_int),
            "xmp_set_position": ([C.c_void_p, C.c_int], C.c_int),
            "xmp_channel_mute": ([C.c_void_p, C.c_int, C.c_int], C.c_int),
        }
        for name, (arguments, result) in prototypes.items():
            try:
                function = getattr(self._dll, name)
            except AttributeError as exc:
                raise RealtimeError(f"This libxmp lacks {name}; version 4.5 or newer is required.") from exc
            function.argtypes, function.restype = arguments, result
        self.library = Path(library)
        self.sample_rate = sample_rate
        self.version = C.c_char_p.in_dll(self._dll, "xmp_version").value.decode("ascii")
        self._ctx = self._dll.xmp_create_context()
        if not self._ctx:
            raise RealtimeError("libxmp could not create a player context.")
        self._buffer = None
        self._size = 0
        self._loaded = self._started = False
        self._pending = b""
        self._pending_marker: dict | None = None
        self._times: dict[tuple[int, int], float] = {}
        self._frame = FrameInfo()
        self.channels = 4
        self.audible = (True, True, True, True)
        self.loop = True
        self.finished = False
        self.plan: dict | None = None
        self.position = {"order": 0, "pattern": 0, "row": 0, "speed": 6, "bpm": 125, "loop_count": 0}

    # --- lifecycle ------------------------------------------------------------------

    def _check(self, code: int, operation: str) -> int:
        if code < 0:
            raise RealtimeError(f"libxmp {operation} failed ({code}).")
        return code

    def _unload(self) -> None:
        if self._started:
            self._dll.xmp_end_player(self._ctx)
            self._started = False
        if self._loaded:
            self._dll.xmp_release_module(self._ctx)
            self._loaded = False

    def load(self, module: Module, order: int = 0, row: int = 0) -> None:
        """Load (or reload) a module and continue from `order`/`row` with its replay state."""
        # Canonical bytes: libxmp 4.7 can crash in the start-up sequence below on modules whose
        # header carries a restart byte or other imported oddities (see formats.encode_for_replay).
        payload = formats.encode_for_replay(module)
        self.channels = module.channels
        self._style = replay_style(payload)
        if len(self.audible) != module.channels:  # keep the states of the channels both modules share
            self.audible = tuple((self.audible + (True,) * module.channels)[:module.channels])
        plan = playback_plan(module)
        self._buffer = C.create_string_buffer(payload, len(payload))
        self._size = len(payload)
        self.plan = plan
        self._times = {}
        for item in plan["timeline"]:
            self._times.setdefault((item["order"], item["row"]), item["seconds"])
        self.seek(order, row)

    def _restart(self) -> None:
        """Start a fresh libxmp player on the encoded module (a few milliseconds)."""
        self._unload()
        self._check(self._dll.xmp_set_player(self._ctx, PLAYER_DEFPAN, 70), "default pan")
        self._check(self._dll.xmp_load_module_from_memory(self._ctx, self._buffer, self._size), "load")
        self._loaded = True
        self._check(self._dll.xmp_start_player(self._ctx, self.sample_rate, 0), "start")
        self._started = True
        style = self._style
        if style != "xm":  # an XM keeps libxmp's FastTracker II personality
            self._check(self._dll.xmp_set_player(self._ctx, PLAYER_MODE, MODE_PROTRACKER), "ProTracker personality")
            flags = self._check(self._dll.xmp_get_player(self._ctx, PLAYER_CFLAGS), "flags")
            # The A500 mixer flag crashes libxmp 4.7 on MODs it does not recognise as ProTracker (see replay_style).
            wanted = (flags | FLAGS_VBLANK_OFF_PAL) & ~1 if style == "mod" else flags & ~1
            self._check(self._dll.xmp_set_player(self._ctx, PLAYER_CFLAGS, wanted), "flags")
        self._check(self._dll.xmp_set_player(self._ctx, PLAYER_MIX, 70), "stereo separation")
        self._check(self._dll.xmp_set_player(self._ctx, PLAYER_AMP, 1), "amplification")
        self.set_audible(self.audible)

    def reload(self, module: Module) -> None:
        """Swap in an edited module at the current playback position."""
        self.load(module, self.position["order"], self.position["row"])

    def close(self) -> None:
        if self._ctx:
            self._unload()
            self._dll.xmp_free_context(self._ctx)
            self._ctx = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # --- control ----------------------------------------------------------------------

    def seek(self, order: int, row: int = 0) -> None:
        """Jump to the first visit of an order/row in the playback plan.

        Every seek starts a fresh player, which makes the result independent of where playback
        was. libxmp applies a position change only after its first frame, keeps no tempo on a row
        jump and ignores a jump to the order it is already playing, so the player enters the order
        and plays silently up to the row (a few milliseconds).
        """
        if self.plan is None:
            raise RealtimeError("No module is loaded.")
        timeline = self.plan["timeline"]
        entry = next((item for item in timeline if item["order"] == order and item["row"] == row), None)
        entry = entry or next((item for item in timeline if item["order"] == order), timeline[0])
        self._restart()
        self._pending, self._pending_marker = b"", None
        self.finished = False
        pcm, marker = self._next_frame()
        if entry["order"] != 0:
            # The call returns the new position; -1 (XMP_END) only means "applied on the next frame".
            if self._dll.xmp_set_position(self._ctx, entry["order"]) < -1:
                raise RealtimeError("libxmp set position failed.")
            pcm, marker = None, None
        for _ in range(64 * 32):
            if marker and (marker["order"], marker["row"]) == (entry["order"], entry["row"]):
                self._pending, self._pending_marker = pcm, marker
                break
            pcm, marker = self._next_frame()
            if pcm is None:
                break
        self.position.update(order=entry["order"], pattern=entry["pattern"], row=entry["row"],
                             speed=entry["speed"], bpm=entry["bpm"])

    def seek_seconds(self, seconds: float) -> None:
        if self.plan is None:
            raise RealtimeError("No module is loaded.")
        timeline = self.plan["timeline"]
        target = timeline[0]
        for item in timeline:
            if item["seconds"] > seconds:
                break
            target = item
        self.seek(target["order"], target["row"])

    def set_audible(self, audible: tuple[bool, ...]) -> None:
        if len(audible) != self.channels:
            raise ValidationError(f"{self.channels} channel states are expected.")
        self.audible = tuple(bool(value) for value in audible)
        if self._started:
            for channel, on in enumerate(self.audible):
                self._dll.xmp_channel_mute(self._ctx, channel, 0 if on else 1)

    # --- rendering ----------------------------------------------------------------------

    def _next_frame(self) -> tuple[bytes | None, dict | None]:
        """Play one libxmp frame: (PCM, row marker or None), or (None, None) when playback ends."""
        code = self._dll.xmp_play_frame(self._ctx)
        if code == XMP_END:
            self.finished = True
            return None, None
        self._check(code, "frame")
        self._dll.xmp_get_frame_info(self._ctx, C.byref(self._frame))
        info = self._frame
        if info.loop_count > 0 and not self.loop:
            self.finished = True
            return None, None
        if not info.buffer or info.buffer_size <= 0 or info.buffer_size % 4:
            raise RealtimeError("libxmp returned an invalid audio frame.")
        pcm = C.string_at(info.buffer, info.buffer_size)
        if sys.byteorder != "little":
            from array import array
            samples = array("h", pcm)
            samples.byteswap()
            pcm = samples.tobytes()
        if info.frame != 0:
            return pcm, None
        # Song time comes from the playback plan: libxmp's own clock restarts at every seek.
        marker = {"order": info.pos, "pattern": info.pattern, "row": info.row, "speed": info.speed,
                  "bpm": info.bpm, "seconds": self._times.get((info.pos, info.row), info.time / 1000),
                  "loop_count": info.loop_count}
        self.position.update({key: marker[key] for key in ("order", "pattern", "row", "speed", "bpm")},
                             loop_count=info.loop_count)
        return pcm, marker

    def render(self, frames: int) -> tuple[bytes, list[dict]]:
        """Return up to `frames` stereo frames (little-endian int16) and row markers.

        Each marker is `{"frame": offset in this block, "order", "pattern", "row", "speed", "bpm",
        "seconds"}` at the start of a new row. An empty result means playback finished (loop off).
        """
        if not self._started:
            raise RealtimeError("No module is loaded.")
        wanted = frames * 4
        chunks, size, markers = [], 0, []
        if self._pending:
            if self._pending_marker:
                markers.append({**self._pending_marker, "frame": 0})
                self._pending_marker = None
            take = self._pending[:wanted]
            self._pending = self._pending[len(take):]
            chunks.append(take)
            size += len(take)
        while size < wanted and not self.finished:
            pcm, marker = self._next_frame()
            if pcm is None:
                break
            room = wanted - size
            if marker:
                markers.append({**marker, "frame": size // 4})
            chunks.append(pcm[:room])
            size += min(room, len(pcm))
            if len(pcm) > room:
                self._pending = pcm[room:]
        return b"".join(chunks), markers
