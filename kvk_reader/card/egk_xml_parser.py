"""Parser for eGK card data (EF.PD and EF.VD).

EF.PD contains gzip-compressed XML with personal data (UC_PersoenlicheVersichertendatenXML).
EF.VD contains gzip-compressed XML with insurance data (UC_AllgemeineVersicherungsdatenXML).

Both use a 2-byte big-endian length prefix before the gzip payload.
XML encoding is ISO-8859-15, namespace varies by CDM version (5.1.0 / 5.2.0).
"""

from __future__ import annotations

import gzip
import zlib
from lxml import etree

from kvk_reader.card.models import PatientData

# Known XML namespaces for eGK VSD schemas
_NS_PD = {
    "pd": "http://ws.gematik.de/fa/vsds/UC_PersoenlicheVersichertendatenXML/v5.2",
    "pd51": "http://ws.gematik.de/fa/vsds/UC_PersoenlicheVersichertendatenXML/v5.1",
}
_NS_VD = {
    "vd": "http://ws.gematik.de/fa/vsds/UC_AllgemeineVersicherungsdatenXML/v5.2",
    "vd51": "http://ws.gematik.de/fa/vsds/UC_AllgemeineVersicherungsdatenXML/v5.1",
}


class EgkParseError(Exception):
    """Raised when eGK data cannot be parsed."""


def _decompress_ef(raw: bytes) -> bytes:
    """Decompress an EF file: 2-byte length prefix + gzip data."""
    if len(raw) < 2:
        raise EgkParseError("EF data too short")
    length = (raw[0] << 8) | raw[1]
    compressed = raw[2 : 2 + length]
    try:
        return gzip.decompress(compressed)
    except Exception as e:
        raise EgkParseError(f"Gzip decompression failed: {e}") from e


def _find_text(root: etree._Element, xpath: str, namespaces: dict) -> str:
    """Find text at xpath, trying multiple namespace prefixes."""
    for ns_prefix, ns_map in [
        (namespaces, namespaces),
    ]:
        elements = root.xpath(xpath, namespaces=ns_map)
        if elements:
            el = elements[0]
            return el.text.strip() if el.text else ""
    return ""


def _xpath_text(root: etree._Element, paths: list[str], ns: dict) -> str:
    """Try multiple XPath expressions and return first match."""
    for path in paths:
        try:
            elements = root.xpath(path, namespaces=ns)
            if elements:
                el = elements[0]
                return el.text.strip() if el.text else ""
        except etree.XPathEvalError:
            continue
    return ""


def _format_egk_date(date_str: str) -> str:
    """Convert ISO date (YYYY-MM-DD) or compact (YYYYMMDD) to German format (DD.MM.YYYY)."""
    if len(date_str) == 10 and date_str[4] == "-":
        parts = date_str.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[6:]}.{date_str[4:6]}.{date_str[:4]}"
    return date_str


def parse_ef_pd(raw: bytes) -> dict:
    """Parse EF.PD (personal data) from raw bytes.

    Returns dict with keys: versicherten_id, vorname, nachname, geburtsdatum,
    geschlecht, titel, vorsatzwort, namenszusatz, strasse, hausnummer, plz, ort,
    wohnsitzlaendercode.
    """
    xml_bytes = _decompress_ef(raw)
    root = etree.fromstring(xml_bytes)

    # Detect namespace from root tag
    ns_uri = root.nsmap.get(None, "")
    ns = {"p": ns_uri} if ns_uri else {}

    prefix = "p:" if ns else ""

    def txt(path: str) -> str:
        full = path.replace("//", f"//{prefix}").lstrip("/")
        # Build proper xpath
        parts = path.strip("/").split("/")
        xpath = "/".join(f"{prefix}{p}" for p in parts)
        xpath = f"//{xpath}"
        try:
            elements = root.xpath(xpath, namespaces=ns)
            if elements:
                return elements[0].text.strip() if elements[0].text else ""
        except etree.XPathEvalError:
            pass
        return ""

    geburtsdatum = txt("Versicherter/Person/Geburtsdatum")

    return {
        "versicherten_id": txt("Versicherten_ID"),
        "vorname": txt("Versicherter/Person/Vorname"),
        "nachname": txt("Versicherter/Person/Nachname"),
        "geburtsdatum": _format_egk_date(geburtsdatum),
        "geschlecht": txt("Versicherter/Person/Geschlecht"),
        "titel": txt("Versicherter/Person/Titel"),
        "vorsatzwort": txt("Versicherter/Person/Vorsatzwort"),
        "namenszusatz": txt("Versicherter/Person/Namenszusatz"),
        "strasse": txt("Versicherter/Person/StrassenAdresse/Strasse"),
        "hausnummer": txt("Versicherter/Person/StrassenAdresse/Hausnummer"),
        "plz": txt("Versicherter/Person/StrassenAdresse/Postleitzahl"),
        "ort": txt("Versicherter/Person/StrassenAdresse/Ort"),
        "wohnsitzlaendercode": txt("Versicherter/Person/StrassenAdresse/Land/Wohnsitzlaendercode"),
    }


def parse_ef_vd(raw: bytes) -> dict:
    """Parse EF.VD (insurance data) from raw bytes.

    EF.VD has a different header structure:
    - Bytes 0-1: start offset of general insurance data
    - Bytes 2-3: end offset of general insurance data
    - Bytes 4-5: start offset of protected insurance data
    - Bytes 6-7: end offset of protected insurance data

    Returns dict with keys: kostentraeger_name, kostentraeger_kennung,
    versicherungsschutz_beginn, versicherungsschutz_ende, versichertenart.
    """
    if len(raw) < 8:
        raise EgkParseError("EF.VD data too short")

    start_general = (raw[0] << 8) | raw[1]
    end_general = (raw[2] << 8) | raw[3]

    # End offsets are INCLUSIVE per gematik spec — use end+1 for Python slice
    if start_general >= end_general or (end_general + 1) > len(raw):
        raise EgkParseError(
            f"Invalid EF.VD offset values: start={start_general} "
            f"end={end_general} raw_len={len(raw)}"
        )

    general_data = raw[start_general:end_general + 1]

    try:
        # Use zlib with wbits=31 (gzip format) + zero-padding for robustness.
        # gzip.decompress() is too strict and fails if even 1 byte is missing
        # from the gzip trailer.  This approach is used by python-healthcard
        # and python-egk reference implementations.
        padded = general_data + b"\x00" * 16
        xml_bytes = zlib.decompress(padded, 15 + 16)
    except Exception as e:
        raise EgkParseError(f"EF.VD gzip decompression failed: {e}") from e

    root = etree.fromstring(xml_bytes)

    ns_uri = root.nsmap.get(None, "")
    ns = {"v": ns_uri} if ns_uri else {}
    prefix = "v:" if ns else ""

    def txt(path: str) -> str:
        parts = path.strip("/").split("/")
        xpath = "/".join(f"{prefix}{p}" for p in parts)
        xpath = f"//{xpath}"
        try:
            elements = root.xpath(xpath, namespaces=ns)
            if elements:
                return elements[0].text.strip() if elements[0].text else ""
        except etree.XPathEvalError:
            pass
        return ""

    beginn = txt("Versicherungsschutz/Beginn")
    ende = txt("Versicherungsschutz/Ende")

    return {
        "kostentraeger_name": txt("Versicherungsschutz/Kostentraeger/Name"),
        "kostentraeger_kennung": txt("Versicherungsschutz/Kostentraeger/Kostentraegerkennung"),
        "versicherungsschutz_beginn": beginn,
        "versicherungsschutz_ende": ende,
        "versichertenart": txt("Zusatzinfos/ZusatzinfosGKV/Versichertenart"),
    }


def build_patient_data(ef_pd_raw: bytes, ef_vd_raw: bytes) -> PatientData:
    """Parse both EF.PD and EF.VD and build a unified PatientData object."""
    pd = parse_ef_pd(ef_pd_raw)
    vd = parse_ef_vd(ef_vd_raw)

    gueltig_bis = ""
    ende = vd.get("versicherungsschutz_ende", "")
    if ende and len(ende) >= 7:
        # Convert YYYY-MM-DD or YYYY-MM to MM/YYYY
        parts = ende.split("-")
        if len(parts) >= 2:
            gueltig_bis = f"{parts[1]}/{parts[0]}"

    return PatientData(
        vorname=pd.get("vorname", ""),
        nachname=pd.get("nachname", ""),
        geburtsdatum=pd.get("geburtsdatum", ""),
        titel=pd.get("titel", ""),
        namenszusatz=pd.get("namenszusatz", ""),
        vorsatzwort=pd.get("vorsatzwort", ""),
        geschlecht=pd.get("geschlecht", ""),
        strasse=pd.get("strasse", ""),
        hausnummer=pd.get("hausnummer", ""),
        plz=pd.get("plz", ""),
        ort=pd.get("ort", ""),
        wohnsitzlaendercode=pd.get("wohnsitzlaendercode", "D"),
        krankenkasse_name=vd.get("kostentraeger_name", ""),
        krankenkassen_nummer=vd.get("kostentraeger_kennung", ""),
        versichertennummer=pd.get("versicherten_id", ""),
        versichertenstatus=vd.get("versichertenart", ""),
        versichertenart=vd.get("versichertenart", ""),
        gueltig_bis=gueltig_bis,
        card_type="eGK",
    )
