"""BER-TLV parser for KVK/PKV memory card data.

KVK data uses BER-TLV encoding with outer container tag 0x60.
Character encoding is DIN 66003 (German ISO 646 variant).

Reference: HL7 Wiki KVK specification, TeleTrusT MKT specification.
"""

from __future__ import annotations

import logging

from kvk_reader.card.models import PatientData
from kvk_reader.utils.encoding import decode_din66003

log = logging.getLogger(__name__)

# KVK TLV tag definitions
TAG_CONTAINER = 0x60
TAG_KRANKENKASSEN_NAME = 0x80
TAG_KRANKENKASSEN_NUMMER = 0x81
TAG_VKNR = 0x8F
TAG_VERSICHERTEN_NUMMER = 0x82
TAG_VERSICHERTEN_STATUS = 0x83
TAG_STATUS_ERGAENZUNG = 0x90
TAG_TITEL = 0x84
TAG_VORNAME = 0x85
TAG_NAMENSZUSATZ = 0x86
TAG_FAMILIENNAME = 0x87
TAG_GEBURTSDATUM = 0x88
TAG_STRASSE = 0x89
TAG_WOHNSITZ_LAENDERCODE = 0x8A
TAG_POSTLEITZAHL = 0x8B
TAG_ORTSNAME = 0x8C
TAG_GUELTIGKEITSDATUM = 0x8D
TAG_PRUEFSUMME = 0x8E


class KvkParseError(Exception):
    """Raised when KVK data cannot be parsed."""


def _find_container(data: bytes) -> int:
    """Find the offset of the 0x60 BER-TLV container in raw card data.

    Scans the data for the container tag 0x60 followed by a valid
    BER length and a plausible first inner tag (0x80-0x90).
    The complete container must fit within the available data.

    Args:
        data: Raw card data bytes.

    Returns:
        Offset of the 0x60 tag.

    Raises:
        KvkParseError: If no valid container found.
    """
    for i in range(len(data) - 3):
        if data[i] != TAG_CONTAINER:
            continue

        # Check that a valid BER length follows
        try:
            container_len, len_bytes = _read_ber_length(data, i + 1)
        except KvkParseError:
            continue

        # Sanity check: container must have reasonable size (>10 bytes)
        if container_len < 10:
            continue

        # Container data must fit within available data
        container_data_start = i + 1 + len_bytes
        container_data_end = container_data_start + container_len
        if container_data_end > len(data):
            continue  # Container doesn't fit — try next 0x60

        # Check first inner byte is a plausible KVK tag (0x80-0x90)
        if container_data_start < len(data):
            first_tag = data[container_data_start]
            if 0x80 <= first_tag <= 0x90:
                return i

    raise KvkParseError(
        f"No valid container tag 0x60 found in {len(data)} bytes of data"
    )


def _read_ber_length(data: bytes, offset: int) -> tuple[int, int]:
    """Read BER-TLV length field. Returns (length, bytes_consumed)."""
    if offset >= len(data):
        raise KvkParseError(f"Unexpected end of data at offset {offset}")

    first = data[offset]
    if first <= 0x7F:
        return first, 1
    elif first == 0x81:
        if offset + 1 >= len(data):
            raise KvkParseError("Truncated length field")
        return data[offset + 1], 2
    elif first == 0x82:
        if offset + 2 >= len(data):
            raise KvkParseError("Truncated length field")
        return (data[offset + 1] << 8) | data[offset + 2], 3
    else:
        raise KvkParseError(f"Unsupported BER length encoding: 0x{first:02X}")


def _format_geburtsdatum(raw: str) -> str:
    """Convert TTMMJJJJ to TT.MM.JJJJ."""
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[0:2]}.{raw[2:4]}.{raw[4:8]}"
    return raw


def _format_gueltigkeitsdatum(raw: str) -> str:
    """Convert MMJJ to MM/20JJ or MM/19JJ."""
    if len(raw) == 4 and raw.isdigit():
        month = raw[0:2]
        year = int(raw[2:4])
        full_year = 2000 + year if year < 80 else 1900 + year
        return f"{month}/{full_year}"
    return raw


def parse_kvk_data(raw_data: bytes) -> PatientData:
    """Parse KVK/PKV card raw binary data into PatientData.

    Args:
        raw_data: Raw bytes read from the KVK memory card.

    Returns:
        PatientData populated with parsed fields.

    Raises:
        KvkParseError: If the data format is invalid.
    """
    if len(raw_data) < 3:
        raise KvkParseError("Data too short")

    # Find the 0x60 container tag in the data.
    # Some readers prepend ATR/directory data or other headers.
    # Search for 0x60 followed by a valid BER length.
    offset = _find_container(raw_data)

    # Skip the container tag
    offset += 1

    # Read container length
    container_len, len_bytes = _read_ber_length(raw_data, offset)
    offset += len_bytes
    container_end = offset + container_len

    if container_end > len(raw_data):
        raise KvkParseError(
            f"Container length ({container_len}) exceeds data "
            f"(available: {len(raw_data) - offset + len_bytes} bytes)"
        )

    # Parse inner TLV fields
    fields: dict[int, bytes] = {}
    checksum_data_start = offset

    while offset < container_end:
        tag = raw_data[offset]
        offset += 1

        field_len, len_bytes = _read_ber_length(raw_data, offset)
        offset += len_bytes

        if offset + field_len > container_end:
            raise KvkParseError(f"Field 0x{tag:02X} length exceeds container")

        fields[tag] = raw_data[offset : offset + field_len]
        offset += field_len

    # Validate XOR checksum if present
    if TAG_PRUEFSUMME in fields:
        expected = fields[TAG_PRUEFSUMME][0]
        # Checksum is XOR over all data bytes excluding the checksum TLV itself
        checksum_data = raw_data[checksum_data_start:container_end]
        # Remove the checksum field (tag + length + value = 3 bytes at end)
        checksum_data = checksum_data[: -(1 + 1 + 1)]
        computed = 0
        for b in checksum_data:
            computed ^= b
        if computed != expected:
            # Log as warning but don't abort — real KVK cards may use
            # a different checksum algorithm (additive, CRC, etc.)
            # and the data is still usable
            log.warning(
                "KVK Prüfsumme weicht ab: berechnet 0x%02X, erwartet 0x%02X "
                "(Daten werden trotzdem verwendet)", computed, expected
            )

    # Decode fields
    def get_str(tag: int) -> str:
        if tag in fields:
            return decode_din66003(fields[tag])
        return ""

    geburtsdatum_raw = get_str(TAG_GEBURTSDATUM)
    gueltig_raw = get_str(TAG_GUELTIGKEITSDATUM)

    return PatientData(
        vorname=get_str(TAG_VORNAME),
        nachname=get_str(TAG_FAMILIENNAME),
        geburtsdatum=_format_geburtsdatum(geburtsdatum_raw),
        titel=get_str(TAG_TITEL),
        namenszusatz=get_str(TAG_NAMENSZUSATZ),
        strasse=get_str(TAG_STRASSE),
        plz=get_str(TAG_POSTLEITZAHL),
        ort=get_str(TAG_ORTSNAME),
        wohnsitzlaendercode=get_str(TAG_WOHNSITZ_LAENDERCODE) or "D",
        krankenkasse_name=get_str(TAG_KRANKENKASSEN_NAME),
        krankenkassen_nummer=get_str(TAG_KRANKENKASSEN_NUMMER),
        versichertennummer=get_str(TAG_VERSICHERTEN_NUMMER),
        versichertenstatus=get_str(TAG_VERSICHERTEN_STATUS),
        versichertenart="",
        gueltig_bis=_format_gueltigkeitsdatum(gueltig_raw),
        vknr=get_str(TAG_VKNR),
        status_ergaenzung=get_str(TAG_STATUS_ERGAENZUNG),
        card_type="KVK",
    )
