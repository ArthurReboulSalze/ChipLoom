"""Render the actual exported file, with explicit native backends and time bounds."""

from __future__ import annotations

from array import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave

from . import formats, project
from ._xmp_worker import master_volume
from .model import NOTE_TO_PERIOD, PAL_CLOCK, Sample, ValidationError, playback_plan, require_int

ROOT = Path(__file__).resolve().parents[1]
MAX_RENDER_SECONDS = 120
MAX_PREROLL_SECONDS = 600
# Child renderers must not flash console windows when started from pythonw/Qt.
SUBPROCESS_OPTIONS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def duration_warnings(seconds: float) -> list[str]:
    return ([f"Duration {seconds:.2f} s exceeds the {MAX_RENDER_SECONDS} s render limit. "
             "Render a section with --seconds (and optionally --from-order), or shorten the arrangement."]
            if seconds > MAX_RENDER_SECONDS else [])


class RenderError(RuntimeError):
    """A renderer failure. `code` is a stable identifier for agents (see errors.py)."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze_wav(path: Path) -> dict:
    peak = square_sum = total = clipped = sum_value = 0
    first, last = None, None
    quiet_run = longest_quiet = windows = 0
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise RenderError("L'analyse attend du PCM signé 16 bits.", "RENDER_FAILED")
        channels, rate, frames = audio.getnchannels(), audio.getframerate(), audio.getnframes()
        while payload := audio.readframes(max(1, rate // 10)):
            values = array("h", payload)
            if sys.byteorder != "little":
                values.byteswap()
            block_peak = max(abs(value) for value in values)
            peak = max(peak, block_peak)
            square_sum += sum(value * value for value in values)
            sum_value += sum(values)
            clipped += sum(value >= 32767 or value <= -32768 for value in values)
            total += len(values)
            if first is None:
                first = list(values[:channels])
            last = list(values[-channels:])
            quiet_run = quiet_run + 1 if block_peak < 32 else 0
            longest_quiet = max(longest_quiet, quiet_run)
            windows += 1
    if not total:
        raise RenderError("Le lecteur a produit un fichier audio vide.", "RENDER_FAILED")
    rms = math.sqrt(square_sum / total) / 32768
    return {
        "sample_rate": rate, "channels": channels, "frames": frames,
        "duration_seconds": round(frames / rate, 9),
        "peak": round(peak / 32768, 6),
        "peak_dbfs": round(20 * math.log10(peak / 32768), 3) if peak else None,
        "rms_dbfs": round(20 * math.log10(rms), 3) if rms else None,
        "dc_mean": round(sum_value / total / 32768, 8), "clipped_samples": clipped,
        "longest_quiet_window_seconds": round(longest_quiet * 0.1, 3),
        "quiet_threshold": "peak below -60 dBFS in 100 ms windows",
        "boundary_jump": max(abs(a - b) for a, b in zip(first, last)) / 32768,
        "sha256": sha256(path),
    }


def default_xmp_library() -> Path:
    manifest = ROOT / ".tools/libxmp/manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        library = Path(data["library"])
        if library.is_file() and sha256(library) == data["library_sha256"]:
            return library
    raise RenderError("libxmp n'est pas prêt. Exécute python tools/setup_reference.py, ou indique --xmp-library.",
                      "XMP_MISSING")


def render(source: Path, output: Path, engine: str = "openmpt", seconds: float | None = None,
           sample_rate: int = 48000, ffmpeg: str | None = None, xmp_library: Path | None = None,
           from_order: int | None = None) -> dict:
    """Render a module file (MOD or XM) or a `.json` project to a 16-bit stereo WAV.

    A project is encoded to a temporary module file of its own format, rendered, then removed;
    `source_sha256` is then the project file's hash and `module_sha256` the encoded module's."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.suffix.lower() != ".wav":
        raise ValidationError("Le rendu principal doit avoir une extension .wav ; utilise l'option MP3 pour une "
                              "copie d'écoute.", "OUTPUT_PATH")
    if source == output:
        raise ValidationError("Le rendu audio doit avoir un chemin distinct du module source.", "OUTPUT_PATH")
    if source.suffix.lower() != ".json":
        return _render_module(formats.read(source), source, output, engine, seconds, sample_rate, ffmpeg,
                              xmp_library, from_order)
    module = project.load(source)
    with tempfile.TemporaryDirectory(prefix="chiploom-render-") as directory:
        module_file = Path(directory) / f"project{formats.extension(module)}"
        module_file.write_bytes(formats.encode(module))
        details = _render_module(module, module_file, output, engine, seconds, sample_rate, ffmpeg,
                                 xmp_library, from_order)
    details.update(module_sha256=details["source_sha256"], source_sha256=sha256(source), source_kind="project",
                   module_format=module.format)
    return details


def _render_module(module, source: Path, output: Path, engine: str, seconds: float | None, sample_rate: int,
                   ffmpeg: str | None, xmp_library: Path | None, from_order: int | None) -> dict:
    plan = playback_plan(module)
    start_seconds = 0.0
    if from_order is not None:
        require_int(from_order, "from_order", 0, len(module.orders) - 1)
        entry = next((row for row in plan["timeline"] if row["order"] == from_order), None)
        if entry is None:
            raise ValidationError("Cet ordre n'est pas atteint pendant le premier cycle de lecture.", "RENDER_LIMIT")
        start_seconds = entry["seconds"]
        if start_seconds > MAX_PREROLL_SECONDS:
            raise ValidationError(f"Le début de l'extrait dépasse la limite de prélecture de {MAX_PREROLL_SECONDS} "
                                  "secondes.", "RENDER_LIMIT")
    available = plan["duration_seconds"] - start_seconds
    if seconds is None:
        seconds = available
    if not math.isfinite(seconds) or not 0 < seconds <= MAX_RENDER_SECONDS:
        raise ValidationError("Un rendu doit durer plus de zéro et au maximum 120 secondes.", "RENDER_LIMIT")
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 96000:
        raise ValidationError("La fréquence de rendu doit être comprise entre 8000 et 96000 Hz.", "RENDER_LIMIT")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".wav", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    executable = ffmpeg or shutil.which("ffmpeg")
    try:
        if engine == "openmpt":
            if not executable:
                raise RenderError("FFmpeg avec libopenmpt est requis pour ce moteur de rendu.", "FFMPEG_MISSING")
            version_result = subprocess.run(
                [executable, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10,
                **SUBPROCESS_OPTIONS,
            )
            result = subprocess.run(
                [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-f", "libopenmpt", "-sample_rate", str(sample_rate), "-layout", "stereo",
                 "-i", str(source), "-ss", f"{start_seconds:.9f}",
                 "-t", f"{seconds:.9f}", "-map", "0:a:0", "-vn",
                 "-ac", "2", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(temporary)],
                capture_output=True, text=True, timeout=60,
                **SUBPROCESS_OPTIONS,
            )
            if result.returncode:
                raise RenderError(f"FFmpeg/libopenmpt : {result.stderr.strip()[-2000:]}", "RENDER_FAILED")
            details = {"engine": "libopenmpt via FFmpeg", "version": version_result.stdout.splitlines()[0],
                       "stderr": result.stderr.strip(), "trace": None}
        elif engine == "xmp":
            library = (xmp_library or default_xmp_library()).resolve()
            # libxmp 4.7.3 can crash on some header variants (restart byte, FLT4/4CHN): replay a copy
            # with the same music and normalised headers (see formats.encode_for_replay).
            replay = temporary.with_name(temporary.stem + ".replay" + formats.extension(module))
            replay.write_bytes(formats.encode_for_replay(module))
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "tracker4agents._xmp_worker", str(replay), str(temporary),
                     str(seconds), str(sample_rate), str(library), str(start_seconds),
                     str(master_volume(module.format, module.channels))],
                    cwd=ROOT, capture_output=True, text=True, timeout=60,
                    **SUBPROCESS_OPTIONS,
                )
            finally:
                replay.unlink(missing_ok=True)
            if result.returncode:
                raise RenderError(f"Processus libxmp (code {result.returncode}) : {result.stderr.strip()[-2000:]}",
                                  "RENDER_FAILED")
            details = json.loads(result.stdout)
            details["library_sha256"] = sha256(library)
        else:
            raise ValidationError(f"Moteur audio inconnu : {engine}.", "INVALID_VALUE")
        metrics = analyze_wav(temporary)
        if metrics["frames"] < min(256, round(seconds * sample_rate)):
            raise RenderError("Le moteur a produit trop peu de données audio.", "RENDER_FAILED")
        os.replace(temporary, output)
        details.update(source_sha256=sha256(source), requested_seconds=seconds,
                       from_order=from_order, start_seconds=start_seconds,
                       output=str(output), audio=metrics)
        details["loudness"] = measure_loudness(output, executable)
        warnings = duration_shortfall(seconds, available, metrics["duration_seconds"])
        details["ended_before_requested"] = bool(warnings)
        if warnings:
            details["module_seconds"] = round(available, 6)
            details["warnings"] = warnings
        return details
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Le rendu a dépassé sa limite de temps et a été interrompu.", "RENDER_TIMEOUT") from exc
    finally:
        temporary.unlink(missing_ok=True)


def duration_shortfall(requested: float, available: float, rendered: float) -> list[str]:
    """A warning when the module ends (one playback cycle) before the requested length."""
    if requested <= available + 0.05 or rendered >= requested - 0.05:
        return []
    return [f"The module ends after {available:.2f} s of playback from the start point (one cycle), so the "
            f"render is {rendered:.2f} s instead of the requested {requested:.2f} s. Renders do not loop the song."]


_EBUR128 = {
    "integrated_lufs": re.compile(r"Integrated loudness:\s*I:\s*(-?inf|-?[\d.]+)\s*LUFS"),
    "lra_lu": re.compile(r"Loudness range:\s*LRA:\s*(-?inf|-?[\d.]+)\s*LU"),
    "true_peak_dbtp": re.compile(r"True peak:\s*Peak:\s*(-?inf|-?[\d.]+)\s*dBFS"),
}
LOUDNESS_METHOD = "FFmpeg ebur128 filter (EBU R 128 / ITU-R BS.1770; true peak by oversampling)"


def measure_loudness(wav: Path, ffmpeg: str | None = None) -> dict:
    """EBU R 128 integrated loudness, loudness range and true peak of a WAV, measured by FFmpeg.

    Without FFmpeg (the libxmp engine renders without it) nothing is measured and `reason`
    says why. Values FFmpeg reports as -inf (silence) are null."""
    empty = {"integrated_lufs": None, "true_peak_dbtp": None, "lra_lu": None, "method": None}
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        return {**empty, "reason": "FFmpeg was not found, so loudness was not measured."}
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-nostats", "-nostdin", "-i", str(wav),
             "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **SUBPROCESS_OPTIONS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**empty, "reason": f"The FFmpeg loudness measurement failed: {exc}"}
    position = result.stderr.rfind("Summary:")
    if result.returncode or position < 0:
        return {**empty, "reason": "FFmpeg did not report an EBU R 128 summary: " + result.stderr.strip()[-300:]}
    summary = result.stderr[position:]
    values = {}
    for key, pattern in _EBUR128.items():
        match = pattern.search(summary)
        values[key] = None if match is None or "inf" in match.group(1) else float(match.group(1))
    return {**values, "method": LOUDNESS_METHOD}


def sample_preview(sample: Sample, output: Path, fmt: str = "mod") -> None:
    """Preview a sample at its C-2 (MOD) or C-4 (XM) playback rate, with loops repeated for one second."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "xm":
        # FastTracker II plays C-4 of a sample at 8363 Hz, shifted by relative note and finetune (1/128 semitone).
        rate = round(8363 * 2 ** (sample.relative_note / 12 + sample.finetune / (128 * 12)))
    else:
        # Integer C-2 periods, finetunes 0..7 then -8..-1, from ProTracker tuning.
        periods = (428, 425, 422, 419, 416, 413, 410, 407, 453, 450, 447, 444, 441, 437, 434, 431)
        rate = round(PAL_CLOCK / periods[sample.finetune & 15])
    pcm = sample.pcm
    if sample.loop_length:
        loop = pcm[sample.loop_start:sample.loop_start + sample.loop_length]
        target = rate
        pcm = (pcm[:sample.loop_start] + loop * (target // len(loop) + 1))[:target]
    scale = 256 if sample.bits == 8 else 1  # 16-bit PCM is already at WAV scale
    values = array("h", (round(value * scale * sample.volume / 64) for value in pcm))
    if sys.byteorder != "little":
        values.byteswap()
    with wave.open(str(output), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(values.tobytes())


def export_mp3(source_wav: Path, output: Path, ffmpeg: str | None = None) -> dict:
    """Optional listening copy, always encoded from a rendered WAV."""
    source_wav, output = source_wav.resolve(), output.resolve()
    if output.suffix.lower() != ".mp3" or source_wav == output:
        raise ValidationError("La copie d'écoute doit avoir un chemin .mp3 distinct du WAV.", "OUTPUT_PATH")
    metrics = analyze_wav(source_wav)
    if metrics["duration_seconds"] > 120:
        raise ValidationError("La copie MP3 est limitée à 120 secondes dans le prototype.", "RENDER_LIMIT")
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        raise RenderError("FFmpeg est requis pour la copie MP3 optionnelle.", "FFMPEG_MISSING")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".mp3", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-i", str(source_wav), "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "2",
             "-metadata", "artist=ChipLoom", str(temporary)],
            capture_output=True, text=True, timeout=60,
            **SUBPROCESS_OPTIONS,
        )
        if result.returncode or temporary.stat().st_size < 256:
            raise RenderError(f"Export MP3 : {result.stderr.strip()[-2000:]}", "RENDER_FAILED")
        os.replace(temporary, output)
        return {"output": str(output), "codec": "MP3 / libmp3lame VBR quality 2",
                "source_wav_sha256": metrics["sha256"], "sha256": sha256(output),
                "bytes": output.stat().st_size}
    except subprocess.TimeoutExpired as exc:
        raise RenderError("L'export MP3 a dépassé sa limite de temps.", "RENDER_TIMEOUT") from exc
    finally:
        temporary.unlink(missing_ok=True)


def audition_sample(sample: Sample, output: Path, note: str = "C-2", seconds: float = 1.0) -> dict:
    """Raw sample audition at a tracker note: its own volume, fine tune and loop, no pattern effects.

    Writes a 16-bit mono 44.1 kHz WAV and needs no external decoder.
    """
    if note not in NOTE_TO_PERIOD or not math.isfinite(seconds) or not .05 <= seconds <= 5:
        raise ValidationError("Audition requires a tracker note C-1..B-3 and 0.05–5 seconds.", "INVALID_VALUE")
    values, start, length = sample.pcm, sample.loop_start, sample.loop_length
    if length and (length < 4 or start + length > len(values)):
        raise ValidationError("Cannot audition an invalid loop.", "SAMPLE_LOOP")
    rate = PAL_CLOCK / NOTE_TO_PERIOD[note] * 2 ** (sample.finetune / 96)
    frame_count = round(seconds * 44100)
    pcm = array("h")
    for frame in range(frame_count):
        position = frame * rate / 44100
        if length and position >= start + length:
            position = start + (position - start) % length
        index = int(position)
        value = values[index] if index < len(values) else 0
        pcm.append(round(value * 256 * sample.volume / 64))
    if sys.byteorder != "little":
        pcm.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((1, 2, 44100, frame_count, "NONE", "not compressed"))
        writer.writeframes(pcm.tobytes())
    project.atomic_bytes(Path(output), buffer.getvalue())
    return {"output": str(Path(output)), "note": note, "seconds": seconds, "sample_rate": 44100,
            "playback_rate": rate,
            "description": "Raw sample with original volume, fine tune and loop; no pattern effects."}
