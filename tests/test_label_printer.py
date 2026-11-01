"""Tests for Windows printer discovery (win32print is faked)."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

from kvk_reader.printer.label_printer import list_windows_printers


def _fake_win32print(names):
    return SimpleNamespace(
        PRINTER_ENUM_LOCAL=2,
        PRINTER_ENUM_CONNECTIONS=4,
        EnumPrinters=lambda flags: [(0, "", name, "") for name in names],
    )


class TestListWindowsPrinters:
    def test_lists_all_printers_brother_first(self):
        fake = _fake_win32print(["HP LaserJet", "Etikettendrucker", "Brother QL-820NWB"])
        with patch.dict(sys.modules, {"win32print": fake}):
            names = list_windows_printers()
        assert names == ["Brother QL-820NWB", "HP LaserJet", "Etikettendrucker"]

    def test_skips_redirected_rdp_printer(self):
        # The RDP copy uses "Microsoft Print To PDF" — choosing it would print into a file
        fake = _fake_win32print(["Brother QL-810W (umgeleitet 2)", "Brother QL-810W"])
        with patch.dict(sys.modules, {"win32print": fake}):
            assert list_windows_printers() == ["Brother QL-810W"]

    def test_without_pywin32_returns_empty(self):
        with patch.dict(sys.modules, {"win32print": None}):
            assert list_windows_printers() == []
