"""Classify a 32-byte (0x + 64 hex) word found in calldata or event logs.

Pure functions, no network. Given the raw word plus light context (the set
of known tx/block hashes in the surrounding block, and known addresses),
return a category label and a human-readable note.

Categories:
  zero            all 32 bytes are 0x00
  bool            canonical ABI bool (0 or 1 in the last byte, rest zero)
  address         left-padded 20-byte address (12 leading zero bytes)
  selector_word   4-byte function selector right-padded with zeros
  uint256_small   numeric value that fits in <= 8 bytes (amount / id / nonce)
  uint256         numeric value using 9..31 significant bytes
  timestamp       small uint that lands in a plausible unix-time range
  bytes32_string  decodes to printable ASCII (right-zero-padded short string)
  tx_hash         matches a transaction hash seen in the block
  block_hash      matches the block hash
  opaque_hash     high-entropy 32 bytes with no detectable structure
                  (merkle root / salt / commit / storage slot / digest)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

HEX32_RE = re.compile(r"(?:0x)?([0-9a-fA-F]{64})")

# Plausible unix-time window: 2017-01-01 .. 2035-01-01 (seconds).
_TS_MIN = 1_483_228_800
_TS_MAX = 2_051_222_400


@dataclass
class Classification:
    category: str
    note: str
    value_dec: str | None = None  # decimal rendering when numeric


def normalize(word: str) -> str | None:
    """Return a lowercase 64-char hex string (no 0x) or None if not bytes32."""
    m = HEX32_RE.fullmatch(word.strip())
    if not m:
        return None
    return m.group(1).lower()


def _shannon_entropy(b: bytes) -> float:
    if not b:
        return 0.0
    counts = [0] * 256
    for x in b:
        counts[x] += 1
    n = len(b)
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return ent  # bits per byte, 0..8


def _try_ascii(b: bytes) -> str | None:
    """bytes32 short-string: nonzero printable ASCII then right zero padding."""
    stripped = b.rstrip(b"\x00")
    if not stripped or len(stripped) > 31:
        return None
    if all(0x20 <= c < 0x7f for c in stripped):
        txt = stripped.decode("ascii")
        # avoid flagging things that are "printable" but clearly not text
        letters = sum(c.isalnum() or c in " _-.:/" for c in txt)
        if letters >= max(2, len(txt) * 0.6):
            return txt
    return None


def classify(
    hex64: str,
    *,
    known_tx_hashes: frozenset[str] = frozenset(),
    block_hash: str | None = None,
    known_addresses: frozenset[str] = frozenset(),
) -> Classification:
    """Classify a normalized 64-hex-char string."""
    b = bytes.fromhex(hex64)

    if not any(b):
        return Classification("zero", "all-zero word", "0")

    # context matches first — strongest signal
    if hex64 in known_tx_hashes:
        return Classification("tx_hash", "matches a tx hash in this block")
    if block_hash and hex64 == block_hash:
        return Classification("block_hash", "matches the block hash")

    ival = int.from_bytes(b, "big")
    sig_bytes = (ival.bit_length() + 7) // 8

    # bool
    if b[:31] == b"\x00" * 31 and b[31] in (0, 1):
        return Classification("bool", f"ABI bool = {b[31]}", str(b[31]))

    # numeric interpretations (before address: a value that fits in <= 8 bytes
    # is far more likely an amount / id / nonce / timestamp than an address)
    if sig_bytes <= 8:
        if _TS_MIN <= ival <= _TS_MAX:
            return Classification(
                "timestamp", f"plausible unix time ({ival})", str(ival)
            )
        return Classification(
            "uint256_small", f"small integer ({sig_bytes} sig. bytes)", str(ival)
        )

    # function selector right-padded (4 nonzero bytes, then all zeros)
    if b[4:] == b"\x00" * 28 and any(b[:4]):
        return Classification("selector_word", f"4-byte selector 0x{hex64[:8]}")

    # left-padded address: 12 zero bytes then a 9..20 significant-byte remainder
    if b[:12] == b"\x00" * 12 and any(b[12:]):
        addr = "0x" + hex64[24:]
        if addr in known_addresses:
            return Classification("address", f"known address {addr}")
        return Classification("address", f"left-padded address {addr}")

    # a short ASCII bytes32 string?
    ascii_txt = _try_ascii(b)
    if ascii_txt is not None:
        return Classification("bytes32_string", f'ASCII "{ascii_txt}"')

    if sig_bytes <= 31:
        # large number but not full-width; likely a big uint256 amount
        ent = _shannon_entropy(b)
        if ent < 3.5:
            return Classification(
                "uint256", f"large integer ({sig_bytes} sig. bytes)", str(ival)
            )
        # otherwise falls through to opaque

    # full-width, high entropy → opaque 32-byte digest
    ent = _shannon_entropy(b)
    return Classification(
        "opaque_hash",
        f"opaque 32-byte value (entropy {ent:.2f} bits/byte) — "
        f"hash / merkle root / salt / commit / storage slot",
    )
