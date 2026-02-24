"""eGK (elektronische Gesundheitskarte) reader via PC/SC.

Reads EF.PD (personal data) and EF.VD (insurance data) from eGK smartcards
using APDU commands via the pyscard library.

Supports eGK Generation 1, 1+, 2, 2+, and 2.1 by trying multiple strategies
for application selection and file reading.

Based on the gematik eGK specification, python-healthcard reference,
and a proven FileMaker MBS implementation.
"""

from __future__ import annotations

import logging

from kvk_reader.card.models import PatientData
from kvk_reader.card.egk_xml_parser import build_patient_data, EgkParseError

log = logging.getLogger(__name__)


class EgkReadError(Exception):
    """Raised when eGK card reading fails."""


# ---------------------------------------------------------------------------
# Application identifiers (AID)
# ---------------------------------------------------------------------------

# Root MF — D27600014480 00 (gematik root)
_SELECT_MF = [0x00, 0xA4, 0x04, 0x0C, 0x07,
              0xD2, 0x76, 0x00, 0x01, 0x44, 0x80, 0x00]

# HCA (Health Care Application) — D27600000102
_SELECT_HCA = [0x00, 0xA4, 0x04, 0x0C, 0x06,
               0xD2, 0x76, 0x00, 0x00, 0x01, 0x02]

# Alternative: select DF.HCA by file ID (eGK G1)
_SELECT_DF_HCA = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0xD0, 0x00]

# EF file IDs and SFIs
_SFI_PD = 0x01
_SFI_VD = 0x02
_FID_EF_PD = [0xD0, 0x01]  # File ID for EF.PD
_FID_EF_VD = [0xD0, 0x02]  # File ID for EF.VD

# Maximum Le per READ BINARY — Omnikey readers can't handle more than ~98 bytes.
_MAX_LE = 98


def _sw_ok(sw1: int, sw2: int) -> bool:
    """Check APDU status word. Returns True on success."""
    return (sw1 == 0x90 and sw2 == 0x00) or sw1 == 0x61


def _select_ef(connection, file_id: list) -> bool:
    """Select an EF by file ID. Returns True on success."""
    apdu = [0x00, 0xA4, 0x02, 0x0C, 0x02] + file_id
    data, sw1, sw2 = connection.transmit(apdu)
    ok = _sw_ok(sw1, sw2)
    log.info("SELECT EF %02X%02X → SW=%02X%02X %s",
             file_id[0], file_id[1], sw1, sw2, "OK" if ok else "FEHLER")
    return ok


def _read_binary_plain(connection, offset: int, length: int) -> bytes:
    """Read binary from the currently selected file using plain offset.

    Reads in chunks of _MAX_LE bytes to stay within reader limits.
    """
    result = b""
    remaining = length
    current_offset = offset

    while remaining > 0:
        read_len = min(remaining, _MAX_LE)
        p1 = (current_offset >> 8) & 0x7F
        p2 = current_offset & 0xFF

        apdu = [0x00, 0xB0, p1, p2, read_len]
        data, sw1, sw2 = connection.transmit(apdu)

        if not _sw_ok(sw1, sw2):
            raise EgkReadError(
                f"READ BINARY offset={current_offset}: "
                f"SW1=0x{sw1:02X}, SW2=0x{sw2:02X}"
            )

        result += bytes(data)
        current_offset += len(data)
        remaining -= len(data)

        if len(data) == 0:
            break

    return result


def _read_binary_sfi(connection, sfi: int, length: int) -> bytes:
    """Read binary using SFI (Short File Identifier) for implicit file selection.

    The SFI is encoded in P1 as: P1 = 0x80 | SFI (bits 4-0).
    This implicitly selects the file AND reads the first chunk.
    Subsequent reads use plain offset addressing.
    """
    # First read: SFI-encoded P1, offset 0
    read_len = min(length, _MAX_LE)
    p1 = 0x80 | sfi  # correct: bit7=1, bits4-0=SFI value
    p2 = 0x00

    apdu = [0x00, 0xB0, p1, p2, read_len]
    data, sw1, sw2 = connection.transmit(apdu)

    if not _sw_ok(sw1, sw2):
        raise EgkReadError(
            f"READ BINARY SFI={sfi} (P1=0x{p1:02X}): "
            f"SW1=0x{sw1:02X}, SW2=0x{sw2:02X}"
        )

    result = bytes(data)

    # Subsequent reads use plain offset (file is now implicitly selected)
    if len(result) < length:
        rest = _read_binary_plain(connection, offset=len(result), length=length - len(result))
        result += rest

    return result


def _read_ef(connection, sfi: int, file_id: list, length: int) -> bytes:
    """Read an EF, trying SFI first, then SELECT FILE + plain READ BINARY.

    Some eGK generations don't support SFI-based READ BINARY and require
    explicit file selection first.
    """
    # Strategy 1: SFI-based READ BINARY (eGK G2/G2+/G2.1)
    try:
        data = _read_binary_sfi(connection, sfi, length)
        log.info("EF via SFI=%d (P1=0x%02X) gelesen: %d bytes",
                 sfi, 0x80 | sfi, len(data))
        return data
    except EgkReadError as e:
        log.info("SFI-Read fehlgeschlagen: %s, versuche SELECT FILE...", e)

    # Strategy 2: Explicit SELECT FILE + plain READ BINARY (eGK G1)
    if not _select_ef(connection, file_id):
        raise EgkReadError(
            f"SELECT EF {file_id[0]:02X}{file_id[1]:02X} fehlgeschlagen"
        )

    data = _read_binary_plain(connection, offset=0, length=length)
    log.info("EF via File-ID %02X%02X gelesen: %d bytes",
             file_id[0], file_id[1], len(data))
    return data


def _select_application(connection) -> None:
    """Select the HCA application on the eGK.

    Tries multiple strategies for different eGK generations:
    1. SELECT HCA directly (works on most cards)
    2. SELECT MF → SELECT HCA (standard G2/G2+)
    3. SELECT DF.HCA by file ID (G1 fallback)

    Raises:
        EgkReadError: If no selection strategy succeeds.
    """
    errors = []

    # Strategy 1: SELECT HCA directly (proven in FileMaker, works on G2/G2.1)
    log.info("eGK: Versuche SELECT HCA direkt...")
    data, sw1, sw2 = connection.transmit(_SELECT_HCA)
    if _sw_ok(sw1, sw2):
        log.info("eGK: HCA selektiert via direkt SELECT")
        return
    errors.append(f"SELECT HCA direkt: SW={sw1:02X}{sw2:02X}")

    # Strategy 2: MF → HCA (standard for eGK G2/G2+)
    log.info("eGK: Versuche SELECT MF → SELECT HCA...")
    data, sw1, sw2 = connection.transmit(_SELECT_MF)
    if _sw_ok(sw1, sw2):
        data, sw1, sw2 = connection.transmit(_SELECT_HCA)
        if _sw_ok(sw1, sw2):
            log.info("eGK: HCA selektiert via MF → HCA")
            return
        errors.append(f"SELECT HCA nach MF: SW={sw1:02X}{sw2:02X}")
    else:
        errors.append(f"SELECT MF: SW={sw1:02X}{sw2:02X}")

    # Strategy 3: SELECT DF.HCA by file ID (eGK G1)
    log.info("eGK: Versuche SELECT DF.HCA (File ID)...")
    data, sw1, sw2 = connection.transmit(_SELECT_DF_HCA)
    if _sw_ok(sw1, sw2):
        log.info("eGK: HCA selektiert via DF File ID")
        return
    errors.append(f"SELECT DF.HCA: SW={sw1:02X}{sw2:02X}")

    raise EgkReadError(
        f"eGK: Keine SELECT-Strategie erfolgreich.\n"
        f"Details: {'; '.join(errors)}"
    )


def read_egk(connection) -> PatientData:
    """Read patient data from an eGK smartcard.

    Follows the proven reading flow:
    1. SELECT HCA application
    2. READ BINARY with SFI=1 to get EF.PD header (2 bytes)
    3. READ BINARY (plain offset) to get rest of EF.PD data
    4. READ BINARY with SFI=2 to get EF.VD header (8 bytes)
    5. READ BINARY (plain offset) to get rest of EF.VD data

    Args:
        connection: pyscard connection object (already connected to the card).

    Returns:
        PatientData populated from eGK card data.

    Raises:
        EgkReadError: If card communication fails.
        EgkParseError: If data parsing fails.
    """
    # Select HCA application (tries multiple strategies)
    _select_application(connection)

    # --- EF.PD ---
    # Read header (2 bytes) via SFI=1 → implicitly selects EF.PD
    log.info("eGK: Lese EF.PD...")
    pd_header = _read_ef(connection, _SFI_PD, _FID_EF_PD, length=2)
    pd_length = (pd_header[0] << 8) | pd_header[1]
    log.info("EF.PD komprimierte Länge: %d bytes", pd_length)

    if pd_length == 0 or pd_length > 5000:
        raise EgkReadError(
            f"EF.PD Länge ungültig: {pd_length} bytes "
            f"(Header: {pd_header.hex()})"
        )

    # Read compressed data starting at offset 2 (file already selected by SFI)
    ef_pd_compressed = _read_binary_plain(connection, offset=2, length=pd_length)
    log.info("EF.PD komprimierte Daten gelesen: %d bytes", len(ef_pd_compressed))

    # Combine header + compressed data
    ef_pd_raw = pd_header + ef_pd_compressed

    # --- EF.VD ---
    # Read header (8 bytes) via SFI=2 → implicitly selects EF.VD
    # Header structure:
    #   Bytes 0-1: offset start of general VD data
    #   Bytes 2-3: offset end of general VD data
    #   Bytes 4-5: offset start of protected VD data (GVD)
    #   Bytes 6-7: offset end of protected VD data (GVD)
    log.info("eGK: Lese EF.VD...")
    vd_header = _read_ef(connection, _SFI_VD, _FID_EF_VD, length=8)

    start_general = (vd_header[0] << 8) | vd_header[1]
    end_general = (vd_header[2] << 8) | vd_header[3]
    start_protected = (vd_header[4] << 8) | vd_header[5]
    end_protected = (vd_header[6] << 8) | vd_header[7]

    log.info("EF.VD Header: startVD=%d endVD=%d startGVD=%d endGVD=%d",
             start_general, end_general, start_protected, end_protected)

    # End offsets are INCLUSIVE (gematik spec), so file size = max_end + 1
    # Verified against working FileMaker MBS implementation
    ef_vd_file_size = max(end_general, end_protected) + 1

    if ef_vd_file_size <= 8 or ef_vd_file_size > 5000:
        raise EgkReadError(
            f"EF.VD Länge ungültig: {ef_vd_file_size} bytes "
            f"(Header: {vd_header.hex()})"
        )

    # Read remaining data after the 8-byte header (file already selected by SFI)
    vd_data_length = ef_vd_file_size - 8
    if vd_data_length > 0:
        ef_vd_rest = _read_binary_plain(connection, offset=8, length=vd_data_length)
        ef_vd_raw = vd_header + ef_vd_rest
    else:
        ef_vd_raw = vd_header

    log.info("EF.VD gelesen: %d bytes", len(ef_vd_raw))

    return build_patient_data(ef_pd_raw, ef_vd_raw)
