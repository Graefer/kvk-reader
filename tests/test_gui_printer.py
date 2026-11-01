"""Tests for choosing the Windows printer in the desktop window (--gui).

Run offscreen (QT_QPA_PLATFORM=offscreen). QSettings points at a throwaway
INI file and the printer list is faked, so nothing touches the registry,
a card reader or a printer.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import QSettings  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from kvk_reader.gui import settings_dialog  # noqa: E402
from kvk_reader.gui.main_window import MainWindow  # noqa: E402

FAKE_PRINTERS = ["Brother QL-810W", "HP LaserJet"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ini_settings(tmp_path):
    path = str(tmp_path / "kvk.ini")
    return lambda *args: QSettings(path, QSettings.IniFormat)


@pytest.fixture
def open_dialog(qapp, ini_settings):
    """Factory: open the settings dialog with a faked printer list."""
    patches = [
        patch.object(settings_dialog, "QSettings", ini_settings),
        patch("kvk_reader.printer.label_printer.list_windows_printers",
              return_value=FAKE_PRINTERS),
        patch("kvk_reader.card.card_detector.CardReaderWorker",
              return_value=MagicMock(discover_readers=lambda: [])),
    ]
    for p in patches:
        p.start()
    yield settings_dialog.SettingsDialog
    for p in reversed(patches):
        p.stop()


def saved_name(ini_settings):
    return ini_settings().value("printer/name")


class TestSettingsDialogPrinter:
    def test_auto_is_default_and_saves_empty(self, open_dialog, ini_settings):
        dialog = open_dialog()
        combo = dialog._printer_name
        assert combo.currentText() == settings_dialog._AUTO_PRINTER
        assert [combo.itemText(i) for i in range(combo.count())] == [
            settings_dialog._AUTO_PRINTER, *FAKE_PRINTERS,
        ]
        dialog._save_and_accept()
        assert saved_name(ini_settings) == ""

    def test_saves_selected_printer(self, open_dialog, ini_settings):
        dialog = open_dialog()
        dialog._printer_name.setCurrentText("HP LaserJet")
        dialog._save_and_accept()
        assert saved_name(ini_settings) == "HP LaserJet"
        assert open_dialog()._printer_name.currentText() == "HP LaserJet"

    def test_keeps_saved_name_not_listed(self, open_dialog, ini_settings):
        ini_settings().setValue("printer/name", "Etikettendrucker WLAN")
        dialog = open_dialog()
        assert dialog._printer_name.currentText() == "Etikettendrucker WLAN"
        dialog._refresh_printers()
        assert dialog._printer_name.currentText() == "Etikettendrucker WLAN"
        dialog._save_and_accept()
        assert saved_name(ini_settings) == "Etikettendrucker WLAN"


class TestMainWindowPrint:
    def test_passes_configured_printer_name(self):
        stored = {"printer/name": "Brother QL-810W (WLAN)"}
        window = SimpleNamespace(
            _preview=MagicMock(),
            _copies_spin=MagicMock(value=lambda: 2),
            _settings=MagicMock(value=lambda key, default=None: stored.get(key, default)),
            _statusbar=MagicMock(),
        )
        with patch("kvk_reader.gui.main_window.print_label") as mock_print:
            MainWindow._on_print(window)

        kwargs = mock_print.call_args.kwargs
        assert kwargs["printer_name"] == "Brother QL-810W (WLAN)"
        assert kwargs["copies"] == 2
