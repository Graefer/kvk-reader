"""Tests for the reader poll's shared PC/SC context."""

import sys
import types

import pytest

from kvk_reader.card import card_detector


class FakeScard(types.ModuleType):
    """Stand-in for smartcard.scard that records context handling."""

    SCARD_S_SUCCESS = 0
    SCARD_SCOPE_USER = 0
    SCARD_E_INVALID_HANDLE = 0x80100003
    SCARD_E_NO_SERVICE = 0x8010001D
    SCARD_E_SERVICE_STOPPED = 0x8010001E
    SCARD_E_NO_READERS_AVAILABLE = 0x8010002E

    def __init__(self):
        super().__init__("smartcard.scard")
        self.established = 0
        self.released = 0
        self.list_results = []

    def SCardEstablishContext(self, scope):
        self.established += 1
        return self.SCARD_S_SUCCESS, 100 + self.established

    def SCardListReaders(self, context, groups):
        return self.list_results.pop(0)

    def SCardReleaseContext(self, context):
        self.released += 1
        return self.SCARD_S_SUCCESS

    def SCardGetErrorMessage(self, hresult):
        return f"Fehler 0x{hresult:08X}"


@pytest.fixture
def scard(monkeypatch):
    fake = FakeScard()
    package = types.ModuleType("smartcard")
    package.scard = fake
    monkeypatch.setitem(sys.modules, "smartcard", package)
    monkeypatch.setitem(sys.modules, "smartcard.scard", fake)
    monkeypatch.setattr(card_detector, "_list_context", None)
    return fake


class TestListReaderNames:
    def test_reuses_one_context_across_polls(self, scard):
        reader = ["OMNIKEY CardMan 3x21 0"]
        scard.list_results = [(0, reader)] * 3

        for _ in range(3):
            assert card_detector.list_reader_names() == reader

        assert scard.established == 1
        assert scard.released == 0

    def test_no_readers_keeps_context(self, scard):
        scard.list_results = [(scard.SCARD_E_NO_READERS_AVAILABLE, [])] * 2

        assert card_detector.list_reader_names() == []
        assert card_detector.list_reader_names() == []
        assert scard.established == 1

    def test_stopped_service_rebuilds_context(self, scard):
        reader = ["OMNIKEY CardMan 3x21 0"]
        scard.list_results = [(0, reader), (scard.SCARD_E_SERVICE_STOPPED, []), (0, reader)]

        assert card_detector.list_reader_names() == reader
        assert card_detector.list_reader_names() == []
        assert card_detector.list_reader_names() == reader
        assert scard.established == 2
        assert scard.released == 1

    def test_invalid_handle_raises_and_rebuilds(self, scard):
        scard.list_results = [(scard.SCARD_E_INVALID_HANDLE, []), (0, ["R"])]

        with pytest.raises(RuntimeError):
            card_detector.list_reader_names()
        assert card_detector.list_reader_names() == ["R"]
        assert scard.established == 2

    def test_missing_service_returns_empty(self, scard, monkeypatch):
        monkeypatch.setattr(
            scard, "SCardEstablishContext", lambda scope: (scard.SCARD_E_NO_SERVICE, 0)
        )
        assert card_detector.list_reader_names() == []
        assert card_detector._list_context is None
