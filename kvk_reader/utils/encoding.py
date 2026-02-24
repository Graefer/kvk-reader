"""Character encoding utilities for KVK card data.

KVK cards use DIN 66003 (German ISO 646 variant / IA5) encoding.
This is essentially ASCII with German-specific substitutions for
characters at positions 0x5B-0x5D, 0x7B-0x7E.
"""

from __future__ import annotations

# DIN 66003 to Unicode mapping for non-ASCII positions
_DIN66003_MAP = {
    0x5B: "Ä",
    0x5C: "Ö",
    0x5D: "Ü",
    0x7B: "ä",
    0x7C: "ö",
    0x7D: "ü",
    0x7E: "ß",
}


def decode_din66003(data: bytes) -> str:
    """Decode DIN 66003 encoded bytes to a Python string."""
    chars = []
    for b in data:
        if b in _DIN66003_MAP:
            chars.append(_DIN66003_MAP[b])
        elif 0x20 <= b <= 0x7E:
            chars.append(chr(b))
        elif b == 0x00:
            break  # null terminator
        else:
            chars.append(chr(b))
    return "".join(chars).strip()
