"""MOD reader/writer (2 to 32 channels), separate from every audio replay implementation.

Reads M.K., M!K!, FLT4 and 4CHN files (four channels) and the channel-count signatures 2CHN ..
9CHN and 10CH .. 32CH (FastTracker/TakeTracker convention). FLT8 (Startrekker pairs of
four-channel patterns), CD61/CD81/OCTA (Octalyser, which has its own flow rules) and TDZx are
rejected with their own codes. Everything that the model cannot express natively
(signature, restart byte, inactive order entries, odd sample headers, non-ASCII text) is
kept in `module.metadata["mod"]` and written back, so a clean import re-exports byte for
byte. What cannot be kept (a loop running past the sample end, volumes above 64, a
two-byte sample, M.K. with more than 64 patterns) is converted and listed in
`import_notes(module)`; nothing is changed silently.
"""

from __future__ import annotations

from pathlib import Path
import re
import struct

from .model import (
    DEFAULT_RESTART_BYTE, MAX_MK_PATTERNS, MAX_PATTERNS, MOD_SIGNATURES, Cell, Module, Pattern, Sample,
    MOD_MAX_CHANNELS, ValidationError, ascii_field, mod_order_table, mod_profile, mod_signature, validate,
)

HEADER_SIZE = 1084
PATTERN_SIZE = 64 * 4 * 4  # a four-channel pattern; see pattern_size()
MAX_MOD_BYTES = HEADER_SIZE + MAX_PATTERNS * 64 * MOD_MAX_CHANNELS * 4 + 31 * 65_534


def pattern_size(channels: int) -> int:
    return 64 * channels * 4


def parse_signature(signature: str) -> int:
    """Channel count named by a MOD signature, or a ValidationError with a specific code."""
    if signature in MOD_SIGNATURES:
        return 4
    match = re.fullmatch(r"([2-9])CHN|(1[0-9]|2[0-9]|3[0-2])CH", signature)
    if match:
        return int(match.group(1) or match.group(2))
    if signature == "FLT8":
        raise ValidationError("FLT8 stores each pattern as two four-channel patterns (Startrekker); it is not "
                              "supported. Convert it to 8CHN in a tracker first.", "MOD_FLT8")
    if signature in ("CD61", "CD81", "OCTA") or re.fullmatch(r"TDZ[1-9]", signature):
        raise ValidationError(f"{signature} is an Octalyser/TakeTracker variant whose flow and effect rules differ "
                              "from ProTracker's; it is not supported.", "MOD_VARIANT")
    shown = "".join(character if " " <= character <= "~" else "?" for character in signature)
    raise ValidationError(f"Not a supported MOD: the signature at offset 1080 is {shown!r}. Accepted signatures: "
                          "M.K., M!K!, FLT4 and 4CHN (four channels), 2CHN to 9CHN and 10CH to 32CH. An XM file "
                          "(\"Extended Module: \" header) is read by the XM reader; a .json project is loaded "
                          "as a project, not as a module file.", "MOD_FORMAT")


def sanitize_text(raw: bytes) -> str:
    """Display text of a fixed-size MOD text field: up to the first NUL, '?' for bytes
    outside printable ASCII. Archive and module text is data, never instructions."""
    return "".join(chr(value) if 32 <= value <= 126 else "?" for value in raw.split(b"\x00", 1)[0])


def import_notes(module: Module) -> list[dict]:
    """Import report: [{code, kind, message, slots?, details?}]. `kind` is "preserved" when
    the detail is stored and re-exported exactly, "converted" when the export differs
    from the source. Empty for a plain M.K. module. cli.py `import` should print these."""
    return list(mod_profile(module).get("import_notes", []))


def _text_field(raw_text: str, stored_hex: str | None, size: int, label: str) -> bytes:
    if stored_hex is not None:
        raw = bytes.fromhex(stored_hex)
        if sanitize_text(raw) == raw_text:
            return raw
    return ascii_field(raw_text, size, label)


def encode(module: Module) -> bytes:
    validate(module)
    return _encode(module, mod_profile(module))


def encode_for_replay(module: Module) -> bytes:
    """Canonical ProTracker bytes of the same music, for an in-process replay engine.

    Drops what changes no sound but steers libxmp's tracker-detection heuristics: the restart
    byte, odd loop/finetune/text header bytes and the FLT4/4CHN signature (M.K., or M!K! above
    64 patterns). libxmp 4.7 crashes in the real-time start-up sequence on some modules that
    carry such header details, so `realtime.XmpEngine` loads this copy; the deliverable file
    is always `encode`. Inactive order entries stay, as they decide how many patterns a
    reader counts.
    """
    validate(module)
    profile = mod_profile(module)
    return _encode(module, {"inactive_orders": profile.get("inactive_orders", {})})


def _encode(module: Module, profile: dict) -> bytes:
    quirks = profile.get("sample_quirks", {})
    output = bytearray(_text_field(module.title, profile.get("title_bytes"), 20, "Titre"))
    for index in range(31):
        sample = module.samples[index] if index < len(module.samples) else Sample("", (), volume=0)
        quirk = quirks.get(str(index + 1), {})
        output.extend(_text_field(sample.name, quirk.get("name_bytes"), 22, "Nom de sample"))
        if sample.loop_length:
            loop_start, loop_length = sample.loop_start // 2, sample.loop_length // 2
        else:
            loop_start, loop_length = quirk.get("header_loop_words", (0, 1))
        output.extend(struct.pack(
            ">HBBHH", len(sample.pcm) // 2, (sample.finetune & 15) | (quirk.get("finetune_high", 0) << 4),
            sample.volume, loop_start, loop_length,
        ))
    # ProTracker writes 0x7F here and ignores it; any other byte is kept as imported.
    output.extend(bytes((len(module.orders), profile.get("restart_byte", DEFAULT_RESTART_BYTE))))
    output.extend(bytes(mod_order_table(module, profile)))
    output.extend(mod_signature(module, profile).encode("ascii"))
    for pattern in module.patterns:
        for row in range(64):
            for channel in range(module.channels):
                value = pattern.get(row, channel)
                output.extend((
                    (value.sample & 0xF0) | (value.period >> 8), value.period & 0xFF,
                    ((value.sample & 15) << 4) | value.command, value.param,
                ))
    for sample in module.samples:
        output.extend(value & 255 for value in sample.pcm)
    return bytes(output)


def _note(notes: list, code: str, kind: str, message: str, slots=None, details=None) -> None:
    note = {"code": code, "kind": kind, "message": message}
    if slots:
        note["slots"] = list(slots)
    if details:
        note["details"] = details
    notes.append(note)


def decode(payload: bytes) -> Module:
    if not HEADER_SIZE <= len(payload) <= MAX_MOD_BYTES:
        raise ValidationError("Taille MOD invalide pour le profil v1.", "MOD_FORMAT")
    signature = payload[1080:1084].decode("latin1")
    channels = parse_signature(signature)
    length = payload[950]
    if not 1 <= length <= 128:
        raise ValidationError("Longueur de liste d'ordres MOD invalide.", "MOD_FORMAT")
    restart = payload[951]
    order_table = payload[952:1080]
    orders = list(order_table[:length])
    inactive = {str(slot): value for slot, value in enumerate(order_table) if slot >= length and value}
    if max(order_table) > 127:
        raise ValidationError("An order entry is above 127, which no player accepts as a pattern number.", "MOD_FORMAT")

    headers = [struct.unpack_from(">HBBHH", payload, 20 + index * 30 + 22) for index in range(31)]
    pcm_total = sum(item[0] * 2 for item in headers)

    def stored_size(count: int) -> int:
        return HEADER_SIZE + count * pattern_size(channels) + pcm_total

    # Players count patterns from the highest entry of the whole 128-entry table (inactive
    # entries included). If the file only fits the active entries, an inactive entry dangles.
    counted, active_count = max(order_table) + 1, max(orders) + 1
    notes: list[dict] = []
    if len(payload) == stored_size(counted):
        pattern_count = counted
    elif len(payload) == stored_size(active_count):
        pattern_count = active_count
        _note(notes, "ORDERS_DANGLING", "preserved",
              "Inactive order entries name patterns that are not stored; they are kept as imported, "
              "but players that count patterns from all 128 entries will read this file differently.")
    else:
        raise ValidationError(
            f"MOD tronqué ou données supplémentaires : {stored_size(counted)} octets attendus, {len(payload)} reçus.",
            "MOD_FORMAT")
    if pattern_count > MAX_PATTERNS:
        raise ValidationError(f"This file stores {pattern_count} patterns; ProTracker's limit is {MAX_PATTERNS}.",
                              "PATTERNS")

    metadata: dict = {}
    if channels != 4:
        pass  # the signature itself names the channel count; nothing to keep
    elif pattern_count > MAX_MK_PATTERNS and signature != "M!K!":
        _note(notes, "SIGNATURE_CONVERTED", "converted",
              f"{signature} with {pattern_count} patterns is exported as M!K! (the signature ProTracker uses "
              f"above {MAX_MK_PATTERNS} patterns); the module data is unchanged.")
    elif signature == "M!K!" and pattern_count <= MAX_MK_PATTERNS:
        metadata["signature"] = signature
        _note(notes, "SIGNATURE_KEPT", "preserved",
              f"M!K! with only {pattern_count} patterns is written back as M!K!.")
    elif signature in ("FLT4", "4CHN"):
        metadata["signature"] = signature
        _note(notes, "SIGNATURE_REPLAY", "preserved",
              f"{signature} is written back unchanged. libopenmpt plays it like M.K.; libxmp 4.7 does not load it "
              "reliably, so real-time replay uses an M.K. copy of the same music (mod.encode_for_replay). "
              "Tracker-specific behaviour of the original program is not reproduced.")
    if restart != DEFAULT_RESTART_BYTE:
        metadata["restart_byte"] = restart
        _note(notes, "RESTART_BYTE_KEPT", "preserved",
              f"Restart byte 0x{restart:02X} is written back unchanged. ProTracker ignores it; the playback "
              "plan loops back to order 0.")
    if inactive:
        metadata["inactive_orders"] = inactive
        _note(notes, "INACTIVE_ORDERS_KEPT", "preserved",
              f"{len(inactive)} nonzero inactive order entries (positions beyond the song length) are kept and "
              "written back.", details={"slots": sorted(int(slot) for slot in inactive)})

    title_raw = payload[:20]
    title = sanitize_text(title_raw)
    if title_raw != title.encode("ascii").ljust(20, b"\x00"):
        metadata["title_bytes"] = title_raw.hex()
        _note(notes, "TEXT_KEPT_RAW", "preserved",
              "The title contains bytes outside printable ASCII or after the first NUL; shown with '?' "
              "and written back unchanged until it is renamed.")

    quirks: dict[str, dict] = {}
    finetune_high, header_words, heads = [], [], []
    clamped, dropped, volumes, tiny, raw_names = [], [], [], [], []
    samples_meta = []
    for index, (size, tune_byte, volume, loop_start, loop_length) in enumerate(headers, 1):
        start = 20 + (index - 1) * 30
        name_raw = payload[start:start + 22]
        name = sanitize_text(name_raw)
        quirk: dict = {}
        if name_raw != name.encode("ascii").ljust(22, b"\x00"):
            quirk["name_bytes"] = name_raw.hex()
            raw_names.append(index)
        if tune_byte >> 4:
            quirk["finetune_high"] = tune_byte >> 4
            finetune_high.append(index)
        tune = tune_byte & 15
        tune = tune if tune < 8 else tune - 16
        if volume > 64:
            volumes.append(index)
            volume = 64
        samples_meta.append((index, name, size * 2, tune, volume, loop_start, loop_length, quirk))
    cursor = HEADER_SIZE + pattern_count * pattern_size(channels)
    samples = []
    for index, name, size, tune, volume, loop_start, loop_length, quirk in samples_meta:
        pcm = tuple(value if value < 128 else value - 256 for value in payload[cursor:cursor + size])
        cursor += size
        if size == 2:
            tiny.append(index)
            pcm, size = (), 0
        start, span = loop_start * 2, loop_length * 2
        sample_loop, converted = (0, 0), False
        if size and loop_length > 1:
            if start + span <= size:
                sample_loop = (start, span)
            else:
                converted = True
                if size - start >= 4:
                    sample_loop = (start, size - start)
                    clamped.append((index, loop_start, loop_length, size // 2))
                else:
                    dropped.append((index, loop_start, loop_length, size // 2))
        if sample_loop == (0, 0) and not converted and (loop_start, loop_length) != (0, 1):
            quirk["header_loop_words"] = [loop_start, loop_length]
            header_words.append(index)
        if sample_loop == (0, 0) and any(pcm[:2]):
            quirk["unlooped_head"] = True
            heads.append(index)
        if quirk:
            quirks[str(index)] = quirk
        samples.append(Sample(name, pcm, volume, tune, *sample_loop))
    if cursor != len(payload):
        raise ValidationError("Internal MOD layout error.", "MOD_FORMAT")

    if raw_names:
        _note(notes, "TEXT_KEPT_RAW", "preserved",
              "These sample names contain bytes outside printable ASCII or after the first NUL; they are shown "
              "with '?' and written back unchanged until renamed.", raw_names)
    if finetune_high:
        _note(notes, "SAMPLE_FINETUNE_HIGH_NIBBLE", "preserved",
              "The high nibble of the finetune byte is set; players ignore it. Kept and written back.", finetune_high)
    if header_words:
        _note(notes, "SAMPLE_LOOP_WORDS_KEPT", "preserved",
              "The loop header words of an unlooped sample differ from ProTracker's 0, 1 (for example loop "
              "length 0). They mean 'no loop' for every player; kept and written back.", header_words)
    if heads:
        _note(notes, "SAMPLE_UNLOOPED_HEAD", "preserved",
              "These unlooped samples do not start with two zero bytes. ProTracker keeps replaying that first "
              "word after the sample ends; libxmp and libopenmpt stop instead. PCM kept as is.", heads)
    for index, loop_start, loop_length, words in clamped:
        _note(notes, "SAMPLE_LOOP_CLAMPED", "converted",
              f"Sample {index}: the loop ran past the sample end (start {loop_start}, length {loop_length}, "
              f"sample {words} words); the loop length was shortened so that it ends at the sample end, as libxmp "
              "plays it (libopenmpt renders an out-of-range loop differently). The export differs from the source.", [index],
              {"loop_start_words": loop_start, "loop_length_words": loop_length, "sample_words": words})
    for index, loop_start, loop_length, words in dropped:
        _note(notes, "SAMPLE_LOOP_DROPPED", "converted",
              f"Sample {index}: the loop starts at or near the sample end (start {loop_start}, length "
              f"{loop_length}, sample {words} words) and leaves fewer than 4 bytes to repeat; the loop was "
              "removed. The export differs from the source.", [index],
              {"loop_start_words": loop_start, "loop_length_words": loop_length, "sample_words": words})
    if volumes:
        _note(notes, "SAMPLE_VOLUME_CLAMPED", "converted",
              "Sample volume above 64 was set to 64 (libopenmpt does the same; libxmp refuses to load such a file). "
              "The export differs from the source.", volumes)
    if tiny:
        _note(notes, "SAMPLE_TWO_BYTES_DROPPED", "converted",
              "A sample of one word (2 bytes) is treated as empty by ProTracker; it was imported as an empty "
              "slot and its 2 bytes are not exported.", tiny)

    if quirks:
        metadata["sample_quirks"] = quirks
    if notes:
        metadata["import_notes"] = notes
    patterns = []
    cursor = HEADER_SIZE
    for index in range(pattern_count):
        pattern = Pattern(f"Pattern {index:02X}")
        for row in range(64):
            for channel in range(channels):
                a, b, c, d = payload[cursor:cursor + 4]
                cursor += 4
                value = Cell(((a & 15) << 8) | b, (a & 0xF0) | (c >> 4), c & 15, d)
                pattern.put(row, channel, value)
        patterns.append(pattern)
    module = Module(title, samples, patterns, orders, {"mod": metadata} if metadata else {}, channels)
    validate(module)
    return module


def read(path: Path) -> Module:
    if path.stat().st_size > MAX_MOD_BYTES:
        raise ValidationError("Fichier trop grand pour le profil MOD v1.", "FILE_TOO_LARGE")
    return decode(path.read_bytes())
