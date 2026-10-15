"""Bounded native replay in a child process, using the libxmp 4.x public ABI."""

from __future__ import annotations

import ctypes as C
import json
from pathlib import Path
import sys
import wave


class XmpEvent(C.Structure):
    _fields_ = [(name, C.c_ubyte) for name in
                ("note", "ins", "vol", "fxt", "fxp", "f2t", "f2p", "flag")]


class ChannelInfo(C.Structure):
    _fields_ = [("period", C.c_uint), ("position", C.c_uint), ("pitchbend", C.c_short)] + [
        (name, C.c_ubyte) for name in ("note", "instrument", "sample", "volume", "pan", "reserved")
    ] + [("event", XmpEvent)]


class FrameInfo(C.Structure):
    _fields_ = [(name, C.c_int) for name in (
        "pos", "pattern", "row", "num_rows", "frame", "speed", "bpm", "time", "total_time", "frame_time",
    )] + [("buffer", C.c_void_p)] + [(name, C.c_int) for name in (
        "buffer_size", "total_size", "volume", "loop_count", "virt_channels", "virt_used", "sequence",
    )] + [("channel_info", ChannelInfo * 64)]


class TestInfo(C.Structure):
    _fields_ = [("name", C.c_char * 64), ("type", C.c_char * 64)]


def render(source: Path, output: Path, seconds: float, sample_rate: int, library: Path) -> dict:
    dll = C.CDLL(str(library))
    prototypes = {
        "xmp_create_context": ([], C.c_void_p),
        "xmp_free_context": ([C.c_void_p], None),
        "xmp_test_module_from_memory": ([C.c_void_p, C.c_long, C.POINTER(TestInfo)], C.c_int),
        "xmp_load_module_from_memory": ([C.c_void_p, C.c_void_p, C.c_long], C.c_int),
        "xmp_start_player": ([C.c_void_p, C.c_int, C.c_int], C.c_int),
        "xmp_set_player": ([C.c_void_p, C.c_int, C.c_int], C.c_int),
        "xmp_get_player": ([C.c_void_p, C.c_int], C.c_int),
        "xmp_play_frame": ([C.c_void_p], C.c_int),
        "xmp_get_frame_info": ([C.c_void_p, C.POINTER(FrameInfo)], None),
        "xmp_end_player": ([C.c_void_p], None),
        "xmp_release_module": ([C.c_void_p], None),
    }
    for name, (arguments, result) in prototypes.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = arguments, result

    def checked(code: int, operation: str) -> None:
        if code < 0:
            raise RuntimeError(f"libxmp {operation}: erreur {code}.")

    data = source.read_bytes()
    buffer = C.create_string_buffer(data)
    info = TestInfo()
    checked(dll.xmp_test_module_from_memory(buffer, len(data), C.byref(info)), "test")
    ctx = dll.xmp_create_context()
    if not ctx:
        raise RuntimeError("Impossible de créer le lecteur libxmp.")
    loaded = started = False
    frames_written = 0
    target_frames = round(seconds * sample_rate)
    trace = []
    try:
        checked(dll.xmp_set_player(ctx, 10, 70), "default pan")
        checked(dll.xmp_load_module_from_memory(ctx, buffer, len(data)), "load")
        loaded = True
        checked(dll.xmp_start_player(ctx, sample_rate, 0), "start")
        started = True
        checked(dll.xmp_set_player(ctx, 11, 3), "ProTracker personality")
        current_flags = dll.xmp_get_player(ctx, 5)
        checked(current_flags, "current flags")
        # CFLAGS applies to the loaded module; FLAGS only configures future loads.
        checked(dll.xmp_set_player(ctx, 5, (current_flags | 8) & ~1), "PAL CIA / Amiga mixer flags")
        checked(dll.xmp_set_player(ctx, 1, 70), "stereo separation")
        checked(dll.xmp_set_player(ctx, 0, 1), "amplification")
        frame = FrameInfo()
        with wave.open(str(output), "wb") as audio:
            audio.setparams((2, 2, sample_rate, 0, "NONE", "not compressed"))
            for _ in range(50_000):
                if frames_written >= target_frames:
                    break
                code = dll.xmp_play_frame(ctx)
                if code == -1:  # XMP_END
                    break
                checked(code, "frame")
                dll.xmp_get_frame_info(ctx, C.byref(frame))
                if not frame.buffer or not 0 < frame.buffer_size <= sample_rate * 4:
                    raise RuntimeError("Taille de frame native invalide.")
                if frame.buffer_size % 4:
                    raise RuntimeError("Frame PCM stéréo non alignée.")
                if frame.frame == 0:
                    trace.append({
                        "seconds": round(frames_written / sample_rate, 9),
                        "order": frame.pos, "pattern": frame.pattern, "row": frame.row,
                        "speed": frame.speed, "bpm": frame.bpm, "loop_count": frame.loop_count,
                    })
                count = min(frame.buffer_size // 4, target_frames - frames_written)
                pcm = C.string_at(frame.buffer, count * 4)
                if sys.byteorder != "little":
                    from array import array
                    samples = array("h", pcm)
                    samples.byteswap()
                    pcm = samples.tobytes()
                audio.writeframesraw(pcm)
                frames_written += count
            else:
                raise RuntimeError("Nombre de frames natives dépassé.")
        return {
            "engine": "libxmp", "version": C.c_char_p.in_dll(dll, "xmp_version").value.decode("ascii"),
            "detected_title": info.name.decode("ascii", "replace"),
            "detected_format": info.type.decode("ascii", "replace"),
            "personality": "ProTracker", "mixer_type": dll.xmp_get_player(ctx, 12),
            "current_flags": dll.xmp_get_player(ctx, 5),
            "stereo_separation": 70, "frames": frames_written, "trace": trace,
        }
    finally:
        if started:
            dll.xmp_end_player(ctx)
        if loaded:
            dll.xmp_release_module(ctx)
        dll.xmp_free_context(ctx)


if __name__ == "__main__":
    try:
        result = render(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), Path(sys.argv[5]))
        print(json.dumps(result))
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
