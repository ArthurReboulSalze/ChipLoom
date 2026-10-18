"""Bounded, read-only layout checks shared by analysis and sample extraction."""
from __future__ import annotations

from dataclasses import dataclass
import re
import struct

MAX_FILE = 4 * 1024 * 1024
MAX_ARCHIVE = 64 * 1024 * 1024


@dataclass(frozen=True)
class ReferenceLayout:
    channels: int
    orders: list[int]
    headers: list[tuple[int, int, int, int, int]]
    pattern_bytes: int
    pattern_count: int


def parse_layout(raw: bytes) -> ReferenceLayout:
    if not 1084 <= len(raw) <= MAX_FILE:
        raise ValueError("Reference must be a MOD with a 31-sample header, at most 4 MiB.")
    signature = raw[1080:1084].decode("ascii", errors="replace")
    if signature in ("M.K.", "M!K!", "4CHN"):
        channels = 4
    elif re.fullmatch(r"[1-9]CHN|[1-3][0-9]CH", signature):
        channels = int(re.match(r"\d+", signature)[0])
    else:
        raise ValueError(f"Unsupported signature for structural analysis: {signature!r}")
    if channels > 32 or not 1 <= raw[950] <= 128:
        raise ValueError("Invalid channel count or order count.")
    orders = list(raw[952:952 + raw[950]])
    if max(orders) >= 128:
        raise ValueError("Invalid pattern number.")
    headers = [struct.unpack_from(">HBBHH", raw, 42 + index * 30) for index in range(31)]
    pcm_size = sum(header[0] * 2 for header in headers)
    stride = 64 * channels * 4
    pattern_bytes = len(raw) - 1084 - pcm_size
    if pattern_bytes < (max(orders) + 1) * stride or pattern_bytes % stride:
        raise ValueError("Truncated or ambiguous pattern/sample layout; no approximate parsing.")
    pattern_count = pattern_bytes // stride
    if pattern_count > 128:
        raise ValueError("Too many stored patterns for this analysis profile.")
    return ReferenceLayout(channels, orders, headers, pattern_bytes, pattern_count)
