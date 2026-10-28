"""Jam voices: a few notes of a sample, mixed into the outgoing audio stream with int16 saturation.

Qt-free and standard library only, so it is easy to test. `JamMixer.mix(pcm)` adds the voices to a block of
16-bit stereo little-endian PCM (what the sink is fed); with no song playing the audio core mixes into
silence. A voice reads its sample straight from the scaled PCM at the ProTracker rate of its note and fine
tune (the same maths as `sample_tools.render_wav`), block by block, so a key press costs no pre-rendering:
the first block is ready on the next tick.

Key release: a looped sample fades out in about 10 ms; a one-shot plays to its end, as in ProTracker.

An XM sample plays at the FastTracker II rate of its note (C-4 is 8363 Hz at relative note 0, one semitone per
note, the fine tune in 1/128 semitone), 16-bit samples keep their depth and a ping-pong loop runs back and forth.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import io
import sys
import wave

from .model import NOTE_TO_PERIOD, PAL_CLOCK, XM_NOTE_TO_NUMBER, Sample, ValidationError

SAMPLE_RATE = 48000
MAX_VOICES = 6          # at least four notes at once; beyond this the oldest is stolen
RELEASE_MS = 10
JAM_GAIN = 0.8          # headroom for a chord of jam voices (and the song under it)
CACHE_SIZE = 24


@dataclass
class Voice:
    key: int
    note: str
    name: str
    scaled: list[int]        # the sample's bytes scaled to int16 at its volume
    step: float              # sample bytes per output frame
    loop_start: int
    loop_length: int
    pos: float = 0.0
    releasing: bool = False
    fade_left: int = 0
    fade_total: int = 1
    done: bool = False
    pingpong: bool = False   # an XM loop that runs forward then backward

    @property
    def looped(self) -> bool:
        return bool(self.loop_length)

    def render(self, frames: int) -> list[int]:
        scaled, step, pos = self.scaled, self.step, self.pos
        if self.looped:
            start, length = self.loop_start, self.loop_length
            end = start + length
            if self.pingpong:
                period = 2 * length

                def at(p: float) -> int:
                    if p < end:
                        return scaled[int(p)]
                    offset = int(p - start) % period
                    return scaled[start + (offset if offset < length else period - 1 - offset)]

                out = [at(p) for p in (pos + index * step for index in range(frames))]
                pos += frames * step
                if pos >= end:
                    pos = start + (pos - start) % period
            else:
                out = [scaled[int(p)] if p < end else scaled[start + int(p - start) % length]
                       for p in (pos + index * step for index in range(frames))]
                pos += frames * step
                if pos >= end:
                    pos = start + (pos - start) % length
        else:
            count = len(scaled)
            out = [scaled[int(p)] if p < count else 0 for p in (pos + index * step for index in range(frames))]
            pos += frames * step
            if pos >= count:
                self.done = True
        if self.releasing:
            total, left = self.fade_total, self.fade_left
            out = [int(value * max(0, left - index) / total) for index, value in enumerate(out)]
            self.fade_left = left - frames
            if self.fade_left <= 0:
                self.done = True
        self.pos = pos
        return out


class JamMixer:
    def __init__(self, rate: int = SAMPLE_RATE, max_voices: int = MAX_VOICES):
        self.rate, self.max_voices = rate, max_voices
        self.voices: list[Voice] = []
        self._scaled: dict[tuple[int, int], list[int]] = {}

    @property
    def active(self) -> bool:
        return any(not voice.done for voice in self.voices)

    def _scale(self, sample: Sample) -> list[int]:
        key = (hash(sample.pcm), sample.volume, sample.bits)
        if key not in self._scaled:
            if len(self._scaled) >= CACHE_SIZE:
                self._scaled.pop(next(iter(self._scaled)))
            gain = (256 if sample.bits == 8 else 1) * sample.volume / 64 * JAM_GAIN   # 16-bit PCM is at WAV scale
            self._scaled[key] = [int(value * gain) for value in sample.pcm]
        return self._scaled[key]

    def note_on(self, key: int, note: str, sample: Sample, name: str = "", fmt: str = "mod") -> Voice | None:
        """Start a voice for `sample` at `note` (C-1..B-3 for a MOD, C-0..B-7 for an XM). The oldest voice is
        stolen beyond `max_voices`."""
        if not sample.pcm:
            return None
        if fmt == "xm":
            number = XM_NOTE_TO_NUMBER.get(note)
            if number is None:
                return None
            rate = 8363 * 2 ** ((number - 49 + sample.relative_note) / 12 + sample.finetune / 1536)
        elif note in NOTE_TO_PERIOD:
            rate = PAL_CLOCK / NOTE_TO_PERIOD[note] * 2 ** (sample.finetune / 96)
        else:
            return None
        live = [voice for voice in self.voices if not voice.done]
        for voice in live[:max(0, len(live) - self.max_voices + 1)]:
            voice.done = True
        voice = Voice(key, note, name or sample.name, self._scale(sample), rate / self.rate, sample.loop_start,
                      sample.loop_length, pingpong=sample.loop_mode == "pingpong")
        voice.fade_total = max(1, self.rate * RELEASE_MS // 1000)
        self.voices = [item for item in self.voices if not item.done] + [voice]
        return voice

    def note_off(self, key: int) -> int:
        """Release the voices of a key: looped ones fade out, one-shots play on. Returns how many were looped."""
        count = 0
        for voice in self.voices:
            if voice.key == key and not voice.releasing and not voice.done and voice.looped:
                voice.releasing, voice.fade_left = True, voice.fade_total
                count += 1
        return count

    def clear(self):
        self.voices = []

    def snapshot(self) -> list[dict]:
        """What is sounding (for the GUI and tests): key, note, sample name, looped, releasing."""
        return [{"key": voice.key, "note": voice.note, "name": voice.name, "looped": voice.looped,
                 "releasing": voice.releasing} for voice in self.voices if not voice.done]

    def mix(self, pcm: bytes) -> bytes:
        """`pcm` (16-bit stereo) with every voice added, each channel saturated to the int16 range."""
        frames = len(pcm) // 4
        if not frames or not self.active:
            return pcm
        total: list[int] | None = None
        for voice in self.voices:
            if not voice.done:
                values = voice.render(frames)
                total = values if total is None else [a + b for a, b in zip(total, values)]
        self.voices = [voice for voice in self.voices if not voice.done]
        base = array("h")
        base.frombytes(pcm[:frames * 4])
        if sys.byteorder != "little":
            base.byteswap()
        stereo = [value for mono in total for value in (mono, mono)]
        mixed = array("h", [32767 if s > 32767 else -32768 if s < -32768 else s for s in map(int.__add__, base, stereo)])
        if sys.byteorder != "little":
            mixed.byteswap()
        return mixed.tobytes() + pcm[frames * 4:]


def render_wav(sample: Sample, note: str, fmt: str = "mod", seconds: float = 1.5) -> bytes:
    """A stereo 16-bit WAV of one note of `sample`, for the player that has no real-time engine."""
    mixer = JamMixer()
    if mixer.note_on(0, note, sample, fmt=fmt) is None:
        raise ValidationError(f"{note} cannot be played in a {fmt.upper()}.", "NOTE_UNKNOWN")
    frames = round(seconds * SAMPLE_RATE)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((2, 2, SAMPLE_RATE, frames, "NONE", "not compressed"))
        writer.writeframes(mixer.mix(bytes(frames * 4)))
    return buffer.getvalue()
