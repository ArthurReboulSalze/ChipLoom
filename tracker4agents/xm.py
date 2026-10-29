"""FastTracker 2 XM reader/writer and validator: the first XM profile (`fasttracker2-xm-v1`).

Scope: 2 to 32 channels, patterns of 1 to 256 rows, up to 128 instruments with exactly one sample
each (a multi-sample instrument is reduced to the sample its key map uses most, with an import
note; `read_samples` returns every sample of a file for bank extraction), 8-bit and 16-bit samples
(stored delta-encoded), forward and ping-pong loops, the volume column, per-sample panning,
relative note and finetune, linear and Amiga frequency tables, and volume/panning envelopes,
auto-vibrato and fadeout, which are stored and written back (not edited by the tools).

Model mapping. `module.samples[i]` is instrument i+1 and its only sample: `Sample.name` is the
instrument name; everything else the model does not carry lives in `module.metadata["xm"]`:
header values (`tracker_name`, `frequency_table`, `restart_position`, `default_speed`,
`default_bpm`, `inactive_orders`) and, per instrument, `instruments["<n>"]` (envelopes, vibrato,
fadeout, raw text bytes ...). A cell stores the XM note number 1..96 (C-0..B-7) or 97 (key off) in
`period`, the instrument in `sample`, the raw volume-column byte in `volume`, and the effect letter
as 0..35 in `command` (G..Z follow F). Unsupported input is refused with a specific code or
converted with an entry in `import_notes(module)`; nothing is dropped silently.
"""

from __future__ import annotations

from pathlib import Path
import struct

from .model import (
    EFFECT_DIGITS, XM_KEY_OFF, Cell, Module, Pattern, Sample, ValidationError, ascii_field, require_int,
    xm_profile,
)

MAGIC = b"Extended Module: "
VERSION = 0x0104
HEADER_SIZE = 276
TRACKER_NAME = "FastTracker v2.00   "  # lets libxmp and libopenmpt keep FastTracker II's flow behaviour
MAX_XM_BYTES = 24 * 1024 * 1024
MAX_SAMPLE_FRAMES = 1_048_576
MAX_INSTRUMENTS = 128
MAX_ORDERS = 256
MAX_PATTERNS_XM = 256
EXTENDED_SIZE = 263
SAMPLE_HEADER_SIZE = 40

# Effect letters FastTracker II defines (0-9, A-H, K, L, P, R, T, X); E-subcommands without a
# defined FastTracker II meaning (E0x filter, E8x, EFx) and every other letter are refused.
XM_COMMANDS = frozenset(EFFECT_DIGITS.index(letter) for letter in "0123456789ABCDEFGHKLPRTX")
XM_EXTENDED = frozenset({1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14})
_VOLUME_NAMES = {0x1: "set", 0x2: "set", 0x3: "set", 0x4: "set", 0x5: "set", 0x6: "slide down", 0x7: "slide up",
                 0x8: "fine down", 0x9: "fine up", 0xA: "vibrato speed", 0xB: "vibrato", 0xC: "panning",
                 0xD: "pan slide left", 0xE: "pan slide right", 0xF: "tone portamento"}


def blank(title: str = "", channels: int = 4, patterns: int = 1, rows: int = 64, speed: int = 6, bpm: int = 125,
          metadata: dict | None = None) -> Module:
    """A new empty XM: `patterns` empty patterns of `rows` rows played in order, one empty instrument, the
    header starting at `speed`/`bpm`, the linear frequency table (FastTracker II's default)."""
    require_int(channels, "channels", 2, 32, "CHANNELS")
    require_int(patterns, "patterns", 1, MAX_PATTERNS_XM, "PATTERNS")
    require_int(rows, "rows", 1, 256, "PATTERNS")
    require_int(speed, "speed", 1, 31, "TIMING")
    require_int(bpm, "bpm", 32, 255, "TIMING")
    ascii_field(title, 20, "XM title")
    block = {"tracker_name": TRACKER_NAME, "frequency_table": "linear", "restart_position": 0,
             "default_speed": speed, "default_bpm": bpm}
    return Module(title, [Sample("", (), 64)], [Pattern(f"Pattern {index:02X}", {}, rows) for index in range(patterns)],
                  list(range(patterns)), {**(metadata or {}), "xm": block}, channels, "xm")


def import_notes(module: Module) -> list[dict]:
    """Import report: [{code, kind, message, slots?, details?}], `kind` "preserved" or "converted"."""
    return list(xm_profile(module).get("import_notes", []))


# --- validation --------------------------------------------------------------------------------------

_XM_KEYS = {"tracker_name", "version", "frequency_table", "restart_position", "default_speed", "default_bpm",
            "inactive_orders", "title_bytes", "instruments", "import_notes"}
_INSTRUMENT_KEYS = {"name_bytes", "sample_name", "sample_name_bytes", "volume_envelope", "panning_envelope", "vibrato",
                    "fadeout", "fadeout_raw", "instrument_type", "header_size", "sample_header", "sample_header_size",
                    "ignored_loop", "sample_reserved", "sample_loop_type", "samples_dropped"}
_ENVELOPE_KEYS = {"points", "extra_points", "sustain", "loop_start", "loop_end", "type", "ticks_as_read"}
MAX_FADEOUT = 4095  # FastTracker II's own maximum; the file field is 16 bits wide
_VIBRATO_KEYS = {"type", "sweep", "depth", "rate"}


def _fail(message: str, code: str = "XM_METADATA") -> None:
    raise ValidationError(message, code)


def _hex(value: object, size: int, label: str) -> None:
    try:
        ok = isinstance(value, str) and len(bytes.fromhex(value)) == size and value == value.lower()
    except ValueError:
        ok = False
    if not ok:
        _fail(f"{label}: expected {size} bytes as lowercase hexadecimal.")


def _validate_envelope(envelope: object, label: str) -> None:
    if not isinstance(envelope, dict) or set(envelope) - _ENVELOPE_KEYS:
        _fail(f"{label}: expected an object with keys among {sorted(_ENVELOPE_KEYS)}.")
    points = envelope.get("points", [])
    if not isinstance(points, list) or len(points) > 12:
        _fail(f"{label}.points: expected at most 12 [tick, value] pairs.")
    as_read = envelope.get("ticks_as_read", False)
    if as_read is not False and as_read is not True:
        _fail(f"{label}.ticks_as_read: expected true (set by the importer when the file's ticks are out of order).")
    last = -1
    for point in points:
        if not (isinstance(point, list) and len(point) == 2):
            _fail(f"{label}.points: expected [tick, value] pairs.")
        require_int(point[0], f"{label}.points tick", 0, 65535, "XM_METADATA")
        require_int(point[1], f"{label}.points value", 0, 64, "XM_METADATA")
        if point[0] <= last and not as_read:
            _fail(f"{label}.points: ticks must increase strictly.")
        last = point[0]
    extra = envelope.get("extra_points", [])
    if not isinstance(extra, list) or len(points) + len(extra) > 12 or any(
            not (isinstance(item, list) and len(item) == 2 and all(type(v) is int and 0 <= v <= 65535 for v in item))
            for item in extra):
        _fail(f"{label}.extra_points: expected the unused [tick, value] slots, 12 points in all.")
    for key in ("sustain", "loop_start", "loop_end"):
        require_int(envelope.get(key, 0), f"{label}.{key}", 0, 255, "XM_METADATA")
    require_int(envelope.get("type", 0), f"{label}.type", 0, 255, "XM_METADATA")
    if envelope.get("type", 0) & 7 and not points:
        _fail(f"{label}: an enabled envelope needs points.")
    for key in ("sustain", "loop_start", "loop_end"):
        if envelope.get(key, 0) >= max(len(points), 1) and envelope.get("type", 0) & 7:
            _fail(f"{label}.{key}: point index outside the envelope.")


def validate_xm_metadata(module: Module) -> None:
    block = module.metadata.get("xm") if isinstance(module.metadata, dict) else None
    if block is None:
        return
    if not isinstance(block, dict) or set(block) - _XM_KEYS:
        _fail(f"metadata.xm: expected an object with keys among {sorted(_XM_KEYS)}.")
    if "tracker_name" in block:
        ascii_field(block["tracker_name"], 20, "metadata.xm.tracker_name")
    if "title_bytes" in block:
        _hex(block["title_bytes"], 20, "metadata.xm.title_bytes")
    if block.get("version", 0x0104) != VERSION:
        _fail("metadata.xm.version: only version 0x0104 is supported.", "XM_VERSION")
    if block.get("frequency_table", "linear") not in ("linear", "amiga"):
        _fail("metadata.xm.frequency_table: expected 'linear' or 'amiga'.")
    require_int(block.get("restart_position", 0), "metadata.xm.restart_position", 0, 255, "XM_METADATA")
    require_int(block.get("default_speed", 6), "metadata.xm.default_speed", 1, 31, "XM_METADATA")
    require_int(block.get("default_bpm", 125), "metadata.xm.default_bpm", 32, 255, "XM_METADATA")
    inactive = block.get("inactive_orders", {})
    if not isinstance(inactive, dict):
        _fail("metadata.xm.inactive_orders: expected an object {slot: pattern}.")
    for key, value in inactive.items():
        if not (isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key and int(key) < MAX_ORDERS):
            _fail(f"metadata.xm.inactive_orders: invalid slot {key!r} (0 to 255).")
        require_int(value, f"metadata.xm.inactive_orders[{key}]", 0, 255, "XM_METADATA")
    instruments = block.get("instruments", {})
    if not isinstance(instruments, dict):
        _fail("metadata.xm.instruments: expected an object {instrument: details}.")
    for key, item in instruments.items():
        label = f"metadata.xm.instruments[{key}]"
        if not (isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key
                and 1 <= int(key) <= MAX_INSTRUMENTS):
            _fail(f"metadata.xm.instruments: invalid instrument {key!r} (1 to 128).")
        if not isinstance(item, dict) or set(item) - _INSTRUMENT_KEYS:
            _fail(f"{label}: allowed keys are {sorted(_INSTRUMENT_KEYS)}.")
        for name in ("name_bytes", "sample_name_bytes"):
            if name in item:
                _hex(item[name], 22, f"{label}.{name}")
        if "sample_name" in item:
            ascii_field(item["sample_name"], 22, f"{label}.sample_name")
        for name in ("volume_envelope", "panning_envelope"):
            if name in item:
                _validate_envelope(item[name], f"{label}.{name}")
        if "vibrato" in item:
            vibrato = item["vibrato"]
            if not isinstance(vibrato, dict) or set(vibrato) - _VIBRATO_KEYS:
                _fail(f"{label}.vibrato: expected an object with keys among {sorted(_VIBRATO_KEYS)}.")
            for name, high in (("type", 3), ("sweep", 255), ("depth", 15), ("rate", 63)):
                require_int(vibrato.get(name, 0), f"{label}.vibrato.{name}", 0, high, "XM_METADATA")
        require_int(item.get("fadeout", 0), f"{label}.fadeout", 0, MAX_FADEOUT, "XM_METADATA")
        require_int(item.get("fadeout_raw", MAX_FADEOUT + 1), f"{label}.fadeout_raw", MAX_FADEOUT + 1, 65535, "XM_METADATA")
        require_int(item.get("instrument_type", 0), f"{label}.instrument_type", 0, 255, "XM_METADATA")
        require_int(item.get("sample_reserved", 0), f"{label}.sample_reserved", 0, 255, "XM_METADATA")
        require_int(item.get("header_size", EXTENDED_SIZE), f"{label}.header_size", 29, 65535, "XM_METADATA")
        require_int(item.get("sample_header_size", SAMPLE_HEADER_SIZE), f"{label}.sample_header_size", 0, 2**32 - 1,
                    "XM_METADATA")
        require_int(item.get("sample_loop_type", 3), f"{label}.sample_loop_type", 3, 3, "XM_METADATA")
        require_int(item.get("samples_dropped", 1), f"{label}.samples_dropped", 1, 65535, "XM_METADATA")
        if "ignored_loop" in item:
            loop = item["ignored_loop"]
            if not (isinstance(loop, list) and len(loop) == 2 and all(type(v) is int and 0 <= v < 2**32 for v in loop)):
                _fail(f"{label}.ignored_loop: expected [start, length] in bytes.")
    notes = block.get("import_notes", [])
    if not isinstance(notes, list):
        _fail("metadata.xm.import_notes: expected a list.")
    for note in notes:
        if (not isinstance(note, dict) or not {"code", "kind", "message"} <= set(note)
                or note["kind"] not in ("preserved", "converted")):
            _fail("metadata.xm.import_notes: expected notes with code, kind and message.")


def validate_xm_sample(sample: Sample, index: int) -> None:
    label = f"Instrument {index}"
    ascii_field(sample.name, 22, label)
    if sample.bits not in (8, 16):
        raise ValidationError(f"{label}: bits must be 8 or 16.", "XM_SAMPLE")
    limit = 1 << (sample.bits - 1)
    if sample.loop_mode not in ("forward", "pingpong"):
        raise ValidationError(f"{label}: loop_mode must be 'forward' or 'pingpong'.", "XM_SAMPLE")
    require_int(sample.volume, f"{label} volume", 0, 64, "XM_SAMPLE")
    require_int(sample.finetune, f"{label} finetune", -128, 127, "XM_SAMPLE")
    require_int(sample.panning, f"{label} panning", 0, 255, "XM_SAMPLE")
    require_int(sample.relative_note, f"{label} relative_note", -96, 95, "XM_SAMPLE")
    length = len(sample.pcm)
    if length > MAX_SAMPLE_FRAMES:
        raise ValidationError(f"{label}: at most {MAX_SAMPLE_FRAMES} sample frames.", "SAMPLE_LENGTH")
    if any(type(value) is not int or not -limit <= value < limit for value in sample.pcm):
        raise ValidationError(f"{label}: signed {sample.bits}-bit PCM values expected ({-limit} to {limit - 1}).",
                              "SAMPLE_PCM")
    require_int(sample.loop_start, f"{label} loop_start", 0, length, "SAMPLE_LOOP")
    require_int(sample.loop_length, f"{label} loop_length", 0, length, "SAMPLE_LOOP")
    if sample.loop_length and sample.loop_start + sample.loop_length > length:
        raise ValidationError(f"{label}: the loop runs past the end of the sample.", "SAMPLE_LOOP")
    if not sample.loop_length and (sample.loop_start or sample.loop_mode != "forward"):
        raise ValidationError(f"{label}: without a loop, loop_start must be 0 and loop_mode 'forward'.", "SAMPLE_LOOP")


def validate_xm_cell(value: Cell, row: int, channel: int, pattern_index: int, instrument_count: int,
                     order_count: int, channels: int, rows: int) -> None:
    where = f"Pattern {pattern_index}, row {row}, channel {channel}"
    require_int(row, where, 0, rows - 1)
    require_int(channel, where, 0, channels - 1)
    require_int(value.period, f"{where} note", 0, XM_KEY_OFF, "NOTE_RANGE")
    require_int(value.sample, f"{where} instrument", 0, instrument_count, "SAMPLE_REF")
    require_int(value.command, f"{where} effect", 0, 35, "EFFECT_UNSUPPORTED")
    require_int(value.param, f"{where} parameter", 0, 255)
    require_int(value.volume, f"{where} volume column", 0, 255, "XM_VOLUME_COLUMN")
    if value.volume and (value.volume < 0x10 or 0x50 < value.volume < 0x60):
        raise ValidationError(f"{where}: volume-column byte {value.volume:02X} is undefined in FastTracker II "
                              "(use 10-50 for a volume, 60-FF for the slides, vibrato, panning and portamento).",
                              "XM_VOLUME_COLUMN")
    if value.command not in XM_COMMANDS:
        raise ValidationError(f"{where}: effect {value.effect} is not a FastTracker II effect "
                              "(0-9, A-H, K, L, P, R, T, X).", "EFFECT_UNSUPPORTED")
    if value.command == 14 and value.param >> 4 not in XM_EXTENDED:
        raise ValidationError(f"{where}: extended effect {value.effect} is not supported "
                              "(E0x, E8x and EFx are undefined in FastTracker II).", "EFFECT_UNSUPPORTED")
    if value.command == 12 and value.param > 64:
        raise ValidationError(f"{where}: Cxx volume above 40 hexadecimal.", "EFFECT_PARAM")
    if value.command == 16 and value.param > 64:
        raise ValidationError(f"{where}: Gxx global volume above 40 hexadecimal.", "EFFECT_PARAM")
    if value.command == 11 and value.param >= order_count:
        raise ValidationError(f"{where}: Bxx points outside the order list.", "FLOW")
    if value.command == 13 and ((value.param >> 4) > 9 or (value.param & 15) > 9):
        raise ValidationError(f"{where}: Dxx expects a decimal (BCD) row, 00 to 99.", "FLOW")
    if value.command == 15 and value.param == 0:
        raise ValidationError(f"{where}: F00 stops the song in some players and is excluded.", "TIMING")


def validate_xm(module: Module) -> None:
    if module.format != "xm":
        _fail(f"Module format {module.format!r} is not xm.", "FORMAT")
    require_int(module.channels, "channels", 2, 32, "CHANNELS")
    ascii_field(module.title, 20, "XM title")
    if not 1 <= len(module.samples) <= MAX_INSTRUMENTS:
        raise ValidationError(f"An XM holds 1 to {MAX_INSTRUMENTS} instruments.", "SAMPLE_SLOT")
    if not 1 <= len(module.patterns) <= MAX_PATTERNS_XM:
        raise ValidationError(f"An XM holds 1 to {MAX_PATTERNS_XM} patterns.", "PATTERNS")
    if not 1 <= len(module.orders) <= MAX_ORDERS:
        raise ValidationError(f"An XM order list holds 1 to {MAX_ORDERS} entries.", "ORDERS")
    for index, value in enumerate(module.orders):
        require_int(value, f"orders[{index}]", 0, len(module.patterns) - 1, "ORDERS")
    validate_xm_metadata(module)
    inactive = xm_profile(module).get("inactive_orders", {})
    if any(slot_value >= len(module.patterns) for slot_value in inactive.values()):
        raise ValidationError("An inactive order entry names a pattern that does not exist.", "ORDERS")
    for slot in xm_profile(module).get("instruments", {}):
        if int(slot) > len(module.samples):
            _fail(f"metadata.xm.instruments[{slot}]: no such instrument.")
    for index, sample in enumerate(module.samples, 1):
        validate_xm_sample(sample, index)
    for index, pattern in enumerate(module.patterns):
        require_int(pattern.rows, f"Pattern {index} rows", 1, 256, "PATTERNS")
        for (row, channel), value in pattern.cells.items():
            validate_xm_cell(value, row, channel, index, len(module.samples), len(module.orders),
                             module.channels, pattern.rows)


# --- writing -----------------------------------------------------------------------------------------

def _text(text: str, stored_hex: str | None, size: int, label: str) -> bytes:
    from .mod import sanitize_text
    if stored_hex is not None:
        raw = bytes.fromhex(stored_hex)
        if sanitize_text(raw) == text:
            return raw
    return ascii_field(text, size, label)


def _delta(values: tuple[int, ...], bits: int) -> bytes:
    mask = (1 << bits) - 1
    previous, out = 0, []
    for value in values:
        out.append((value - previous) & mask)
        previous = value
    if bits == 8:
        return bytes(out)
    return struct.pack(f"<{len(out)}H", *out)


def _undelta(raw: bytes, bits: int) -> tuple[int, ...]:
    if bits == 8:
        values = list(raw)
        sign = 128
    else:
        values = list(struct.unpack(f"<{len(raw) // 2}H", raw))
        sign = 32768
    previous, mask, out = 0, (1 << bits) - 1, []
    for value in values:
        previous = (previous + value) & mask
        out.append(previous - (1 << bits) if previous >= sign else previous)
    return tuple(out)


def _pack_cell(value: Cell) -> bytes:
    mask, body = 0, bytearray()
    for bit, field_value in ((1, value.period), (2, value.sample), (4, value.volume), (8, value.command), (16, value.param)):
        if field_value:
            mask |= bit
            body.append(field_value)
    return bytes((0x80 | mask,)) + bytes(body)


def _envelope_bytes(envelope: dict | None) -> tuple[bytes, int, tuple[int, int, int, int]]:
    envelope = envelope or {}
    points = list(envelope.get("points", [])) + list(envelope.get("extra_points", []))
    points += [[0, 0]] * (12 - len(points))
    data = b"".join(struct.pack("<HH", x, y) for x, y in points)
    return data, len(envelope.get("points", [])), (envelope.get("sustain", 0), envelope.get("loop_start", 0),
                                                  envelope.get("loop_end", 0), envelope.get("type", 0))


def _fadeout_bytes(extra: dict) -> int:
    """The fadeout written: the file's own value above 4095 while the clamped value was not edited."""
    value, raw = extra.get("fadeout", 0), extra.get("fadeout_raw")
    return raw if raw is not None and value == min(raw, MAX_FADEOUT) else value


def encode(module: Module) -> bytes:
    validate_xm(module)
    return _encode(module, xm_profile(module))


def encode_for_replay(module: Module) -> bytes:
    """The bytes handed to an in-process replay engine: identical to the file for an XM."""
    return encode(module)


def _encode(module: Module, profile: dict) -> bytes:
    inactive = profile.get("inactive_orders", {})
    table = list(module.orders) + [inactive.get(str(slot), 0) for slot in range(len(module.orders), MAX_ORDERS)]
    header = bytearray(MAGIC)
    header += _text(module.title, profile.get("title_bytes"), 20, "Title")
    header += b"\x1a" + ascii_field(profile.get("tracker_name", TRACKER_NAME), 20, "Tracker").replace(b"\x00", b" ")
    header += struct.pack(
        "<HIHHHHHHH", VERSION, HEADER_SIZE, len(module.orders), profile.get("restart_position", 0), module.channels,
        len(module.patterns), len(module.samples), 1 if profile.get("frequency_table", "linear") == "linear" else 0,
        profile.get("default_speed", 6))
    header += struct.pack("<H", profile.get("default_bpm", 125)) + bytes(table)
    output = bytearray(header)
    for pattern in module.patterns:
        data = bytearray()
        for row in range(pattern.rows):
            for channel in range(module.channels):
                data += _pack_cell(pattern.get(row, channel))
        output += struct.pack("<IBHH", 9, 0, pattern.rows, len(data)) + data
    instruments = profile.get("instruments", {})
    for slot, sample in enumerate(module.samples, 1):
        extra = instruments.get(str(slot), {})
        has_sample = bool(sample.pcm) or extra.get("sample_header", False)
        name = _text(sample.name, extra.get("name_bytes"), 22, "Instrument name")
        # The header is 29 bytes for an empty instrument and 263 otherwise, unless the import kept another
        # size: the extended layout is then cut or zero-padded to it, as the file laid it out.
        size = extra.get("header_size", EXTENDED_SIZE if has_sample else 29)
        head = bytearray(struct.pack("<I", size) + name + bytes((extra.get("instrument_type", 0),)))
        head += struct.pack("<H", 1 if has_sample else 0)
        if size > 29:
            volume_points, volume_count, volume_flags = _envelope_bytes(extra.get("volume_envelope"))
            panning_points, panning_count, panning_flags = _envelope_bytes(extra.get("panning_envelope"))
            vibrato = extra.get("vibrato", {})
            sample_header_size = SAMPLE_HEADER_SIZE if has_sample else extra.get("sample_header_size", SAMPLE_HEADER_SIZE)
            head += struct.pack("<I", sample_header_size) + bytes(96)
            head += volume_points + panning_points
            head += bytes((volume_count, panning_count, volume_flags[0], volume_flags[1], volume_flags[2],
                           panning_flags[0], panning_flags[1], panning_flags[2], volume_flags[3], panning_flags[3],
                           vibrato.get("type", 0), vibrato.get("sweep", 0), vibrato.get("depth", 0),
                           vibrato.get("rate", 0)))
            head += struct.pack("<H", _fadeout_bytes(extra)) + bytes(22)
            head = head[:size].ljust(size, b"\x00")
        output += head
        if not has_sample:
            continue
        step = sample.bits // 8
        if sample.loop_length:
            loop_start, loop_length = sample.loop_start * step, sample.loop_length * step
            kind = 2 if sample.loop_mode == "pingpong" else 1
            if kind == 2 and extra.get("sample_loop_type") == 3:
                kind = 3  # both loop bits, as the source file had them (players read it as ping-pong)
        else:
            loop_start, loop_length = extra.get("ignored_loop", (0, 0))
            kind = 0
        output += struct.pack("<IIIBbBBbB", len(sample.pcm) * step, loop_start, loop_length, sample.volume,
                              sample.finetune, kind | (16 if sample.bits == 16 else 0), sample.panning,
                              sample.relative_note, extra.get("sample_reserved", 0))
        sample_name = extra.get("sample_name", sample.name)
        output += _text(sample_name, extra.get("sample_name_bytes"), 22, "Sample name")
        output += _delta(sample.pcm, sample.bits)
    return bytes(output)


# --- reading -----------------------------------------------------------------------------------------

def _note(notes: list, code: str, kind: str, message: str, slots=None, details=None) -> None:
    note = {"code": code, "kind": kind, "message": message}
    if slots:
        note["slots"] = list(slots)
    if details:
        note["details"] = details
    notes.append(note)


def _envelope(raw: bytes, count: int, sustain: int, loop_start: int, loop_end: int, kind: int) -> dict | None:
    pairs = [list(struct.unpack_from("<HH", raw, offset)) for offset in range(0, 48, 4)]
    if count > 12:
        raise ValidationError("An envelope holds at most 12 points.", "XM_FORMAT")
    envelope: dict = {}
    if count:
        envelope["points"] = pairs[:count]
        if any(later[0] <= earlier[0] for earlier, later in zip(pairs[:count], pairs[1:count])):
            envelope["ticks_as_read"] = True
    if any(pair != [0, 0] for pair in pairs[count:]):
        envelope["extra_points"] = pairs[count:]
    for key, value in (("sustain", sustain), ("loop_start", loop_start), ("loop_end", loop_end), ("type", kind)):
        if value:
            envelope[key] = value
    return envelope or None


def _header(payload: bytes) -> tuple:
    """The validated file header: (orders, inactive, channels, pattern_count, instrument_count, flags, speed, bpm,
    restart, cursor) with the cursor on the first pattern."""
    if len(payload) > MAX_XM_BYTES or len(payload) < 80 + MAX_ORDERS:
        raise ValidationError("Invalid XM size.", "XM_FORMAT")
    if payload[:17] != MAGIC or payload[37] != 0x1A:
        raise ValidationError("Not an Extended Module (missing the 'Extended Module: ' header).", "XM_FORMAT")
    version, header_size, length, restart, channels, pattern_count, instrument_count, flags, speed, bpm = \
        struct.unpack_from("<HIHHHHHHHH", payload, 58)
    if version != VERSION:
        raise ValidationError(f"XM version 0x{version:04X} is not supported (only 0x0104).", "XM_VERSION")
    if header_size != HEADER_SIZE:
        raise ValidationError(f"XM header size {header_size} is not supported (expected {HEADER_SIZE}).", "XM_FORMAT")
    if not 2 <= channels <= 32 or not 1 <= length <= MAX_ORDERS or pattern_count > MAX_PATTERNS_XM \
            or instrument_count > MAX_INSTRUMENTS:
        raise ValidationError("The XM header has an invalid channel, order, pattern or instrument count.", "XM_FORMAT")
    if flags & ~1:
        raise ValidationError("Unknown XM header flags are set.", "XM_FORMAT")
    if not 1 <= speed <= 31 or not 32 <= bpm <= 255:
        raise ValidationError("The default speed must be 1-31 and the default tempo 32-255.", "XM_FORMAT")
    table = payload[80:80 + MAX_ORDERS]
    orders = list(table[:length])
    inactive = {str(slot): value for slot, value in enumerate(table) if slot >= length and value}
    if pattern_count < 1:
        raise ValidationError("An XM without patterns is not supported.", "XM_FORMAT")
    if max(max(orders), *inactive.values(), 0) >= pattern_count:
        raise ValidationError("The order list names a pattern the file does not contain.", "ORDERS")
    return orders, inactive, channels, pattern_count, instrument_count, flags, speed, bpm, restart, 60 + header_size


def _pattern_header(payload: bytes, cursor: int, index: int) -> tuple[int, int]:
    """(rows, data size) of the pattern header at `cursor`."""
    if cursor + 9 > len(payload):
        raise ValidationError("The XM ends inside a pattern header.", "XM_FORMAT")
    head, packing, rows, size = struct.unpack_from("<IBHH", payload, cursor)
    if head != 9 or packing != 0 or not 1 <= rows <= 256:
        raise ValidationError(f"Pattern {index}: unsupported header (length {head}, packing {packing}, "
                              f"{rows} rows).", "XM_FORMAT")
    if cursor + 9 + size > len(payload):
        raise ValidationError(f"Pattern {index} runs past the end of the file.", "XM_FORMAT")
    return rows, size


def _unsupported_effect(command: int, param: int) -> bool:
    """Effects the profile refuses in a cell: undefined letters, E0x/E8x/EFx, and F00 (ignored by
    FastTracker II, a song stop in other players)."""
    return (command not in XM_COMMANDS or (command == 14 and param >> 4 not in XM_EXTENDED)
            or (command == 15 and param == 0))


def _read_instruments(payload: bytes, cursor: int, count: int) -> tuple[list[dict], int]:
    """Every instrument with every sample, as the file stores them (no profile reduction).

    The instrument header size field says where the sample headers start; its fields are read from a
    263-byte view (zero-padded when the header is shorter, cut when longer). A sample header size field
    above 40 skips the extra bytes; below 40 the 40 known bytes are read anyway, as OpenMPT does."""
    items = []
    for slot in range(1, count + 1):
        if cursor + 29 > len(payload):
            raise ValidationError("The XM ends inside an instrument header.", "XM_FORMAT")
        (size,) = struct.unpack_from("<I", payload, cursor)
        if size < 29 or cursor + size > len(payload):
            raise ValidationError(f"Instrument {slot}: header size {size} is below 29 bytes or runs past the end "
                                  "of the file.", "XM_INSTRUMENT_HEADER")
        head = payload[cursor:cursor + size]
        view = head[:EXTENDED_SIZE].ljust(EXTENDED_SIZE, b"\x00")
        (sample_count,) = struct.unpack_from("<H", view, 27)
        (sample_header_size,) = struct.unpack_from("<I", view, 29)
        volume_count, panning_count = view[225], view[226]
        (vs, vls, vle, ps, pls, ple, vt, pt, vib_type, vib_sweep, vib_depth, vib_rate) = view[227:239]
        (fadeout,) = struct.unpack_from("<H", view, 239)
        item = {
            "slot": slot, "header_size": size, "name_raw": view[4:26], "instrument_type": view[26],
            "sample_count": sample_count, "sample_header_size": sample_header_size, "keymap": view[33:129],
            "volume_envelope": _envelope(view[129:177], volume_count, vs, vls, vle, vt),
            "panning_envelope": _envelope(view[177:225], panning_count, ps, pls, ple, pt),
            "vibrato": {key: value for key, value in (("type", vib_type), ("sweep", vib_sweep), ("depth", vib_depth),
                                                      ("rate", vib_rate)) if value},
            "fadeout": fadeout, "reserved_nonzero": any(view[241:263]) or any(head[EXTENDED_SIZE:]), "samples": [],
        }
        cursor += size
        stride = max(sample_header_size, SAMPLE_HEADER_SIZE)
        headers = []
        for index in range(sample_count):
            if cursor + SAMPLE_HEADER_SIZE > len(payload):
                raise ValidationError("The XM ends inside a sample header.", "XM_FORMAT")
            headers.append((struct.unpack_from("<IIIBbBBbB", payload, cursor), payload[cursor + 18:cursor + 40]))
            cursor += stride
        for index, (fields, name_raw) in enumerate(headers):
            length_bytes, loop_start, loop_length, volume, finetune, kind, panning, relative, reserved = fields
            if kind & ~0x13:
                raise ValidationError(f"Instrument {slot}: sample type 0x{kind:02X} is not supported (stereo or "
                                      "unknown flags).", "XM_SAMPLE_TYPE")
            if reserved == 0xAD:
                raise ValidationError(f"Instrument {slot}: ADPCM-compressed samples are not supported.", "XM_SAMPLE_TYPE")
            bits = 16 if kind & 16 else 8
            step = bits // 8
            if length_bytes % step or loop_start % step or loop_length % step:
                raise ValidationError(f"Instrument {slot}: a 16-bit sample or loop has an odd byte count.", "XM_FORMAT")
            if cursor + length_bytes > len(payload):
                raise ValidationError(f"Instrument {slot}: sample data runs past the end of the file.", "XM_FORMAT")
            if length_bytes // step > MAX_SAMPLE_FRAMES:
                raise ValidationError(f"Instrument {slot}: sample longer than {MAX_SAMPLE_FRAMES} frames.", "SAMPLE_LENGTH")
            if volume > 64:
                raise ValidationError(f"Instrument {slot}: sample volume {volume} is above 64.", "XM_SAMPLE")
            item["samples"].append({
                "index": index, "name_raw": name_raw, "pcm": _undelta(payload[cursor:cursor + length_bytes], bits),
                "bits": bits, "loop_start": loop_start, "loop_length": loop_length, "kind": kind, "volume": volume,
                "finetune": finetune, "panning": panning, "relative_note": relative, "reserved": reserved,
            })
            cursor += length_bytes
        items.append(item)
    return items, cursor


def _keymap_counts(keymap: bytes, sample_count: int) -> list[int]:
    """How many of the 96 key map entries name each existing sample."""
    counts = [0] * sample_count
    for entry in keymap:
        if entry < sample_count:
            counts[entry] += 1
    return counts


def read_samples(payload: bytes) -> list[dict]:
    """Every sample of every instrument, without the one-sample reduction of `decode` (for bank extraction).

    Each item: `instrument` (1-based), `index` (within the instrument), `name`, `pcm` (signed ints), `bits`,
    `loop_start`, `loop_length` (frames), `loop_mode` (none|forward|pingpong), `volume`, `finetune`,
    `panning`, `relative_note`, `keymap_notes` (how many of the 96 key map entries name it), and the
    instrument's `volume_envelope`, `panning_envelope`, `vibrato`, `fadeout` as the importer stores them."""
    from .mod import sanitize_text
    _, _, channels, pattern_count, instrument_count, *_rest, cursor = _header(payload)
    for index in range(pattern_count):
        cursor += 9 + _pattern_header(payload, cursor, index)[1]
    instruments, _ = _read_instruments(payload, cursor, instrument_count)
    out = []
    for item in instruments:
        counts = _keymap_counts(item["keymap"], item["sample_count"])
        for sample in item["samples"]:
            step = sample["bits"] // 8
            start, span = sample["loop_start"] // step, sample["loop_length"] // step
            mode = "none" if sample["kind"] & 3 == 0 or span == 0 else ("pingpong" if sample["kind"] & 2 else "forward")
            out.append({
                "instrument": item["slot"], "index": sample["index"], "name": sanitize_text(sample["name_raw"]),
                "pcm": sample["pcm"], "bits": sample["bits"], "loop_start": start, "loop_length": span,
                "loop_mode": mode, "volume": sample["volume"], "finetune": sample["finetune"],
                "panning": sample["panning"], "relative_note": sample["relative_note"],
                "keymap_notes": counts[sample["index"]], "volume_envelope": item["volume_envelope"],
                "panning_envelope": item["panning_envelope"], "vibrato": item["vibrato"],
                "fadeout": min(item["fadeout"], MAX_FADEOUT),
            })
    return out


def decode(payload: bytes) -> Module:
    orders, inactive, channels, pattern_count, instrument_count, flags, speed, bpm, restart, cursor = _header(payload)
    notes: list[dict] = []
    from .mod import sanitize_text
    metadata: dict = {"tracker_name": sanitize_text(payload[38:58]).ljust(20)[:20]}
    metadata["frequency_table"] = "linear" if flags & 1 else "amiga"
    metadata["restart_position"] = restart
    metadata["default_speed"], metadata["default_bpm"] = speed, bpm
    if inactive:
        metadata["inactive_orders"] = inactive
        _note(notes, "INACTIVE_ORDERS_KEPT", "preserved", f"{len(inactive)} nonzero order entries beyond the song "
              "length are kept and written back.")
    title_raw = payload[17:37]
    title = sanitize_text(title_raw)
    if title_raw != title.encode("ascii").ljust(20, b"\x00"):
        metadata["title_bytes"] = title_raw.hex()
        _note(notes, "TEXT_KEPT_RAW", "preserved", "The title has bytes outside printable ASCII; shown with '?' and "
              "written back unchanged until renamed.")

    patterns = []
    ignored_effects: dict[str, list[dict]] = {}
    for index in range(pattern_count):
        rows, size = _pattern_header(payload, cursor, index)
        start = cursor + 9
        pattern = Pattern(f"Pattern {index:02X}", {}, rows)
        position, end = start, start + size
        for row in range(rows):
            for channel in range(channels):
                if position >= end:  # a short pattern: the remaining cells are empty
                    break
                first = payload[position]
                position += 1
                values = [0, 0, 0, 0, 0]
                if first & 0x80:
                    for bit in range(5):
                        if first & (1 << bit):
                            if position >= end:
                                raise ValidationError(f"Pattern {index} is truncated.", "XM_FORMAT")
                            values[bit] = payload[position]
                            position += 1
                else:
                    values[0] = first
                    if position + 4 > end:
                        raise ValidationError(f"Pattern {index} is truncated.", "XM_FORMAT")
                    values[1:] = payload[position:position + 4]
                    position += 4
                value = Cell(values[0], values[1], values[3], values[4], values[2])
                if (value.command or value.param) and _unsupported_effect(value.command, value.param):
                    text = EFFECT_DIGITS[value.command] + f"{value.param:02X}" if value.command < 36 else f"?{value.param:02X}"
                    ignored_effects.setdefault(text, []).append({"pattern": index, "row": row, "channel": channel})
                    value = Cell(value.period, value.sample, 0, 0, value.volume)
                pattern.put(row, channel, value)
        if position != end:
            raise ValidationError(f"Pattern {index} has {end - position} unused data bytes.", "XM_FORMAT")
        patterns.append(pattern)
        cursor = end
    for text, cells in ignored_effects.items():
        first = cells[0]
        _note(notes, "EFFECT_IGNORED", "converted",
              f"Effect {text} is undefined or ignored in FastTracker II (F00 stops the song in some players) and was "
              f"cleared in {len(cells)} cell(s), the first at pattern {first['pattern']}, row {first['row']}, "
              f"channel {first['channel']}; the export differs from the source.",
              details={"effect": text, "cells": cells})

    instruments, cursor = _read_instruments(payload, cursor, instrument_count)
    samples: list[Sample] = []
    instruments_meta: dict[str, dict] = {}
    converted_loops, ignored_loops, odd_headers, fadeouts, loop_types = [], [], [], [], []
    for item in instruments:
        slot, count = item["slot"], item["sample_count"]
        name = sanitize_text(item["name_raw"])
        extra: dict = {}
        if item["name_raw"] != name.encode("ascii").ljust(22, b"\x00"):
            extra["name_bytes"] = item["name_raw"].hex()
        if item["instrument_type"]:
            extra["instrument_type"] = item["instrument_type"]
        if item["header_size"] != (EXTENDED_SIZE if count else 29):
            extra["header_size"] = item["header_size"]
            odd_headers.append(slot)
        if item["sample_header_size"] != SAMPLE_HEADER_SIZE and (count or item["header_size"] > 29):
            if count:
                _note(notes, "XM_SAMPLE_HEADER_RESIZED", "converted",
                      f"Instrument {slot}: its sample headers are declared {item['sample_header_size']} bytes long "
                      f"(read as {max(item['sample_header_size'], SAMPLE_HEADER_SIZE)}); they are written back as "
                      "40-byte headers, so the export differs from the source.", [slot])
            else:
                extra["sample_header_size"] = item["sample_header_size"]
                if slot not in odd_headers:
                    odd_headers.append(slot)
        if item["reserved_nonzero"]:
            _note(notes, "INSTRUMENT_RESERVED_DROPPED", "converted",
                  "The reserved bytes of an instrument header are not kept.", [slot])
        for key in ("volume_envelope", "panning_envelope"):
            if item[key]:
                extra[key] = item[key]
                if item[key].get("ticks_as_read"):
                    _note(notes, "XM_ENVELOPE_POINTS_KEPT", "preserved",
                          f"Instrument {slot}: the {key.replace('_', ' ')} has ticks that do not increase strictly; "
                          "the points are kept as read and written back (players reorder or clamp them).", [slot],
                          {"instrument": slot, "envelope": key})
        if item["vibrato"]:
            extra["vibrato"] = item["vibrato"]
        if item["fadeout"] > MAX_FADEOUT:
            extra["fadeout"], extra["fadeout_raw"] = MAX_FADEOUT, item["fadeout"]
            fadeouts.append(slot)
        elif item["fadeout"]:
            extra["fadeout"] = item["fadeout"]
        sample = Sample(name, (), 64, 0, 0, 0)
        counts = _keymap_counts(item["keymap"], count)
        chosen = max(range(count), key=counts.__getitem__) if count else 0
        if count > 1:
            extra["samples_dropped"] = count - 1
            _note(notes, "XM_MULTISAMPLE_REDUCED", "converted",
                  f"Instrument {slot} holds {count} samples; this profile keeps one per instrument, so sample "
                  f"{chosen} (the one its key map uses for {counts[chosen]} of 96 notes) was kept and {count - 1} "
                  "dropped. The export differs from the source; `read_samples` returns them all.", [slot],
                  {"instrument": slot, "samples": count, "kept": chosen, "keymap_notes": counts[chosen]})
        elif any(item["keymap"]):
            _note(notes, "XM_KEYMAP_DROPPED", "converted",
                  f"Instrument {slot}: its key map names samples the instrument does not hold; the map is not kept "
                  "(every note plays the instrument's sample). The export differs from the source.", [slot])
        if count:
            raw = item["samples"][chosen]
            bits, kind, pcm = raw["bits"], raw["kind"], raw["pcm"]
            step = bits // 8
            frames = len(pcm)
            loop_start, loop_length = raw["loop_start"], raw["loop_length"]
            loop_mode, start, span = "forward", loop_start // step, loop_length // step
            if kind & 3 == 0:
                if loop_start or loop_length:
                    extra["ignored_loop"] = [loop_start, loop_length]
                    ignored_loops.append(slot)
                start = span = 0
            else:
                loop_mode = "pingpong" if kind & 2 else "forward"
                if kind & 3 == 3:
                    extra["sample_loop_type"] = 3
                    loop_types.append(slot)
                if span == 0:
                    start, loop_mode = 0, "forward"  # a loop of length 0 is no loop for any player
                    extra["ignored_loop"] = [loop_start, 0]
                    ignored_loops.append(slot)
                elif start + span > frames:
                    converted_loops.append((slot, loop_start // step, loop_length // step, frames))
                    if start >= frames:
                        start = span = 0
                        loop_mode = "forward"
                    else:
                        span = frames - start
            sample_name = sanitize_text(raw["name_raw"])
            if sample_name != name:
                extra["sample_name"] = sample_name
            if raw["name_raw"] != sample_name.encode("ascii").ljust(22, b"\x00"):
                extra["sample_name_bytes"] = raw["name_raw"].hex()
            if raw["reserved"]:
                extra["sample_reserved"] = raw["reserved"]
            if not pcm:
                extra["sample_header"] = True
            sample = Sample(name, pcm, raw["volume"], raw["finetune"], start, span, None, bits, loop_mode,
                            raw["panning"], raw["relative_note"])
        if extra:
            instruments_meta[str(slot)] = extra
        samples.append(sample)
    if not samples:
        samples.append(Sample("", (), 64))
        _note(notes, "INSTRUMENT_ADDED", "converted", "The file has no instrument; an empty one was added "
              "(this profile holds at least one).")
    if cursor < len(payload):
        _note(notes, "TRAILING_DATA_DROPPED", "converted",
              f"{len(payload) - cursor} bytes after the last sample (extension chunks or padding) are not kept.",
              details={"bytes": len(payload) - cursor})
    if odd_headers:
        _note(notes, "XM_HEADER_SIZE_KEPT", "preserved", "These instrument headers have an unusual size (such as 33 "
              "bytes) or sample header size field; they are read as the file lays them out and written back as read.",
              odd_headers)
    if fadeouts:
        _note(notes, "XM_FADEOUT_CLAMPED", "preserved", f"These instruments store a fadeout above {MAX_FADEOUT} "
              "(FastTracker II's maximum); `fadeout` shows the clamped value and `fadeout_raw` the file's, which is "
              "written back until `fadeout` is edited.", fadeouts)
    if loop_types:
        _note(notes, "XM_LOOP_TYPE_KEPT", "preserved", "These samples set both loop bits (type 3, undefined); they "
              "play as ping-pong loops, like in libxmp and OpenMPT, and the type is written back as read.", loop_types)
    if converted_loops:
        for slot, start, span, frames in converted_loops:
            _note(notes, "SAMPLE_LOOP_CLAMPED", "converted",
                  f"Instrument {slot}: the loop ran past the sample end (start {start}, length {span}, sample "
                  f"{frames} frames) and was shortened to end at the sample end, or dropped when it started past "
                  "the end. The export differs from the source.", [slot],
                  {"loop_start": start, "loop_length": span, "sample_frames": frames})
    if ignored_loops:
        _note(notes, "SAMPLE_IGNORED_LOOP_KEPT", "preserved", "These samples store loop points although their loop "
              "type is none (or a zero-length loop); the values are kept and written back.", ignored_loops)
    if instruments_meta:
        metadata["instruments"] = instruments_meta
    if notes:
        metadata["import_notes"] = notes
    module = Module(title, samples, patterns, orders, {"xm": metadata}, channels, "xm")
    validate_xm(module)
    # Report what a re-export does not reproduce, region by region (the music is the same).
    again = _encode(module, metadata)
    if again != payload and not any(note["kind"] == "converted" for note in notes):
        differing = _differences(payload, again)
        _note(notes, "REPACKED", "converted", "The re-exported file differs from the source in "
              + ", ".join(differing) + " (pattern packing, header padding or similar); the music data is the same.")
        metadata["import_notes"] = notes
    return module


def _differences(a: bytes, b: bytes) -> list[str]:
    if len(a) != len(b):
        return [f"length ({len(a)} to {len(b)} bytes)"]
    first = next(index for index in range(len(a)) if a[index] != b[index])
    return [f"the bytes from offset {first}"]


def read(path: Path) -> Module:
    if path.stat().st_size > MAX_XM_BYTES:
        raise ValidationError("XM file too large for this profile.", "FILE_TOO_LARGE")
    return decode(path.read_bytes())
