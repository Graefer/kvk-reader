"""Tests for eGK XML parser (EF.PD and EF.VD)."""

import gzip
import struct

import pytest
from kvk_reader.card.egk_xml_parser import parse_ef_pd, parse_ef_vd, build_patient_data, EgkParseError


def _make_ef_pd(xml_str: str) -> bytes:
    """Create EF.PD binary: 2-byte length prefix + gzip-compressed XML."""
    xml_bytes = xml_str.encode("iso-8859-15")
    compressed = gzip.compress(xml_bytes)
    length = len(compressed)
    return struct.pack(">H", length) + compressed


def _make_ef_vd(xml_str: str) -> bytes:
    """Create EF.VD binary with offset header + gzip-compressed XML.

    End offsets are INCLUSIVE per gematik spec (last byte of the data block).
    """
    xml_bytes = xml_str.encode("iso-8859-15")
    compressed = gzip.compress(xml_bytes)
    # Header: 8 bytes (start_general, end_general, start_protected, end_protected)
    start = 8
    end = start + len(compressed) - 1  # inclusive: last byte index
    header = struct.pack(">HHHH", start, end, 0, 0)
    return header + compressed


SAMPLE_PD_XML = """\
<?xml version="1.0" encoding="ISO-8859-15"?>
<UC_PersoenlicheVersichertendatenXML
    xmlns="http://ws.gematik.de/fa/vsds/UC_PersoenlicheVersichertendatenXML/v5.2"
    CDM_VERSION="5.2.0">
  <Versicherten_ID>A123456789</Versicherten_ID>
  <Versicherter>
    <Person>
      <Geburtsdatum>1990-01-01</Geburtsdatum>
      <Vorname>Max</Vorname>
      <Nachname>Mustermann</Nachname>
      <Geschlecht>M</Geschlecht>
      <Titel>Dr.</Titel>
      <Vorsatzwort>von</Vorsatzwort>
      <StrassenAdresse>
        <Strasse>Musterstraße</Strasse>
        <Hausnummer>1</Hausnummer>
        <Postleitzahl>12345</Postleitzahl>
        <Ort>Musterstadt</Ort>
        <Land>
          <Wohnsitzlaendercode>D</Wohnsitzlaendercode>
        </Land>
      </StrassenAdresse>
    </Person>
  </Versicherter>
</UC_PersoenlicheVersichertendatenXML>"""

SAMPLE_VD_XML = """\
<?xml version="1.0" encoding="ISO-8859-15"?>
<UC_AllgemeineVersicherungsdatenXML
    xmlns="http://ws.gematik.de/fa/vsds/UC_AllgemeineVersicherungsdatenXML/v5.2"
    CDM_VERSION="5.2.0">
  <Versicherungsschutz>
    <Beginn>2020-01-01</Beginn>
    <Ende>2026-12-31</Ende>
    <Kostentraeger>
      <Kostentraegerkennung>108018007</Kostentraegerkennung>
      <Name>AOK Bayern</Name>
    </Kostentraeger>
  </Versicherungsschutz>
  <Zusatzinfos>
    <ZusatzinfosGKV>
      <Versichertenart>1</Versichertenart>
    </ZusatzinfosGKV>
  </Zusatzinfos>
</UC_AllgemeineVersicherungsdatenXML>"""


class TestEfPdParser:
    def test_parse_basic(self):
        raw = _make_ef_pd(SAMPLE_PD_XML)
        result = parse_ef_pd(raw)

        assert result["versicherten_id"] == "A123456789"
        assert result["vorname"] == "Max"
        assert result["nachname"] == "Mustermann"
        assert result["geburtsdatum"] == "01.01.1990"
        assert result["geschlecht"] == "M"
        assert result["titel"] == "Dr."
        assert result["vorsatzwort"] == "von"
        assert result["strasse"] == "Musterstraße"
        assert result["hausnummer"] == "1"
        assert result["plz"] == "12345"
        assert result["ort"] == "Musterstadt"

    def test_parse_too_short(self):
        with pytest.raises(EgkParseError, match="too short"):
            parse_ef_pd(b"\x00")


class TestEfVdParser:
    def test_parse_basic(self):
        raw = _make_ef_vd(SAMPLE_VD_XML)
        result = parse_ef_vd(raw)

        assert result["kostentraeger_name"] == "AOK Bayern"
        assert result["kostentraeger_kennung"] == "108018007"
        assert result["versichertenart"] == "1"
        assert result["versicherungsschutz_ende"] == "2026-12-31"

    def test_parse_too_short(self):
        with pytest.raises(EgkParseError, match="too short"):
            parse_ef_vd(b"\x00\x01\x02")


class TestBuildPatientData:
    def test_full_integration(self):
        ef_pd = _make_ef_pd(SAMPLE_PD_XML)
        ef_vd = _make_ef_vd(SAMPLE_VD_XML)
        patient = build_patient_data(ef_pd, ef_vd)

        assert patient.vorname == "Max"
        assert patient.nachname == "Mustermann"
        assert patient.geburtsdatum == "01.01.1990"
        assert patient.geschlecht == "M"
        assert patient.krankenkasse_name == "AOK Bayern"
        assert patient.krankenkassen_nummer == "108018007"
        assert patient.versichertennummer == "A123456789"
        assert patient.versichertenart == "1"
        assert patient.gueltig_bis == "12/2026"
        assert patient.card_type == "eGK"
        assert patient.strasse == "Musterstraße"
        assert patient.hausnummer == "1"
        assert patient.plz == "12345"
        assert patient.ort == "Musterstadt"
