"""Card type detection and reader management.

Uses pyscard for eGK (processor cards) via PC/SC,
and CT-API for KVK/PKV (memory cards) via vendor DLL.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from kvk_reader.card.models import PatientData

log = logging.getLogger(__name__)

# Known eGK ATR patterns (partial matches on first bytes)
_EGK_ATR_PREFIXES = [
    [0x3B, 0xDD],  # eGK G2
    [0x3B, 0xDE],  # eGK G2 variant
    [0x3B, 0x16],  # eGK G1
    [0x3B, 0x80],  # Various processor cards
]

# SLE4428/SLE4442 memory card ATRs
_MEMORY_CARD_ATRS = [
    [0x3B, 0x04, 0x92, 0x23, 0x10, 0x91],  # SLE4428
    [0x3B, 0x04, 0xA2, 0x13, 0x10, 0x91],  # SLE4442
]


class CardType:
    EGK = "eGK"
    KVK = "KVK"
    UNKNOWN = "unknown"


def detect_card_type(atr: list) -> str:
    """Detect card type from ATR (Answer to Reset).

    Args:
        atr: ATR bytes as list of ints.

    Returns:
        CardType constant: "eGK", "KVK", or "unknown".
    """
    if not atr:
        return CardType.UNKNOWN

    # Check for memory card ATR patterns
    for pattern in _MEMORY_CARD_ATRS:
        if atr[: len(pattern)] == pattern:
            return CardType.KVK

    # Check for eGK processor card patterns
    for prefix in _EGK_ATR_PREFIXES:
        if atr[: len(prefix)] == prefix:
            return CardType.EGK

    # Heuristic: long ATR → likely processor card (eGK)
    if len(atr) > 6:
        return CardType.EGK

    # Short ATR → likely memory card
    if len(atr) <= 6:
        return CardType.KVK

    return CardType.UNKNOWN


def read_card_pcsc(connection, card_type: str) -> PatientData:
    """Read a card using PC/SC (pyscard) with the appropriate reader module.

    Args:
        connection: pyscard connection object.
        card_type: CardType constant ("eGK" or "KVK").

    Returns:
        PatientData from the card.
    """
    if card_type == CardType.EGK:
        from kvk_reader.card.egk_reader import read_egk
        return read_egk(connection)
    elif card_type == CardType.KVK:
        from kvk_reader.card.kvk_reader import read_kvk_pcsc
        return read_kvk_pcsc(connection)
    else:
        raise ValueError(f"Unbekannter Kartentyp: {card_type}")


class CardReaderWorker:
    """Manages card reader interaction.

    Supports two modes:
    - PC/SC for eGK (and KVK fallback on compatible readers)
    - CT-API for KVK/PKV memory cards (preferred for memory cards)

    Designed to be called from a QThread worker.
    """

    def __init__(self, ct_api_dll: str = "", ct_api_pn: int = 1):
        """Initialize the card reader worker.

        Args:
            ct_api_dll: Path to CT-API DLL for KVK reading.
                       Empty string = use PC/SC only.
            ct_api_pn: CT-API port number (vendor-specific, usually 1).
        """
        self._readers: list = []
        self._ct_api_dll = ct_api_dll
        self._ct_api_pn = ct_api_pn

    def discover_readers(self) -> List[str]:
        """List available PC/SC card readers.

        Returns:
            List of reader name strings.
        """
        try:
            from smartcard.System import readers
            self._readers = readers()
            return [str(r) for r in self._readers]
        except Exception as e:
            log.error("Kartenleser-Suche fehlgeschlagen: %s", e)
            return []

    def read_from_reader(self, reader_index: int = 0) -> PatientData:
        """Read a card from the specified reader.

        For eGK: Always uses PC/SC.
        For KVK: Uses CT-API if DLL is configured, otherwise PC/SC fallback.

        Args:
            reader_index: Index into the list from discover_readers().

        Returns:
            PatientData from the inserted card.

        Raises:
            RuntimeError: If no reader found, no card, or read fails.
        """
        from smartcard.System import readers
        from smartcard.Exceptions import NoCardException, CardConnectionException

        available = readers()
        if not available:
            raise RuntimeError("Kein Kartenleser gefunden")

        if reader_index >= len(available):
            raise RuntimeError(f"Kartenleser-Index {reader_index} ungültig")

        reader = available[reader_index]
        log.info("Verwende Leser: %s", reader)

        try:
            connection = reader.createConnection()
            connection.connect()
        except NoCardException:
            # No card via PC/SC — memory cards (KVK) are often invisible
            reader_name = str(reader)
            if self._is_omnikey_reader(reader_name):
                log.info("Keine Karte über PC/SC, versuche Omnikey Sync API...")
                return self._read_kvk_omnikey(reader_name)
            if self._ct_api_dll:
                log.info("Keine Karte über PC/SC, versuche CT-API für KVK...")
                return self._read_kvk_ctapi()
            raise RuntimeError("Keine Karte eingesteckt")
        except CardConnectionException as e:
            # Connection failed — typical for memory cards (error 0x80100066)
            # Try Omnikey Sync API first (designed for memory cards),
            # then CT-API as last resort
            reader_name = str(reader)
            if self._is_omnikey_reader(reader_name):
                log.info("PC/SC fehlgeschlagen (%s), versuche Omnikey Sync API...", e)
                return self._read_kvk_omnikey(reader_name)
            if self._ct_api_dll:
                log.info("PC/SC fehlgeschlagen, versuche CT-API: %s", e)
                return self._read_kvk_ctapi()
            raise RuntimeError(f"Verbindung zum Kartenleser fehlgeschlagen: {e}")

        try:
            atr = connection.getATR()
            log.info("Karten-ATR: %s", " ".join(f"{b:02X}" for b in atr))

            card_type = detect_card_type(atr)
            log.info("Erkannter Kartentyp: %s", card_type)

            if card_type == CardType.KVK:
                # KVK detected — choose best backend
                reader_name = str(reader)
                if self._is_omnikey_reader(reader_name):
                    connection.disconnect()
                    log.info("KVK erkannt + Omnikey-Leser, verwende Sync API...")
                    return self._read_kvk_omnikey(reader_name)
                if self._ct_api_dll:
                    connection.disconnect()
                    log.info("KVK erkannt, wechsle zu CT-API...")
                    return self._read_kvk_ctapi()

            if card_type == CardType.UNKNOWN:
                # Try eGK first, then KVK
                reader_name = str(reader)
                try:
                    return read_card_pcsc(connection, CardType.EGK)
                except Exception:
                    if self._is_omnikey_reader(reader_name):
                        connection.disconnect()
                        return self._read_kvk_omnikey(reader_name)
                    if self._ct_api_dll:
                        connection.disconnect()
                        return self._read_kvk_ctapi()
                    return read_card_pcsc(connection, CardType.KVK)

            return read_card_pcsc(connection, card_type)
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass

    def read_kvk_only(self) -> PatientData:
        """Read KVK/PKV card only (no eGK).

        Uses CT-API if configured, otherwise PC/SC.

        Returns:
            PatientData from KVK card.
        """
        if self._ct_api_dll:
            return self._read_kvk_ctapi()
        else:
            # Fall back to PC/SC
            from smartcard.System import readers
            available = readers()
            if not available:
                raise RuntimeError("Kein Kartenleser gefunden")
            connection = available[0].createConnection()
            connection.connect()
            try:
                from kvk_reader.card.kvk_reader import read_kvk_pcsc
                return read_kvk_pcsc(connection)
            finally:
                connection.disconnect()

    @staticmethod
    def _is_omnikey_reader(reader_name: str) -> bool:
        """Check if a reader is an HID Omnikey device."""
        from kvk_reader.card.omnikey_sync import is_omnikey_reader, is_omnikey_available
        return is_omnikey_reader(reader_name) and is_omnikey_available()

    def _read_kvk_omnikey(self, reader_name: str) -> PatientData:
        """Read KVK via Omnikey Sync API.

        Returns:
            PatientData from KVK card.

        Raises:
            RuntimeError: If Omnikey read fails.
        """
        from kvk_reader.card.kvk_reader import read_kvk_omnikey, KvkReadError
        try:
            return read_kvk_omnikey(reader_name)
        except KvkReadError as e:
            raise RuntimeError(str(e)) from e

    def _read_kvk_ctapi(self) -> PatientData:
        """Read KVK via CT-API.

        Returns:
            PatientData from KVK card.

        Raises:
            RuntimeError: If CT-API read fails.
        """
        from kvk_reader.card.kvk_reader import read_kvk_ctapi, KvkReadError
        try:
            return read_kvk_ctapi(
                dll_path=self._ct_api_dll,
                ctn=1,
                pn=self._ct_api_pn,
            )
        except KvkReadError as e:
            raise RuntimeError(str(e)) from e
