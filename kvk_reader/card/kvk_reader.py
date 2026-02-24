"""KVK/PKV memory card reader.

Reads data from KVK (Krankenversichertenkarte) and PKV memory cards
(SLE4428 / SLE4442 chips).

Supports two backends:
- CT-API (preferred): Uses vendor-specific DLL via ctypes.
  Reliable for synchronous memory cards on all readers.
- PC/SC (fallback): Uses pyscard. Only works on readers that
  natively support synchronous cards via PC/SC (e.g. Cherry ST-2100).
"""

from __future__ import annotations

import logging

from kvk_reader.card.models import PatientData
from kvk_reader.card.kvk_tlv_parser import parse_kvk_data, KvkParseError

log = logging.getLogger(__name__)


class KvkReadError(Exception):
    """Raised when KVK card reading fails."""


# ---------- CT-API backend ----------

def read_kvk_ctapi(dll_path: str, ctn: int = 1, pn: int = 1) -> PatientData:
    """Read patient data from KVK/PKV card via CT-API.

    This is the preferred method for reading memory cards (SLE4428).

    Args:
        dll_path: Path to vendor CT-API DLL (e.g. "ctpcsc32.dll").
        ctn: Logical card terminal number.
        pn: Physical port number (vendor-specific, usually 1 for USB).

    Returns:
        PatientData populated from KVK card data.

    Raises:
        KvkReadError: If card communication fails.
        KvkParseError: If data parsing fails.
    """
    from kvk_reader.card.ct_api import CTAPI, CTAPIError, CTAPINotFoundError

    try:
        ct = CTAPI(dll_path)
    except CTAPINotFoundError as e:
        raise KvkReadError(str(e)) from e

    log.info("CT-API: DLL=%s, ctn=%d, pn=%d", dll_path, ctn, pn)

    try:
        ct.init(ctn, pn)
        log.info("CT_init erfolgreich")
        try:
            atr = ct.request_icc(ctn)
            log.info("REQUEST ICC erfolgreich, ATR=%s",
                     " ".join(f"{b:02X}" for b in atr) if atr else "(leer)")
            try:
                raw_data = ct.read_card_data(ctn)
            finally:
                try:
                    ct.eject_icc(ctn)
                except Exception:
                    pass
        finally:
            try:
                ct.close(ctn)
            except Exception:
                pass
    except CTAPIError as e:
        raise KvkReadError(f"Kartenleser-Kommunikation fehlgeschlagen: {e}") from e
    except RuntimeError as e:
        raise KvkReadError(str(e)) from e

    if not raw_data:
        raise KvkReadError("Keine Daten von Karte gelesen")

    log.info("CT-API: %d Bytes von KVK-Karte gelesen", len(raw_data))
    hex_preview = " ".join(f"{b:02X}" for b in raw_data[:64])
    log.info("CT-API: Erste 64 Bytes: %s", hex_preview)
    return parse_kvk_data(raw_data)


# ---------- PC/SC backend (fallback) ----------

# KVK Application ID
_KVK_AID = [0xD2, 0x76, 0x00, 0x00, 0x01, 0x01]
_KVK_AID_ALT = [0xD2, 0x80, 0x00, 0x00, 0x01, 0x01]


def read_kvk_pcsc(connection) -> PatientData:
    """Read patient data from a KVK/PKV memory card via PC/SC.

    Fallback for readers that support synchronous cards natively
    via PC/SC (e.g. Cherry ST-2100).

    Args:
        connection: pyscard connection object (already connected).

    Returns:
        PatientData populated from KVK card data.

    Raises:
        KvkReadError: If card communication fails.
        KvkParseError: If data parsing fails.
    """
    # Try to SELECT the KVK application
    select_apdu = [0x00, 0xA4, 0x04, 0x00, len(_KVK_AID)] + _KVK_AID
    data, sw1, sw2 = connection.transmit(select_apdu)

    if sw1 != 0x90 or sw2 != 0x00:
        # Try alternative AID
        select_apdu = [0x00, 0xA4, 0x04, 0x00, len(_KVK_AID_ALT)] + _KVK_AID_ALT
        data, sw1, sw2 = connection.transmit(select_apdu)
        if sw1 != 0x90 or sw2 != 0x00:
            raise KvkReadError(
                f"KVK-Anwendung nicht gefunden: SW1=0x{sw1:02X}, SW2=0x{sw2:02X}"
            )

    # Read the entire data area
    raw_data = b""
    offset = 0
    total_len = 256

    while offset < total_len:
        read_len = min(total_len - offset, 252)
        p1 = (offset >> 8) & 0x7F
        p2 = offset & 0xFF
        read_apdu = [0x00, 0xB0, p1, p2, read_len]

        data, sw1, sw2 = connection.transmit(read_apdu)

        if sw1 == 0x6C:
            # Wrong Le: SW2 contains the correct length
            read_apdu[-1] = sw2
            data, sw1, sw2 = connection.transmit(read_apdu)

        if sw1 == 0x90 and sw2 == 0x00:
            raw_data += bytes(data)
            offset += len(data)
        elif sw1 == 0x62 or sw1 == 0x63:
            raw_data += bytes(data)
            break
        else:
            if raw_data:
                break
            raise KvkReadError(
                f"READ BINARY fehlgeschlagen: SW1=0x{sw1:02X}, SW2=0x{sw2:02X}"
            )

    if not raw_data:
        raise KvkReadError("Keine Daten von Karte gelesen")

    log.info("PC/SC: %d Bytes von KVK-Karte gelesen", len(raw_data))
    return parse_kvk_data(raw_data)


# ---------- Omnikey Sync API backend ----------

def read_kvk_omnikey(reader_name: str) -> PatientData:
    """Read patient data from KVK/PKV card via Omnikey Sync API.

    Uses the HID Omnikey proprietary scardsyn.dll to read all 1024 bytes
    from an SLE4428 memory card in a single call.

    Args:
        reader_name: PC/SC reader name (e.g. "HID Global OMNIKEY 3x21 ...").

    Returns:
        PatientData populated from KVK card data.

    Raises:
        KvkReadError: If card communication fails.
        KvkParseError: If data parsing fails.
    """
    from kvk_reader.card.omnikey_sync import read_sle4428, OmnikeySyncError

    try:
        raw_data = read_sle4428(reader_name)
    except OmnikeySyncError as e:
        raise KvkReadError(f"Omnikey Sync API: {e}") from e
    except OSError as e:
        raise KvkReadError(f"Omnikey DLL nicht verfügbar: {e}") from e

    if not raw_data:
        raise KvkReadError("Keine Daten von Karte gelesen (Omnikey)")

    log.info("Omnikey: %d Bytes von KVK-Karte gelesen", len(raw_data))
    return parse_kvk_data(raw_data)


# ---------- Unified read function ----------

def read_kvk(connection=None, dll_path: str = "", ctn: int = 1, pn: int = 1) -> PatientData:
    """Read patient data from KVK/PKV card.

    Tries CT-API first (if dll_path given), falls back to PC/SC.

    Args:
        connection: pyscard connection (for PC/SC fallback).
        dll_path: Path to CT-API DLL (preferred method).
        ctn: CT-API terminal number.
        pn: CT-API port number.

    Returns:
        PatientData from KVK card.
    """
    if dll_path:
        return read_kvk_ctapi(dll_path, ctn, pn)
    elif connection is not None:
        return read_kvk_pcsc(connection)
    else:
        raise KvkReadError(
            "Kein Leseverfahren verfügbar: Weder CT-API DLL noch PC/SC-Verbindung angegeben"
        )
