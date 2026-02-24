"""Tests for Omnikey Sync API wrapper."""

from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock

import pytest

from kvk_reader.card.omnikey_sync import (
    OKERR_OK,
    OKERR_COMMUNICATE,
    OKERR_ILLEGAL_CARDTYPE,
    OKERR_CARD_NOT_INSERTED,
    SCARD_SCOPE_USER,
    SCARD_SHARE_SHARED,
    SCARD_PROTOCOL_T0,
    SCARD_PROTOCOL_T1,
    SCARD_LEAVE_CARD,
    SCARD_S_SUCCESS,
    SLE4428_SIZE,
    SLE4442_SIZE,
    OmnikeySyncError,
    _format_error,
    is_omnikey_reader,
)


class TestConstants:
    def test_sle4428_size(self):
        assert SLE4428_SIZE == 1024

    def test_sle4442_size(self):
        assert SLE4442_SIZE == 256

    def test_okerr_ok_is_zero(self):
        assert OKERR_OK == 0

    def test_scard_success_is_zero(self):
        assert SCARD_S_SUCCESS == 0

    def test_error_codes_are_nonzero(self):
        assert OKERR_COMMUNICATE != 0
        assert OKERR_ILLEGAL_CARDTYPE != 0
        assert OKERR_CARD_NOT_INSERTED != 0

    def test_scard_protocols(self):
        assert SCARD_PROTOCOL_T0 == 0x0001
        assert SCARD_PROTOCOL_T1 == 0x0002

    def test_scard_share_shared(self):
        assert SCARD_SHARE_SHARED == 2


class TestFormatError:
    def test_known_error(self):
        msg = _format_error(OKERR_COMMUNICATE)
        assert "Kommunikationsfehler" in msg
        assert "0x81300001" in msg

    def test_illegal_cardtype(self):
        msg = _format_error(OKERR_ILLEGAL_CARDTYPE)
        assert "Kartentyp" in msg

    def test_card_not_inserted(self):
        msg = _format_error(OKERR_CARD_NOT_INSERTED)
        assert "Keine Karte" in msg

    def test_unknown_error(self):
        msg = _format_error(0xDEADBEEF)
        assert "Unbekannter Fehler" in msg
        assert "0xDEADBEEF" in msg


class TestIsOmnikeyReader:
    def test_omnikey_3x21(self):
        assert is_omnikey_reader("HID Global OMNIKEY 3x21 Smart Card Reader 0")

    def test_omnikey_5427(self):
        assert is_omnikey_reader("HID Global OMNIKEY 5427 CK 0")

    def test_omnikey_lowercase(self):
        assert is_omnikey_reader("omnikey cardman 3121")

    def test_cherry_reader(self):
        assert not is_omnikey_reader("Cherry SmartTerminal ST-2052 0")

    def test_generic_reader(self):
        assert not is_omnikey_reader("Generic Smart Card Reader")

    def test_empty_string(self):
        assert not is_omnikey_reader("")


class TestIsOmnikeyAvailable:
    def test_not_available_on_non_windows(self):
        """On macOS/Linux, is_omnikey_available() returns False."""
        from kvk_reader.card.omnikey_sync import is_omnikey_available
        if sys.platform != "win32":
            assert is_omnikey_available() is False

    @patch("kvk_reader.card.omnikey_sync.sys")
    def test_returns_false_on_non_win32(self, mock_sys):
        from kvk_reader.card.omnikey_sync import is_omnikey_available
        mock_sys.platform = "darwin"
        assert is_omnikey_available() is False

    @patch("kvk_reader.card.omnikey_sync.sys")
    @patch("kvk_reader.card.omnikey_sync._load_scardsyn")
    def test_returns_true_when_dll_available(self, mock_load, mock_sys):
        from kvk_reader.card.omnikey_sync import is_omnikey_available
        mock_sys.platform = "win32"
        mock_load.return_value = MagicMock()
        assert is_omnikey_available() is True

    @patch("kvk_reader.card.omnikey_sync.sys")
    @patch("kvk_reader.card.omnikey_sync._load_scardsyn")
    def test_returns_false_when_dll_missing(self, mock_load, mock_sys):
        from kvk_reader.card.omnikey_sync import is_omnikey_available
        mock_sys.platform = "win32"
        mock_load.side_effect = OSError("DLL not found")
        assert is_omnikey_available() is False


class TestCardTypeDetection:
    """Test ATR-based card type detection logic."""

    def test_sle4428_atr_0x92(self):
        """ATR byte[2] == 0x92 → SLE4428."""
        from kvk_reader.card.omnikey_sync import _detect_card_type_from_atr
        mock_winscard = MagicMock()
        mock_hCard = MagicMock()

        # Simulate SCardGetAttrib returning ATR with byte[2] = 0x92
        def fake_get_attrib(hCard, attr_id, buf, buf_len):
            atr = [0x3B, 0x04, 0x92, 0x23, 0x10, 0x91]
            for i, b in enumerate(atr):
                buf[i] = b
            buf_len._obj.value = len(atr)
            return 0  # SCARD_S_SUCCESS

        mock_winscard.SCardGetAttrib.side_effect = fake_get_attrib
        card_type, size = _detect_card_type_from_atr(mock_winscard, mock_hCard)
        assert card_type == "SLE4428"
        assert size == 1024

    def test_sle4442_atr_0xa2(self):
        """ATR byte[2] == 0xA2 → SLE4442."""
        from kvk_reader.card.omnikey_sync import _detect_card_type_from_atr
        mock_winscard = MagicMock()
        mock_hCard = MagicMock()

        def fake_get_attrib(hCard, attr_id, buf, buf_len):
            atr = [0x3B, 0x04, 0xA2, 0x13, 0x10, 0x91]
            for i, b in enumerate(atr):
                buf[i] = b
            buf_len._obj.value = len(atr)
            return 0

        mock_winscard.SCardGetAttrib.side_effect = fake_get_attrib
        card_type, size = _detect_card_type_from_atr(mock_winscard, mock_hCard)
        assert card_type == "SLE4442"
        assert size == 256

    def test_atr_read_failure_defaults_to_sle4442(self):
        """If ATR cannot be read, default to SLE4442."""
        from kvk_reader.card.omnikey_sync import _detect_card_type_from_atr
        mock_winscard = MagicMock()
        mock_hCard = MagicMock()
        mock_winscard.SCardGetAttrib.return_value = 0x80100001  # error
        card_type, size = _detect_card_type_from_atr(mock_winscard, mock_hCard)
        assert card_type == "SLE4442"
        assert size == 256


class TestBackwardCompatibility:
    def test_read_sle4428_alias_exists(self):
        """read_sle4428 should be an alias for read_sync_card."""
        from kvk_reader.card.omnikey_sync import read_sle4428, read_sync_card
        assert read_sle4428 is read_sync_card


class TestOmnikeySyncError:
    def test_error_message(self):
        err = OmnikeySyncError("Test-Fehler")
        assert "Test-Fehler" in str(err)

    def test_is_exception(self):
        assert issubclass(OmnikeySyncError, Exception)
