"""Tests for CT-API wrapper and KVK CT-API reading."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from kvk_reader.card.ct_api import (
    CTAPI,
    CTAPIError,
    CTAPINotFoundError,
    CT_OK,
    ERR_CT,
    ERR_INVALID,
    DAD_CT,
    DAD_ICC1,
    SAD_HOST,
    RETURN_CODES,
)


class TestCTAPIError:
    def test_error_message_known_code(self):
        err = CTAPIError("CT_init", ERR_CT)
        assert "CT_init" in str(err)
        assert "Kommunikationsfehler" in str(err)

    def test_error_message_unknown_code(self):
        err = CTAPIError("CT_data", -99)
        assert "-99" in str(err)

    def test_return_codes_dict(self):
        assert RETURN_CODES[0] == "OK"
        assert ERR_INVALID in RETURN_CODES
        assert ERR_CT in RETURN_CODES


class TestCTAPINotFoundError:
    def test_dll_not_found(self):
        with pytest.raises(CTAPINotFoundError, match="nicht gefunden"):
            CTAPI("nonexistent_dll_12345.dll")


class TestCTAPIWrapper:
    """Test CT-API wrapper with mocked DLL."""

    @pytest.fixture
    def mock_ct(self):
        """Create a CTAPI instance with mocked library."""
        with patch("kvk_reader.card.ct_api.ctypes") as mock_ctypes:
            # Mock WinDLL / CDLL
            mock_lib = MagicMock()
            mock_ctypes.WinDLL.return_value = mock_lib
            mock_ctypes.CDLL.return_value = mock_lib

            # Forward real ctypes types
            import ctypes as real_ctypes
            mock_ctypes.c_ushort = real_ctypes.c_ushort
            mock_ctypes.c_uint8 = real_ctypes.c_uint8
            mock_ctypes.c_int8 = real_ctypes.c_int8
            mock_ctypes.POINTER = real_ctypes.POINTER
            mock_ctypes.byref = real_ctypes.byref

            ct = CTAPI.__new__(CTAPI)
            ct._lib = mock_lib
            yield ct, mock_lib

    def test_init_success(self, mock_ct):
        ct, lib = mock_ct
        lib.CT_init.return_value = CT_OK
        ct.init(ctn=1, pn=1)
        lib.CT_init.assert_called_once()

    def test_init_failure(self, mock_ct):
        ct, lib = mock_ct
        lib.CT_init.return_value = ERR_CT
        with pytest.raises(CTAPIError, match="CT_init"):
            ct.init(ctn=1, pn=1)

    def test_close_success(self, mock_ct):
        ct, lib = mock_ct
        lib.CT_close.return_value = CT_OK
        ct.close(ctn=1)
        lib.CT_close.assert_called_once()

    def test_constants(self):
        assert DAD_ICC1 == 0x00
        assert DAD_CT == 0x01
        assert SAD_HOST == 0x02


class TestKvkReaderCtapi:
    """Test KVK reading via CT-API (high-level)."""

    def test_read_kvk_ctapi_dll_not_found(self):
        from kvk_reader.card.kvk_reader import read_kvk_ctapi, KvkReadError
        with pytest.raises(KvkReadError, match="nicht gefunden"):
            read_kvk_ctapi("nonexistent_dll_12345.dll")

    def test_read_kvk_unified_no_method(self):
        from kvk_reader.card.kvk_reader import read_kvk, KvkReadError
        with pytest.raises(KvkReadError, match="Kein Leseverfahren"):
            read_kvk()

    def test_read_kvk_unified_with_dll(self):
        """Unified read_kvk with dll_path tries CT-API."""
        from kvk_reader.card.kvk_reader import read_kvk, KvkReadError
        with pytest.raises(KvkReadError, match="nicht gefunden"):
            read_kvk(dll_path="nonexistent.dll")


class TestValidateKvkData:
    """Test KVK data validation."""

    def test_valid_kvk_data(self):
        # Build minimal valid KVK TLV: 0x60 container with 0x80 inner tag
        inner = bytes([0x80, 0x03, 0x41, 0x42, 0x43,   # tag=0x80, len=3, "ABC"
                       0x85, 0x03, 0x44, 0x45, 0x46,   # tag=0x85, len=3, "DEF"
                       0x87, 0x04, 0x54, 0x65, 0x73, 0x74])  # tag=0x87, "Test"
        data = bytes([0x60, len(inner)]) + inner
        assert CTAPI._validate_kvk_data(data) is True

    def test_invalid_no_container(self):
        data = bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x05])
        assert CTAPI._validate_kvk_data(data) is False

    def test_invalid_too_short(self):
        data = bytes([0x60, 0x02, 0x80, 0x00])
        assert CTAPI._validate_kvk_data(data) is False

    def test_valid_with_prefix(self):
        # KVK data with ATR prefix
        inner = bytes([0x80, 0x05, 0x41, 0x42, 0x43, 0x44, 0x45,
                       0x85, 0x03, 0x44, 0x45, 0x46])
        container = bytes([0x60, len(inner)]) + inner
        data = bytes([0x00] * 30) + container
        assert CTAPI._validate_kvk_data(data) is True


class TestCardDetectorCtapi:
    """Test card detector with CT-API integration."""

    def test_worker_init_with_ctapi(self):
        from kvk_reader.card.card_detector import CardReaderWorker
        worker = CardReaderWorker(ct_api_dll="ctpcsc32.dll", ct_api_pn=2)
        assert worker._ct_api_dll == "ctpcsc32.dll"
        assert worker._ct_api_pn == 2

    def test_worker_init_without_ctapi(self):
        from kvk_reader.card.card_detector import CardReaderWorker
        worker = CardReaderWorker()
        assert worker._ct_api_dll == ""
        assert worker._ct_api_pn == 1
