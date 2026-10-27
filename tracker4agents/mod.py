"""Strict M.K. reader/writer, separate from every audio replay implementation."""

from __future__ import annotations

from pathlib import Path
import struct

from .model import Cell, Module, Pattern, Sample, ValidationError, ascii_field, validate

HEADER_SIZE = 1084
PATTERN_SIZE = 64 * 4 * 4
MAX_MOD_BYTES = HEADER_SIZE + 64 * PATTERN_SIZE + 31 * 65_534


def encode(module: Module) -> bytes:
    validate(module)
    output = bytearray(ascii_field(module.title, 20, "Titre"))
    for index in range(31):
        sample = module.samples[index] if index < len(module.samples) else Sample("", (), volume=0)
        output.extend(ascii_field(sample.name, 22, "Nom de sample"))
        output.extend(struct.pack(
            ">HBBHH", len(sample.pcm) // 2, sample.finetune & 15, sample.volume,
            sample.loop_start // 2, sample.loop_length // 2 if sample.loop_length else 1,
        ))
    # 0x7F is ProTracker's sentinel here, not a playback restart order.
    output.extend(bytes((len(module.orders), 0x7F)))
    output.extend(bytes(module.orders).ljust(128, b"\x00"))
    output.extend(b"M.K.")
    for pattern in module.patterns:
        for row in range(64):
            for channel in range(4):
                value = pattern.get(row, channel)
                output.extend((
                    (value.sample & 0xF0) | (value.period >> 8), value.period & 0xFF,
                    ((value.sample & 15) << 4) | value.command, value.param,
                ))
    for sample in module.samples:
        output.extend(value & 255 for value in sample.pcm)
    return bytes(output)


def decode(payload: bytes) -> Module:
    if not HEADER_SIZE <= len(payload) <= MAX_MOD_BYTES:
        raise ValidationError("Taille MOD invalide pour le profil v1.", "MOD_FORMAT")
    if payload[1080:1084] != b"M.K.":
        raise ValidationError("Seuls les MOD M.K. à 4 voies sont acceptés dans ce prototype.", "MOD_FORMAT")
    length = payload[950]
    if not 1 <= length <= 128:
        raise ValidationError("Longueur de liste d'ordres MOD invalide.", "MOD_FORMAT")
    if payload[951] != 0x7F:
        raise ValidationError("Ce MOD utilise un octet restart/tempo hors du profil ProTracker v1.", "MOD_FORMAT")
    order_table = payload[952:1080]
    if any(order_table[length:]):
        raise ValidationError("Ordres inactifs non nuls : variante MOD non prise en charge sans perte.", "MOD_FORMAT")
    orders = list(order_table[:length])
    pattern_count = max(orders) + 1
    if pattern_count > 64:
        raise ValidationError("Ce fichier dépasse les 64 patterns du profil M.K. v1.", "MOD_FORMAT")

    def text_at(start: int, size: int) -> str:
        raw = payload[start:start + size]
        raw_text = raw.rstrip(b"\x00")
        if b"\x00" in raw_text or any(value < 32 or value > 126 for value in raw_text):
            raise ValidationError("Texte MOD hors ASCII imprimable du profil v1.", "MOD_FORMAT")
        return raw_text.decode("ascii")

    headers = []
    for index in range(31):
        start = 20 + index * 30
        size, tune, volume, loop_start, loop_length = struct.unpack_from(
            ">HBBHH", payload, start + 22,
        )
        if tune > 15 or loop_length == 0:
            raise ValidationError(f"En-tête du sample {index + 1} hors du profil v1.", "MOD_FORMAT")
        headers.append((text_at(start, 22), size * 2, tune if tune < 8 else tune - 16,
                        volume, loop_start * 2, loop_length * 2))
    expected = HEADER_SIZE + pattern_count * PATTERN_SIZE + sum(item[1] for item in headers)
    if len(payload) != expected:
        raise ValidationError(f"MOD tronqué ou données supplémentaires : {expected} octets attendus, {len(payload)} reçus.", "MOD_FORMAT")

    cursor = HEADER_SIZE
    patterns = []
    for index in range(pattern_count):
        pattern = Pattern(f"Pattern {index:02X}")
        for row in range(64):
            for channel in range(4):
                a, b, c, d = payload[cursor:cursor + 4]
                cursor += 4
                value = Cell(((a & 15) << 8) | b, (a & 0xF0) | (c >> 4), c & 15, d)
                pattern.put(row, channel, value)
        patterns.append(pattern)
    samples = []
    for name, size, tune, volume, loop_start, loop_length in headers:
        pcm = tuple(value if value < 128 else value - 256 for value in payload[cursor:cursor + size])
        cursor += size
        if loop_start == 0 and loop_length == 2:
            loop_length = 0
        samples.append(Sample(name, pcm, volume, tune, loop_start, loop_length))
    module = Module(text_at(0, 20), samples, patterns, orders)
    validate(module)
    return module


def read(path: Path) -> Module:
    if path.stat().st_size > MAX_MOD_BYTES:
        raise ValidationError("Fichier trop grand pour le profil MOD v1.", "FILE_TOO_LARGE")
    return decode(path.read_bytes())
