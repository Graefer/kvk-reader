"""CT-API (Card Terminal API) wrapper using ctypes.

Provides low-level access to card terminals for reading KVK/PKV
memory cards (SLE4428) via the vendor-specific CT-API DLL.

The CT-API is the standard interface for German health insurance
card readers and consists of three functions:
- CT_init: Initialize terminal connection
- CT_data: Send/receive APDUs
- CT_close: Close terminal connection

Typical DLL names by vendor:
- Cherry ST-2052:   ctpcsc32kv.dll
- Cherry ST-2100:   ctpcsc32.dll / ctpcsc64.dll / ctcym.dll
- Omnikey:          ctomni532.dll
- Reiner SCT:       ctrsct32.dll / cjpcsc.dll
- SCM (Identiv):    ctscm32.dll
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Tuple, List

log = logging.getLogger(__name__)

# --- Return codes ---
CT_OK = 0
ERR_INVALID = -1
ERR_CT = -8
ERR_TRANS = -10
ERR_MEMORY = -11
ERR_HOST = -127
ERR_HTSI = -128

RETURN_CODES = {
    0: "OK",
    -1: "ERR_INVALID (ungültiger Parameter)",
    -8: "ERR_CT (Kartenleser-Kommunikationsfehler)",
    -10: "ERR_TRANS (Übertragungsfehler)",
    -11: "ERR_MEMORY (Speicherfehler)",
    -127: "ERR_HOST (Host-Fehler)",
    -128: "ERR_HTSI (HTSI-Fehler)",
}

# --- Address constants ---
DAD_ICC1 = 0x00  # Card in slot 1
DAD_CT = 0x01    # Card Terminal (for CT-BCS commands)
DAD_ICC2 = 0x02  # Card in slot 2
SAD_HOST = 0x02  # Host application (source)

# --- CT-BCS commands ---
# Note: REQUEST ICC must be 5 bytes (with Le=0x00) per Cherry documentation!
CMD_REQUEST_ICC = bytes([0x20, 0x12, 0x01, 0x01, 0x00])   # REQUEST ICC1, return ATR
CMD_EJECT_ICC = bytes([0x20, 0x15, 0x01, 0x00])            # EJECT ICC1
CMD_GET_STATUS = bytes([0x20, 0x13, 0x00, 0x46, 0x00])     # GET STATUS all ICCs


class CTAPIError(Exception):
    """Raised when a CT-API function returns an error code."""

    def __init__(self, function: str, return_code: int):
        self.function = function
        self.return_code = return_code
        msg = RETURN_CODES.get(return_code, f"Unbekannter Fehler ({return_code})")
        super().__init__(f"{function} fehlgeschlagen: {msg}")


class CTAPINotFoundError(Exception):
    """Raised when the CT-API DLL cannot be loaded."""


class CTAPI:
    """Wrapper for CT-API card terminal communication.

    Usage::

        ct = CTAPI("ctpcsc32.dll")
        ct.init(ctn=1, pn=1)
        atr = ct.request_icc(ctn=1)
        data = ct.read_card_data(ctn=1)
        ct.eject_icc(ctn=1)
        ct.close(ctn=1)
    """

    MAX_RESPONSE = 1024

    def __init__(self, library_path: str):
        """Load the CT-API shared library.

        Args:
            library_path: Path to the vendor-specific CT-API DLL.

        Raises:
            CTAPINotFoundError: If the DLL cannot be loaded.
        """
        log.info("CT-API: Lade DLL '%s' ...", library_path)

        try:
            if sys.platform == "win32":
                self._lib = ctypes.WinDLL(library_path)
            else:
                self._lib = ctypes.CDLL(library_path)
        except OSError as e:
            raise CTAPINotFoundError(
                f"CT-API DLL nicht gefunden: {library_path}\n{e}"
            ) from e

        log.info("CT-API DLL geladen: %s", library_path)

        # Bind CT-API functions — wrapped in try/except because some DLLs
        # may not export these symbols (wrong DLL, 64-bit vs 32-bit, etc.)
        try:
            # CT_init(unsigned short ctn, unsigned short pn) -> signed char
            self._lib.CT_init.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
            self._lib.CT_init.restype = ctypes.c_int8

            # CT_data(ctn, *dad, *sad, lenc, *command, *lenr, *response) -> signed char
            self._lib.CT_data.argtypes = [
                ctypes.c_ushort,                    # ctn
                ctypes.POINTER(ctypes.c_uint8),     # dad
                ctypes.POINTER(ctypes.c_uint8),     # sad
                ctypes.c_ushort,                    # lenc
                ctypes.POINTER(ctypes.c_uint8),     # command
                ctypes.POINTER(ctypes.c_ushort),    # lenr
                ctypes.POINTER(ctypes.c_uint8),     # response
            ]
            self._lib.CT_data.restype = ctypes.c_int8

            # CT_close(unsigned short ctn) -> signed char
            self._lib.CT_close.argtypes = [ctypes.c_ushort]
            self._lib.CT_close.restype = ctypes.c_int8
        except AttributeError as e:
            raise CTAPINotFoundError(
                f"CT-API Funktionen nicht in DLL: {library_path}\n"
                f"CT_init/CT_data/CT_close nicht exportiert.\n"
                f"Falsche DLL konfiguriert? Detail: {e}"
            ) from e

        log.info("CT-API bereit: CT_init, CT_data, CT_close")

    def init(self, ctn: int = 1, pn: int = 1) -> None:
        """Initialize connection to card terminal.

        Args:
            ctn: Logical card terminal number (freely chosen).
            pn: Physical port number (vendor-specific, usually 1 for USB).

        Raises:
            CTAPIError: If initialization fails.
        """
        rc = self._lib.CT_init(ctypes.c_ushort(ctn), ctypes.c_ushort(pn))
        if rc != CT_OK:
            raise CTAPIError("CT_init", rc)
        log.info("CT_init OK (ctn=%d, pn=%d)", ctn, pn)

    def close(self, ctn: int = 1) -> None:
        """Close connection to card terminal.

        Args:
            ctn: Card terminal number used in init().
        """
        rc = self._lib.CT_close(ctypes.c_ushort(ctn))
        if rc != CT_OK:
            log.warning("CT_close returned %d", rc)
        else:
            log.info("CT_close OK (ctn=%d)", ctn)

    def data(
        self,
        ctn: int,
        dad: int,
        sad: int,
        command: bytes,
        max_response: int = MAX_RESPONSE,
    ) -> Tuple[bytes, int, int]:
        """Send command APDU and receive response.

        Args:
            ctn: Card terminal number.
            dad: Destination address (DAD_CT, DAD_ICC1, DAD_ICC2).
            sad: Source address (typically SAD_HOST = 0x02).
            command: Command APDU as bytes.
            max_response: Maximum expected response size.

        Returns:
            Tuple of (response_data, sw1, sw2).
            response_data excludes the trailing status words.

        Raises:
            CTAPIError: If CT_data returns an error.
            ValueError: If response too short for status words.
        """
        dad_byte = ctypes.c_uint8(dad)
        sad_byte = ctypes.c_uint8(sad)

        cmd_len = len(command)
        cmd_buf = (ctypes.c_uint8 * cmd_len)(*command)

        resp_len = ctypes.c_ushort(max_response)
        resp_buf = (ctypes.c_uint8 * max_response)()

        rc = self._lib.CT_data(
            ctypes.c_ushort(ctn),
            ctypes.byref(dad_byte),
            ctypes.byref(sad_byte),
            ctypes.c_ushort(cmd_len),
            cmd_buf,
            ctypes.byref(resp_len),
            resp_buf,
        )

        if rc != CT_OK:
            raise CTAPIError("CT_data", rc)

        actual_len = resp_len.value
        if actual_len < 2:
            raise ValueError(
                f"Antwort zu kurz ({actual_len} Bytes), SW1+SW2 erwartet"
            )

        response = bytes(resp_buf[:actual_len])
        sw1 = response[-2]
        sw2 = response[-1]
        data = response[:-2]

        return data, sw1, sw2

    def request_icc(self, ctn: int = 1, slot: int = 1) -> bytes:
        """Send REQUEST ICC to activate card and get ATR.

        Uses the 5-byte format per Cherry CT-API documentation:
        [0x20, 0x12, slot, 0x01, 0x00]

        The Cherry demo shows that after REQUEST ICC to CT (dad=1),
        the same command should be sent to ICC (dad=0) to get card data.
        This method stores any received card data for later use.

        Args:
            ctn: Card terminal number.
            slot: Card slot (1=ICC1, 2=ICC2).

        Returns:
            ATR (Answer To Reset) bytes from the CT response.

        Raises:
            RuntimeError: If no card present or command fails.
        """
        # 5-byte REQUEST ICC command (Le=0x00 at end per Cherry spec)
        cmd = bytes([0x20, 0x12, slot, 0x01, 0x00])

        log.info("REQUEST ICC: Sende an CT (dad=1), CMD=%s",
                 " ".join(f"{b:02X}" for b in cmd))

        data, sw1, sw2 = self.data(ctn, DAD_CT, SAD_HOST, cmd)

        log.info("REQUEST ICC Response: SW1=%02X SW2=%02X, %d Bytes: %s",
                 sw1, sw2, len(data),
                 " ".join(f"{b:02X}" for b in data[:64]) if data else "(leer)")

        if sw1 == 0x64 and sw2 == 0x00:
            raise RuntimeError("Keine Karte eingesteckt")
        if sw1 == 0x62 and sw2 == 0x00:
            log.info("Karte bereits aktiviert")
        elif sw1 != 0x90:
            raise RuntimeError(
                f"REQUEST ICC fehlgeschlagen: SW1=0x{sw1:02X} SW2=0x{sw2:02X}"
            )

        sync = "synchron" if sw2 == 0x01 else "asynchron"
        log.info("Karte erkannt (%s), ATR (%d Bytes): %s",
                 sync, len(data), " ".join(f"{b:02X}" for b in data))

        # Check if this response already contains card data
        self._request_icc_data = None
        if len(data) > 20 and self._validate_kvk_data(data):
            log.info(">>> REQUEST ICC an CT enthält bereits KVK-Daten! <<<")
            self._request_icc_data = data
            return data

        # ============================================================
        # Cherry protocol: Send REQUEST ICC again to ICC (dad=0)
        # The Cherry C++ demo shows this is how you get card data:
        # First REQUEST ICC to CT (dad=1) → activates card, returns ATR
        # Then same command to ICC (dad=0) → returns actual card data
        # ============================================================
        log.info("Cherry-Protokoll: Sende REQUEST ICC an ICC (dad=0)...")
        try:
            icc_data, icc_sw1, icc_sw2 = self.data(
                ctn, DAD_ICC1, SAD_HOST, cmd
            )
            log.info("REQUEST ICC->ICC Response: SW1=%02X SW2=%02X, %d Bytes: %s",
                     icc_sw1, icc_sw2, len(icc_data),
                     " ".join(f"{b:02X}" for b in icc_data[:64]) if icc_data else "(leer)")
            if len(icc_data) > 64:
                log.info("  ... (gesamt %d Bytes)", len(icc_data))

            if len(icc_data) > 10:
                if self._validate_kvk_data(icc_data):
                    log.info(">>> Cherry-Protokoll ERFOLGREICH: KVK-Daten via REQUEST ICC->ICC <<<")
                    self._request_icc_data = icc_data
                else:
                    # Even if no 0x60 container found, store for analysis
                    log.info("  ICC-Daten empfangen aber kein KVK-Container erkannt")
                    # Store as potential data — read_card_data will try to use it
                    self._icc_response_data = icc_data
        except Exception as e:
            log.info("REQUEST ICC->ICC fehlgeschlagen: %s", e)

        return data

    def eject_icc(self, ctn: int = 1, slot: int = 1) -> None:
        """Send EJECT ICC to deactivate the card.

        Args:
            ctn: Card terminal number.
            slot: Card slot (1=ICC1, 2=ICC2).
        """
        cmd = bytes([0x20, 0x15, slot, 0x00])
        _data, sw1, sw2 = self.data(ctn, DAD_CT, SAD_HOST, cmd)

        if sw1 != 0x90:
            log.warning("EJECT ICC: SW1=0x%02X SW2=0x%02X", sw1, sw2)
        else:
            log.info("Karte deaktiviert")

    def _try_read(self, ctn: int, dad: int, cmd: bytes) -> tuple:
        """Send a command and return (data, sw1, sw2, success).

        Does not raise on bad status — returns success=False instead.
        Logs detailed diagnostic info for every attempt.

        Accepts SW1=0x90 (success), SW1=0x61 (more data available),
        and SW1=0x62 (warning: EOF before Le bytes) as success.
        SW1=0x62 is common on synchronous memory cards where the
        card has fewer bytes than requested — the data is still valid.
        """
        cmd_hex = " ".join(f"{b:02X}" for b in cmd)
        dad_name = {0x00: "ICC", 0x01: "CT", 0x02: "ICC2"}.get(dad, f"0x{dad:02X}")
        try:
            data, sw1, sw2 = self.data(ctn, dad, SAD_HOST, cmd)
            # 0x90=OK, 0x61=more data, 0x62=warning (EOF before Le)
            ok = sw1 in (0x90, 0x61, 0x62)
            data_hex = " ".join(f"{b:02X}" for b in data[:32]) if data else "(leer)"
            if len(data) > 32:
                data_hex += f" ... ({len(data)} Bytes gesamt)"
            status = "OK" if sw1 == 0x90 else ("WARNUNG" if sw1 == 0x62 else ("MEHR" if sw1 == 0x61 else "FEHLER"))
            log.info("  -> [%s] CMD=%s => SW1=%02X SW2=%02X, %d Bytes: %s %s",
                     dad_name, cmd_hex, sw1, sw2, len(data), data_hex, status)
            return data, sw1, sw2, ok
        except Exception as e:
            log.info("  -> [%s] CMD=%s => EXCEPTION: %s", dad_name, cmd_hex, e)
            return b"", 0, 0, False

    def _try_read_any_response(self, ctn: int, dad: int, cmd: bytes) -> tuple:
        """Like _try_read but accepts any SW1/SW2 as long as CT_data succeeds.

        Returns (data, sw1, sw2, ct_data_ok) where ct_data_ok is True
        if CT_data itself didn't throw an error (regardless of SW1/SW2).
        """
        cmd_hex = " ".join(f"{b:02X}" for b in cmd)
        dad_name = {0x00: "ICC", 0x01: "CT", 0x02: "ICC2"}.get(dad, f"0x{dad:02X}")
        try:
            data, sw1, sw2 = self.data(ctn, dad, SAD_HOST, cmd)
            data_hex = " ".join(f"{b:02X}" for b in data[:64]) if data else "(leer)"
            if len(data) > 64:
                data_hex += f" ... ({len(data)} Bytes gesamt)"
            log.info("  -> [%s] CMD=%s => SW1=%02X SW2=%02X, %d Bytes: %s",
                     dad_name, cmd_hex, sw1, sw2, len(data), data_hex)
            return data, sw1, sw2, True
        except Exception as e:
            log.info("  -> [%s] CMD=%s => EXCEPTION: %s", dad_name, cmd_hex, e)
            return b"", 0, 0, False

    def read_card_data(self, ctn: int = 1, total_bytes: int = 416) -> bytes:
        """Read KVK data from a synchronous memory card (SLE4428).

        Tries many strategies because different CT-API DLLs and
        card readers handle synchronous cards differently.

        Strategies include:
        1. Standard ISO 7816-4 READ BINARY (CLA=0x00)
        2. Cherry-specific: CLA=0x20 READ BINARY (sync card CLA)
        3. READ RECORD commands
        4. CT-BCS READ MEMORY (0x20 0x08) for direct memory access
        5. GET DATA commands
        6. Various combinations of DADs, AIDs, and chunk sizes

        Args:
            ctn: Card terminal number.
            total_bytes: Total bytes to read (SLE4428 = 416).

        Returns:
            Complete card data as bytes.
        """
        log.info("=" * 60)
        log.info("DIAGNOSE: Starte KVK-Kartenlesung")
        log.info("=" * 60)

        # Check if REQUEST ICC already returned valid card data
        if hasattr(self, '_request_icc_data') and self._request_icc_data:
            log.info(">>> REQUEST ICC enthielt bereits KVK-Daten! <<<")
            return self._request_icc_data

        # Collect all data we get from any strategy for diagnosis
        all_results = []

        # Check if ICC response from REQUEST ICC had data (possibly without 0x60 container)
        if hasattr(self, '_icc_response_data') and self._icc_response_data:
            icc_resp = self._icc_response_data
            log.info("ICC-Response aus REQUEST ICC verfügbar: %d Bytes", len(icc_resp))
            all_results.append(("REQUEST ICC->ICC Response", icc_resp))

        # KVK AIDs
        kvk_aid = [0xD2, 0x76, 0x00, 0x00, 0x01, 0x01]
        kvk_aid_alt = [0xD2, 0x80, 0x00, 0x00, 0x01, 0x01]

        # ============================================================
        # GROUP 0: Best known working strategy for Cherry ST-2052:
        # SELECT KVK AID to ICC, then READ BINARY to ICC
        # (confirmed working from diagnostic log)
        # ============================================================
        for aid, aid_name in [(kvk_aid, "D27600000101"), (kvk_aid_alt, "D28000000101")]:
            name = f"G0: SELECT {aid_name} + READ (dad=ICC)"
            log.info("-" * 50)
            log.info("Strategie: %s (bevorzugt)", name)

            select_cmd = bytes([0x00, 0xA4, 0x04, 0x00, len(aid)] + aid)
            _, _, _, sel_ok = self._try_read(ctn, DAD_ICC1, select_cmd)

            if sel_ok:
                result = self._read_binary_loop(ctn, DAD_ICC1, total_bytes, 256, cla=0x00)
                if self._check_result(result, name, all_results):
                    return result

        # ============================================================
        # GROUP 0b: Cherry protocol — send REQUEST ICC to ICC
        # ============================================================
        name = "G0b: Cherry REQUEST ICC->ICC"
        log.info("-" * 50)
        log.info("Strategie: %s", name)

        for slot in [1, 2]:
            cmd = bytes([0x20, 0x12, slot, 0x01, 0x00])
            data, sw1, sw2, ok = self._try_read_any_response(ctn, DAD_ICC1, cmd)
            if data and len(data) > 10:
                if self._validate_kvk_data(data):
                    log.info(">>> Cherry-Strategie ERFOLGREICH: %d Bytes <<<", len(data))
                    return data
                all_results.append((f"{name} slot={slot}", data))

        # ============================================================
        # GROUP 1: Standard ISO 7816-4 READ BINARY (CLA=0x00)
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G1: ISO READ BINARY CLA=00 (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)
            result = self._read_binary_loop(ctn, dad, total_bytes, 256, cla=0x00)
            if self._check_result(result, name, all_results):
                return result

        # ============================================================
        # GROUP 2: Sync card READ BINARY with CLA=0x20
        # Cherry and some other vendors use CLA=0x20 for sync cards
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G2: Sync READ BINARY CLA=20 (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)
            result = self._read_binary_loop(ctn, dad, total_bytes, 256, cla=0x20)
            if self._check_result(result, name, all_results):
                return result

        # ============================================================
        # GROUP 3: READ BINARY with Le=0 (request max 256 bytes)
        # Some CT-APIs only respond to Le=0
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G3: READ BINARY Le=0 single read (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)
            # Single read with offset 0, Le=0 (=256 bytes)
            for cla in [0x00, 0x20]:
                cmd = bytes([cla, 0xB0, 0x00, 0x00, 0x00])
                data, sw1, sw2, ok = self._try_read_any_response(ctn, dad, cmd)
                if data and len(data) > 10:
                    if self._validate_kvk_data(data):
                        log.info("Strategie '%s' (CLA=%02X) erfolgreich!", name, cla)
                        return data
                    all_results.append((f"{name} CLA={cla:02X}", data))

        # ============================================================
        # GROUP 4: SELECT AID then READ BINARY
        # ============================================================
        for aid, aid_name in [(kvk_aid, "D27600000101"), (kvk_aid_alt, "D28000000101")]:
            for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
                name = f"G4: SELECT {aid_name} + READ (dad={dad_name})"
                log.info("-" * 50)
                log.info("Strategie: %s", name)

                # Try SELECT to both destinations
                select_cmd = bytes([0x00, 0xA4, 0x04, 0x00, len(aid)] + aid)
                _, _, _, ok1 = self._try_read(ctn, DAD_ICC1, select_cmd)
                _, _, _, ok2 = self._try_read(ctn, DAD_CT, select_cmd)

                if ok1 or ok2:
                    for cla in [0x00, 0x20]:
                        result = self._read_binary_loop(ctn, dad, total_bytes, 256, cla=cla)
                        if self._check_result(result, f"{name} CLA={cla:02X}", all_results):
                            return result
                else:
                    log.info("  SELECT fehlgeschlagen, überspringe...")

        # ============================================================
        # GROUP 5: SELECT MF (Master File) then READ BINARY
        # Some readers need MF selection first
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G5: SELECT MF + READ (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)

            # SELECT MF: P1=0x00, P2=0x00 (select MF by empty data)
            select_mf = bytes([0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00])
            self._try_read(ctn, dad, select_mf)

            for cla in [0x00, 0x20]:
                result = self._read_binary_loop(ctn, dad, total_bytes, 256, cla=cla)
                if self._check_result(result, f"{name} CLA={cla:02X}", all_results):
                    return result

        # ============================================================
        # GROUP 6: READ RECORD commands (some sync cards use records)
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G6: READ RECORD (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)

            collected = bytearray()
            for record_nr in range(1, 20):
                for cla in [0x00, 0x20]:
                    # READ RECORD: INS=0xB2, P1=record_nr, P2=0x04 (absolute)
                    cmd = bytes([cla, 0xB2, record_nr, 0x04, 0x00])
                    data, sw1, sw2, ok = self._try_read(ctn, dad, cmd)
                    if ok and data:
                        collected.extend(data)
                        break
                else:
                    if collected:
                        break
                    if record_nr > 2:
                        break

            if collected and len(collected) > 10:
                if self._validate_kvk_data(bytes(collected)):
                    log.info("Strategie '%s' erfolgreich! %d Bytes", name, len(collected))
                    return bytes(collected)
                all_results.append((name, bytes(collected)))

        # ============================================================
        # GROUP 7: GET DATA command (CLA=0x00, INS=0xCA)
        # ============================================================
        for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
            name = f"G7: GET DATA (dad={dad_name})"
            log.info("-" * 50)
            log.info("Strategie: %s", name)

            for p1, p2 in [(0x00, 0x00), (0x01, 0x00), (0x60, 0x00)]:
                cmd = bytes([0x00, 0xCA, p1, p2, 0x00])
                data, sw1, sw2, ok = self._try_read_any_response(ctn, dad, cmd)
                if data and len(data) > 10:
                    if self._validate_kvk_data(data):
                        return data
                    all_results.append((f"{name} P1={p1:02X} P2={p2:02X}", data))

        # ============================================================
        # GROUP 8: Small chunk reads (32 bytes, 64 bytes)
        # ============================================================
        for chunk_size in [32, 64, 128]:
            for dad, dad_name in [(DAD_ICC1, "ICC"), (DAD_CT, "CT")]:
                for cla in [0x00, 0x20]:
                    name = f"G8: {chunk_size}B chunks CLA={cla:02X} (dad={dad_name})"
                    log.info("-" * 50)
                    log.info("Strategie: %s", name)
                    result = self._read_binary_loop(
                        ctn, dad, total_bytes, chunk_size, cla=cla
                    )
                    if self._check_result(result, name, all_results):
                        return result

        # ============================================================
        # GROUP 9: CT-BCS proprietary commands
        # Direct memory access via terminal command
        # ============================================================
        name = "G9: CT-BCS Direct Memory Read"
        log.info("-" * 50)
        log.info("Strategie: %s", name)

        # Some CT-APIs support reading synchronous card memory
        # via CT-BCS command sent to the CT (dad=0x01)
        # Format: CLA=0x20, INS=0xB0/0xB1, P1=offset_hi, P2=offset_lo
        for ins in [0xB0, 0xB1, 0x08]:
            cmd = bytes([0x20, ins, 0x00, 0x00, 0x00])
            data, sw1, sw2, ok = self._try_read_any_response(ctn, DAD_CT, cmd)
            if data and len(data) > 10:
                if self._validate_kvk_data(data):
                    return data
                all_results.append((f"{name} INS={ins:02X}", data))

        # ============================================================
        # GROUP 10: Try reading the ATR data area
        # Some Cherry CT-APIs put KVK data right after ATR in
        # the REQUEST ICC response or need a second REQUEST ICC
        # ============================================================
        name = "G10: Second REQUEST ICC for data"
        log.info("-" * 50)
        log.info("Strategie: %s", name)
        try:
            # Some implementations return card data in extended REQUEST ICC
            cmd_ext = bytes([0x20, 0x12, 0x01, 0x02])  # P2=0x02 = return data
            data, sw1, sw2, ok = self._try_read_any_response(ctn, DAD_CT, cmd_ext)
            if data and len(data) > 10:
                if self._validate_kvk_data(data):
                    return data
                all_results.append((name, data))
        except Exception as e:
            log.info("  %s fehlgeschlagen: %s", name, e)

        # ============================================================
        # DIAGNOSIS OUTPUT: Show what we got from all attempts
        # ============================================================
        log.info("=" * 60)
        log.info("DIAGNOSE: Alle Strategien fehlgeschlagen!")
        log.info("Daten-Zusammenfassung aller Versuche die Daten lieferten:")
        for idx, (sname, sdata) in enumerate(all_results):
            hex_dump = " ".join(f"{b:02X}" for b in sdata[:80])
            if len(sdata) > 80:
                hex_dump += f" ... (gesamt {len(sdata)} Bytes)"
            log.info("  [%d] %s: %s", idx, sname, hex_dump)
        if not all_results:
            log.info("  (Keine Strategie hat Daten zurückgeliefert)")
        log.info("=" * 60)

        # Build detailed error message
        error_details = (
            "KVK-Karte konnte nicht gelesen werden.\n"
            "Alle Strategien fehlgeschlagen.\n\n"
            f"Versuche mit Daten: {len(all_results)}\n"
        )
        if all_results:
            error_details += "Erste 32 Bytes der besten Antwort:\n"
            best = max(all_results, key=lambda x: len(x[1]))
            hex_str = " ".join(f"{b:02X}" for b in best[1][:32])
            error_details += f"  {best[0]}: {hex_str}\n"

        raise RuntimeError(error_details)

    def _check_result(
        self, result: bytes, name: str, all_results: List[tuple]
    ) -> bool:
        """Check if read result contains valid KVK data.

        Returns True if valid (caller should return the data).
        If data was read but invalid, stores in all_results for diagnosis.
        """
        if result and len(result) > 10:
            if self._validate_kvk_data(result):
                log.info(">>> Strategie '%s' ERFOLGREICH: %d Bytes <<<", name, len(result))
                return True
            else:
                hex_dump = " ".join(f"{b:02X}" for b in result[:64])
                log.info("  Daten gelesen (%d Bytes) aber kein KVK-Container: %s",
                         len(result), hex_dump)
                all_results.append((name, result))
        else:
            if result:
                log.info("  Zu wenig Daten: %d Bytes", len(result))
            else:
                log.info("  Keine Daten")
        return False

    @staticmethod
    def _validate_kvk_data(data: bytes) -> bool:
        """Check if data contains a valid KVK TLV container (0x60).

        Verifies that:
        - A 0x60 tag exists
        - It has a valid BER length
        - The container fits within the data
        - First inner tag is 0x80-0x90

        Returns:
            True if data looks like valid KVK data.
        """
        for i in range(len(data) - 3):
            if data[i] != 0x60:
                continue

            # Read BER length
            length_byte = data[i + 1]
            if length_byte <= 0x7F:
                container_len = length_byte
                data_start = i + 2
            elif length_byte == 0x81 and i + 2 < len(data):
                container_len = data[i + 2]
                data_start = i + 3
            elif length_byte == 0x82 and i + 3 < len(data):
                container_len = (data[i + 2] << 8) | data[i + 3]
                data_start = i + 4
            else:
                continue

            # Container must be reasonable size and fit in data
            if container_len < 10:
                continue
            if data_start + container_len > len(data):
                continue

            # First inner tag must be a KVK tag
            if data_start < len(data) and 0x80 <= data[data_start] <= 0x90:
                return True

        return False

    def _read_binary_loop(
        self, ctn: int, dad: int, total_bytes: int,
        chunk_max: int = 256, cla: int = 0x00,
    ) -> bytes:
        """Read binary data in a loop using READ BINARY (INS=0xB0).

        Args:
            ctn: Card terminal number.
            dad: Destination address (DAD_ICC1 or DAD_CT).
            total_bytes: Total bytes to attempt to read.
            chunk_max: Maximum bytes per READ BINARY call.
            cla: Class byte (0x00=standard, 0x20=sync card).

        Returns:
            Raw card data bytes (empty if first read fails).
        """
        data = bytearray()
        offset = 0

        while offset < total_bytes:
            remaining = total_bytes - offset
            chunk_size = min(remaining, chunk_max)
            le = chunk_size if chunk_size < 256 else 0  # 0 = 256 bytes

            p1 = (offset >> 8) & 0xFF
            p2 = offset & 0xFF
            cmd = bytes([cla, 0xB0, p1, p2, le])

            chunk, sw1, sw2, ok = self._try_read(ctn, dad, cmd)

            if not ok:
                # Special: SW1=0x6C means wrong Le, SW2 has correct length
                if sw1 == 0x6C and sw2 > 0:
                    log.info("  Korrigiere Le auf %d", sw2)
                    cmd = bytes([cla, 0xB0, p1, p2, sw2])
                    chunk, sw1, sw2, ok = self._try_read(ctn, dad, cmd)

                if not ok:
                    if offset == 0:
                        return b""  # First read failed → strategy doesn't work
                    log.info("Lesen beendet bei Offset %d (SW1=0x%02X SW2=0x%02X)",
                             offset, sw1, sw2)
                    break

            data.extend(chunk)
            offset += len(chunk)

            if len(chunk) == 0:
                break

            # SW1=0x62 means "warning: EOF reached before Le bytes"
            # The data is valid but there's no more to read
            if sw1 == 0x62:
                log.info("EOF erreicht bei Offset %d (SW1=62, %d Bytes in letztem Chunk)",
                         offset, len(chunk))
                break

            if len(chunk) < chunk_size:
                log.info("Lesen beendet bei Offset %d (weniger Daten als erwartet)", offset)
                break

        log.info("Gelesen: %d Bytes (dad=0x%02X, CLA=0x%02X)", len(data), dad, cla)
        return bytes(data)
