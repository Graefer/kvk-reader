"""HID Omnikey Synchronous Card API wrapper using ctypes.

Reads SLE4428 and SLE4442 memory cards (KVK/PKV) via HID Omnikey card
readers using the proprietary Sync API DLL (scardsyn.dll / scardsynx64.dll).

The Omnikey Sync API uses standard WinSCard (PC/SC) for the connection,
plus a proprietary DLL for synchronous card operations:
- SCard3WBPReadData for SLE4428 (3-Wire Bus, 1024 bytes)
- SCard2WBPReadData for SLE4442 (2-Wire Bus, 256 bytes)

Card type is auto-detected via ATR byte[2]:
- 0x92 or 0x02 → SLE4428 (3-Wire, 1024 bytes)
- 0xA2         → SLE4442 (2-Wire, 256 bytes)

Reading does NOT require PIN presentation.

The DLL is installed by the HID Omnikey driver and resides in the
system PATH (typically C:\\Windows\\System32\\scardsyn.dll).
"""

from __future__ import annotations

import ctypes
import logging
import platform
import sys

log = logging.getLogger(__name__)

# --- Error codes from ok.h ---
OKERR_OK = 0
OKERR_INSUFFICIENT_PRIV = 0x81100000
OKERR_PW_WRONG = 0x81100001
OKERR_PW_LOCKED = 0x81100002
OKERR_COMMUNICATE = 0x81300001
OKERR_BUFFER_OVERFLOW = 0x81300003
OKERR_TIMEOUT = 0x81300004
OKERR_ILLEGAL_ARGUMENT = 0x81300006
OKERR_INVALID_HANDLE = 0x81300009
OKERR_GENERAL_FAILURE = 0x8130000A
OKERR_CARD_NOT_POWERED = 0x81F0000A
OKERR_ILLEGAL_CARDTYPE = 0x81F0000B
OKERR_CARD_NOT_INSERTED = 0x81F0000C

_ERROR_MESSAGES = {
    OKERR_INSUFFICIENT_PRIV: "PIN nicht eingegeben",
    OKERR_PW_WRONG: "Falscher PIN",
    OKERR_PW_LOCKED: "PIN gesperrt",
    OKERR_COMMUNICATE: "Kommunikationsfehler mit Karte",
    OKERR_BUFFER_OVERFLOW: "Puffer-Überlauf",
    OKERR_TIMEOUT: "Zeitüberschreitung",
    OKERR_ILLEGAL_ARGUMENT: "Ungültiges Argument",
    OKERR_INVALID_HANDLE: "Ungültiges Handle",
    OKERR_GENERAL_FAILURE: "Allgemeiner Fehler",
    OKERR_CARD_NOT_POWERED: "Karte nicht aktiviert",
    OKERR_ILLEGAL_CARDTYPE: "Falscher Kartentyp",
    OKERR_CARD_NOT_INSERTED: "Keine Karte eingesteckt",
}

# --- WinSCard constants ---
SCARD_SCOPE_USER = 0
SCARD_SHARE_SHARED = 2
SCARD_SHARE_DIRECT = 3
SCARD_PROTOCOL_UNDEFINED = 0x0000
SCARD_PROTOCOL_T0 = 0x0001
SCARD_PROTOCOL_T1 = 0x0002
SCARD_PROTOCOL_RAW = 0x00010000
SCARD_LEAVE_CARD = 0
SCARD_S_SUCCESS = 0
SCARD_ATTR_ATR_STRING = 0x00090303

# Common SCard error codes for better logging
_SCARD_ERRORS = {
    0x80100001: "SCARD_F_INTERNAL_ERROR",
    0x80100002: "SCARD_E_CANCELLED",
    0x80100003: "SCARD_E_INVALID_HANDLE",
    0x80100004: "SCARD_E_INVALID_PARAMETER",
    0x80100009: "SCARD_E_UNKNOWN_READER",
    0x8010000A: "SCARD_E_TIMEOUT",
    0x8010000B: "SCARD_E_SHARING_VIOLATION",
    0x8010000C: "SCARD_E_NO_SMARTCARD",
    0x8010000F: "SCARD_E_PROTO_MISMATCH",
    0x80100010: "SCARD_E_NOT_READY",
    0x80100017: "SCARD_E_READER_UNAVAILABLE",
    0x80100019: "SCARD_E_UNSUPPORTED_FEATURE",
    0x80100066: "SCARD_W_UNRESPONSIVE_CARD",
    0x80100069: "SCARD_W_REMOVED_CARD",
}

# --- Card type constants ---
SLE4428_SIZE = 1024    # 3-Wire Bus Protocol
SLE4442_SIZE = 256     # 2-Wire Bus Protocol


class OmnikeySyncError(Exception):
    """Raised when Omnikey Sync API call fails."""


def _format_error(code: int) -> str:
    """Format error code to human-readable message."""
    msg = _ERROR_MESSAGES.get(code, "Unbekannter Fehler")
    return f"{msg} (0x{code:08X})"


def is_omnikey_available() -> bool:
    """Check if the Omnikey Sync API DLL can be loaded.

    Returns:
        True if scardsyn.dll (or scardsynx64.dll) is available.
    """
    if sys.platform != "win32":
        return False
    try:
        _load_scardsyn()
        return True
    except OSError:
        return False


def _load_scardsyn():
    """Load the Omnikey Sync API DLL.

    Returns:
        ctypes.WinDLL instance.

    Raises:
        OSError: If DLL cannot be loaded.
    """
    if platform.architecture()[0] == "64bit":
        dll_name = "scardsynx64.dll"
    else:
        dll_name = "scardsyn.dll"

    return ctypes.WinDLL(dll_name)


def _load_winscard():
    """Load the Windows Smart Card API DLL.

    Returns:
        ctypes.WinDLL instance.

    Raises:
        OSError: If DLL cannot be loaded.
    """
    return ctypes.WinDLL("winscard.dll")


def _setup_winscard(winscard):
    """Set up function signatures for WinSCard API."""
    DWORD = ctypes.c_ulong
    HANDLE = ctypes.c_void_p

    winscard.SCardEstablishContext.restype = DWORD
    winscard.SCardEstablishContext.argtypes = [
        DWORD,                       # dwScope
        ctypes.c_void_p,             # pvReserved1
        ctypes.c_void_p,             # pvReserved2
        ctypes.POINTER(HANDLE),      # phContext
    ]

    winscard.SCardConnectA.restype = DWORD
    winscard.SCardConnectA.argtypes = [
        HANDLE,                      # hContext
        ctypes.c_char_p,             # szReader
        DWORD,                       # dwShareMode
        DWORD,                       # dwPreferredProtocols
        ctypes.POINTER(HANDLE),      # phCard
        ctypes.POINTER(DWORD),       # pdwActiveProtocol
    ]

    winscard.SCardGetAttrib.restype = DWORD
    winscard.SCardGetAttrib.argtypes = [
        HANDLE,                             # hCard
        DWORD,                              # dwAttrId
        ctypes.POINTER(ctypes.c_ubyte),     # pbAttr
        ctypes.POINTER(DWORD),              # pcbAttrLen
    ]

    winscard.SCardDisconnect.restype = DWORD
    winscard.SCardDisconnect.argtypes = [HANDLE, DWORD]

    winscard.SCardReleaseContext.restype = DWORD
    winscard.SCardReleaseContext.argtypes = [HANDLE]


def _setup_scardsyn(scardsyn):
    """Set up function signatures for Omnikey Sync API."""
    HANDLE = ctypes.c_void_p
    DWORD = ctypes.c_ulong
    OKERR = ctypes.c_long

    # SLE4428 (3-Wire Bus Protocol)
    scardsyn.SCard3WBPReadData.restype = OKERR
    scardsyn.SCard3WBPReadData.argtypes = [
        HANDLE,                             # ulHandleCard
        DWORD,                              # ulBytesToRead
        ctypes.POINTER(ctypes.c_ubyte),     # pbReadBuffer
        DWORD,                              # ulAddress
    ]

    # SLE4442 (2-Wire Bus Protocol)
    scardsyn.SCard2WBPReadData.restype = OKERR
    scardsyn.SCard2WBPReadData.argtypes = [
        HANDLE,                             # ulHandleCard
        DWORD,                              # ulBytesToRead
        ctypes.POINTER(ctypes.c_ubyte),     # pbReadBuffer
        DWORD,                              # ulAddress
    ]


def _detect_card_type_from_atr(winscard, hCard) -> tuple[str, int]:
    """Detect SLE card type from ATR byte[2].

    Returns:
        Tuple of (card_type_name, memory_size).
        card_type_name is "SLE4428", "SLE4442", or "unknown".

    Raises:
        OmnikeySyncError: If ATR cannot be read.
    """
    DWORD = ctypes.c_ulong

    atr_buf = (ctypes.c_ubyte * 256)()
    atr_len = DWORD(256)
    rc = winscard.SCardGetAttrib(
        hCard, SCARD_ATTR_ATR_STRING, atr_buf, ctypes.byref(atr_len)
    )

    if rc != SCARD_S_SUCCESS:
        log.warning("ATR konnte nicht gelesen werden: 0x%08X", rc)
        # Default to SLE4442 (more common for KVK)
        return "SLE4442", SLE4442_SIZE

    atr_bytes = bytes(atr_buf[:atr_len.value])
    log.info("Omnikey ATR: %s", " ".join(f"{b:02X}" for b in atr_bytes))

    if len(atr_bytes) > 2:
        atr2 = atr_bytes[2]
        if atr2 == 0x92 or atr2 == 0x02:
            log.info("Kartentyp: SLE4428 (3-Wire, 1024 Bytes)")
            return "SLE4428", SLE4428_SIZE
        elif atr2 == 0xA2:
            log.info("Kartentyp: SLE4442 (2-Wire, 256 Bytes)")
            return "SLE4442", SLE4442_SIZE

    log.warning("Unbekannter ATR-Kartentyp, versuche SLE4442")
    return "SLE4442", SLE4442_SIZE


def _read_card_chunked(read_func, func_name, hCard, total_size, chunk_size) -> bytes | None:
    """Read card data in small chunks.

    Some Omnikey readers cannot read the entire card memory at once.
    This function reads in blocks of chunk_size bytes from address 0
    up to total_size.

    Args:
        read_func: ctypes function (SCard2WBPReadData or SCard3WBPReadData).
        func_name: Name for logging.
        hCard: Card handle.
        total_size: Total bytes to read (256 or 1024).
        chunk_size: Bytes per read operation (e.g. 32).

    Returns:
        Complete card data as bytes, or None on failure.
    """
    data = b""
    offset = 0

    while offset < total_size:
        bytes_to_read = min(chunk_size, total_size - offset)
        buf = (ctypes.c_ubyte * bytes_to_read)()

        okerr = read_func(hCard, bytes_to_read, buf, offset)
        if okerr != OKERR_OK:
            log.error(
                "%s fehlgeschlagen bei Offset %d: %s",
                func_name, offset, _format_error(okerr),
            )
            return None

        data += bytes(buf[:bytes_to_read])
        offset += bytes_to_read

    log.debug("%s: %d Bytes in %d-Byte-Blöcken gelesen",
              func_name, len(data), chunk_size)
    return data


def read_sync_card(reader_name: str) -> bytes:
    """Read all data from an SLE4428 or SLE4442 card via Omnikey Sync API.

    Auto-detects card type via ATR and uses the appropriate read function:
    - SLE4428: SCard3WBPReadData (1024 bytes)
    - SLE4442: SCard2WBPReadData (256 bytes)

    Args:
        reader_name: PC/SC reader name (e.g. "HID Global OMNIKEY 3x21 ...").

    Returns:
        Card data bytes (1024 for SLE4428, 256 for SLE4442).

    Raises:
        OmnikeySyncError: If any API call fails.
        OSError: If DLLs cannot be loaded.
    """
    log.info("Omnikey Sync API: Lese Karte über '%s'", reader_name)

    winscard = _load_winscard()
    scardsyn = _load_scardsyn()
    _setup_winscard(winscard)
    _setup_scardsyn(scardsyn)

    HANDLE = ctypes.c_void_p
    DWORD = ctypes.c_ulong

    # Step 1: Establish context
    hContext = HANDLE()
    rc = winscard.SCardEstablishContext(
        SCARD_SCOPE_USER, None, None, ctypes.byref(hContext)
    )
    if rc != SCARD_S_SUCCESS:
        raise OmnikeySyncError(
            f"SCardEstablishContext fehlgeschlagen: 0x{rc:08X}"
        )

    hCard = HANDLE()
    try:
        # Step 2: Connect to card — try multiple modes
        # HID Omnikey Sync API Dokumentation:
        # "dwPreferredProtocols has to be SCARD_PROTOCOL_T0 cause of
        #  our implementation" — synchrone Karten werden als T=0 abgebildet.
        # Daher SCARD_PROTOCOL_T0 ZUERST versuchen (laut Doku).
        dwActiveProtocol = DWORD(0)
        reader_bytes = reader_name.encode("ascii")

        _CONNECT_MODES = [
            ("SHARED + T0 (Omnikey-Doku)", SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0),
            ("SHARED + T0|T1", SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1),
            ("DIRECT + RAW", SCARD_SHARE_DIRECT, SCARD_PROTOCOL_RAW),
            ("DIRECT + UNDEFINED", SCARD_SHARE_DIRECT, SCARD_PROTOCOL_UNDEFINED),
        ]

        last_rc = 0
        connected = False
        for mode_name, share_mode, protocol in _CONNECT_MODES:
            dwActiveProtocol = DWORD(0)
            rc = winscard.SCardConnectA(
                hContext,
                reader_bytes,
                share_mode,
                protocol,
                ctypes.byref(hCard),
                ctypes.byref(dwActiveProtocol),
            )
            err_name = _SCARD_ERRORS.get(rc, "")
            if rc == SCARD_S_SUCCESS:
                log.info("Omnikey: Verbunden mit Modus '%s', Protokoll=0x%04X",
                         mode_name, dwActiveProtocol.value)
                connected = True
                break
            else:
                log.info("Omnikey: %s fehlgeschlagen: 0x%08X %s",
                         mode_name, rc, err_name)
                last_rc = rc

        if not connected:
            err_name = _SCARD_ERRORS.get(last_rc, "Unbekannt")
            raise OmnikeySyncError(
                f"SCardConnect fehlgeschlagen nach allen Verbindungsversuchen.\n"
                f"Letzter Fehler: 0x{last_rc:08X} ({err_name})\n"
                f"Der HID Omnikey PC/SC-Treiber muss installiert sein!\n"
                f"(Der Standard-Windows-CCID-Treiber reicht NICHT aus.)\n"
                f"Download: https://www.hidglobal.com/drivers"
            )

        # Step 3: Detect card type from ATR
        card_type, card_size = _detect_card_type_from_atr(winscard, hCard)

        # Step 4: Read card data in chunks
        # Omnikey readers require reading in small blocks,
        # not the full card memory at once.
        CHUNK_SIZE = 32  # Read 32 bytes at a time

        if card_type == "SLE4428":
            read_func = scardsyn.SCard3WBPReadData
            func_name = "SCard3WBPReadData"
        else:
            read_func = scardsyn.SCard2WBPReadData
            func_name = "SCard2WBPReadData"

        data = _read_card_chunked(
            read_func, func_name, hCard, card_size, CHUNK_SIZE,
        )

        if data is None and card_type != "SLE4428":
            # 2-Wire failed → try 3-Wire as fallback
            log.warning(
                "%s fehlgeschlagen, versuche SCard3WBPReadData...",
                func_name,
            )
            data = _read_card_chunked(
                scardsyn.SCard3WBPReadData, "SCard3WBPReadData (Fallback)",
                hCard, SLE4428_SIZE, CHUNK_SIZE,
            )
            card_size = SLE4428_SIZE

        if data is None:
            raise OmnikeySyncError(
                f"{func_name} fehlgeschlagen: Karte konnte nicht gelesen werden"
            )

        log.info("Omnikey: %d Bytes gelesen (%s)", len(data), card_type)
        hex_preview = " ".join(f"{b:02X}" for b in data[:64])
        log.info("Omnikey: Erste 64 Bytes: %s", hex_preview)

        return data

    finally:
        # Step 5: Disconnect and release
        if hCard.value:
            winscard.SCardDisconnect(hCard, SCARD_LEAVE_CARD)
        winscard.SCardReleaseContext(hContext)


# Keep old name as alias for backward compatibility
read_sle4428 = read_sync_card


def is_omnikey_reader(reader_name: str) -> bool:
    """Check if a reader name indicates an HID Omnikey device.

    Args:
        reader_name: PC/SC reader name string.

    Returns:
        True if reader appears to be an Omnikey device.
    """
    return "OMNIKEY" in reader_name.upper()
