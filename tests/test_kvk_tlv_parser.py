"""Tests for KVK BER-TLV parser."""

from __future__ import annotations

import pytest
from kvk_reader.card.kvk_tlv_parser import parse_kvk_data, KvkParseError


def _build_tlv_field(tag: int, value: bytes) -> bytes:
    """Build a single TLV field."""
    length = len(value)
    if length <= 0x7F:
        return bytes([tag, length]) + value
    elif length <= 0xFF:
        return bytes([tag, 0x81, length]) + value
    else:
        return bytes([tag, 0x82, (length >> 8) & 0xFF, length & 0xFF]) + value


def _build_kvk_data(overrides: dict[int, bytes] | None = None) -> bytes:
    """Build complete KVK TLV data with given fields."""
    fields = {
        0x80: b"AOK Bayern",                    # Krankenkassenname
        0x81: b"1234567",                        # Krankenkassennummer
        0x8F: b"12345",                          # VKNR
        0x82: b"A123456789",                     # Versichertennummer
        0x83: b"1",                              # Versichertenstatus
        0x84: b"Dr.",                            # Titel
        0x85: b"Max",                            # Vorname
        0x87: b"Mustermann",                     # Familienname
        0x88: b"01011990",                       # Geburtsdatum TTMMJJJJ
        0x89: b"Musterstr. 1",                   # Strasse
        0x8A: b"D",                              # Laendercode
        0x8B: b"12345",                          # PLZ
        0x8C: b"Musterstadt",                    # Ort
        0x8D: b"1226",                           # Gueltigkeitsdatum MMJJ
    }
    if overrides:
        fields.update(overrides)

    inner = b""
    for tag in sorted(fields.keys()):
        value = fields[tag]
        if value:  # skip empty values
            inner += _build_tlv_field(tag, value)

    # XOR checksum
    xor = 0
    for b in inner:
        xor ^= b
    inner += _build_tlv_field(0x8E, bytes([xor]))

    # Outer container
    container_len = len(inner)
    if container_len <= 0x7F:
        return bytes([0x60, container_len]) + inner
    elif container_len <= 0xFF:
        return bytes([0x60, 0x81, container_len]) + inner
    else:
        return bytes([0x60, 0x82, (container_len >> 8) & 0xFF, container_len & 0xFF]) + inner


class TestKvkTlvParser:
    def test_parse_basic(self):
        data = _build_kvk_data()
        patient = parse_kvk_data(data)

        assert patient.vorname == "Max"
        assert patient.nachname == "Mustermann"
        assert patient.geburtsdatum == "01.01.1990"
        assert patient.titel == "Dr."
        assert patient.plz == "12345"
        assert patient.ort == "Musterstadt"
        assert patient.strasse == "Musterstr. 1"
        assert patient.krankenkasse_name == "AOK Bayern"
        assert patient.krankenkassen_nummer == "1234567"
        assert patient.versichertennummer == "A123456789"
        assert patient.versichertenstatus == "1"
        assert patient.gueltig_bis == "12/2026"
        assert patient.vknr == "12345"
        assert patient.card_type == "KVK"

    def test_parse_with_atr_prefix(self):
        """Data prefixed with 30 bytes ATR/directory data."""
        atr_prefix = bytes([0x82] + [0x00] * 29)
        kvk_data = _build_kvk_data()
        data = atr_prefix + kvk_data
        patient = parse_kvk_data(data)

        assert patient.vorname == "Max"
        assert patient.nachname == "Mustermann"

    def test_parse_din66003_encoding(self):
        """Test DIN 66003 special characters: { -> ä, | -> ö, etc."""
        data = _build_kvk_data({
            0x85: bytes([0x4D, 0x7B, 0x78]),                      # "Mäx"
            0x87: bytes([0x4D, 0x7C, 0x6C, 0x6C, 0x65, 0x72]),    # "Möller"
        })
        patient = parse_kvk_data(data)
        assert patient.vorname == "Mäx"
        assert patient.nachname == "Möller"

    def test_parse_gueltigkeitsdatum_19xx(self):
        data = _build_kvk_data({0x8D: b"0399"})
        patient = parse_kvk_data(data)
        assert patient.gueltig_bis == "03/1999"

    def test_parse_gueltigkeitsdatum_20xx(self):
        data = _build_kvk_data({0x8D: b"0630"})
        patient = parse_kvk_data(data)
        assert patient.gueltig_bis == "06/2030"

    def test_parse_missing_optional_fields(self):
        """KVK with only required fields (no title, no VKNR)."""
        data = _build_kvk_data({0x84: b"", 0x8F: b""})
        patient = parse_kvk_data(data)
        assert patient.titel == ""
        assert patient.vknr == ""
        assert patient.vorname == "Max"

    def test_parse_empty_data_raises(self):
        with pytest.raises(KvkParseError, match="too short"):
            parse_kvk_data(b"")

    def test_parse_wrong_container_tag_raises(self):
        with pytest.raises(KvkParseError, match="container tag"):
            parse_kvk_data(bytes([0x61, 0x02, 0x80, 0x00]))

    def test_checksum_mismatch_logs_warning(self):
        """Checksum mismatch logs a warning but still parses data."""
        data = bytearray(_build_kvk_data())
        # The checksum value is the very last byte in the container.
        # Corrupt a data byte (not the checksum TLV itself) to trigger mismatch.
        # Byte at index 2 is the first inner field byte.
        data[2] ^= 0x01
        # Should NOT raise — checksum mismatch is now a warning
        patient = parse_kvk_data(bytes(data))
        # Data is still parsed (some fields may be slightly off due to corruption)
        assert patient.card_type == "KVK"
