"""Settings dialog for reader, printer, practice, and API configuration."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QCheckBox,
    QComboBox,
    QPushButton,
    QDialogButtonBox,
    QHBoxLayout,
)
from PyQt5.QtCore import QSettings

from kvk_reader.config import APP_NAME, ORG_NAME, DEFAULTS, CT_API_DLLS


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(480)
        self._settings = QSettings(ORG_NAME, APP_NAME)

        layout = QVBoxLayout()

        # --- Kartenleser ---
        reader_group = QGroupBox("Kartenleser")
        reader_form = QFormLayout()

        reader_row = QHBoxLayout()
        self._reader_combo = QComboBox()
        self._reader_combo.setMinimumWidth(250)
        self._reader_combo.addItem("(Wird gesucht...)")
        reader_row.addWidget(self._reader_combo, stretch=1)

        self._btn_refresh_readers = QPushButton("Aktualisieren")
        self._btn_refresh_readers.clicked.connect(self._refresh_readers)
        reader_row.addWidget(self._btn_refresh_readers)

        reader_form.addRow("Kartenleser:", reader_row)

        # CT-API DLL for KVK/PKV memory cards
        ctapi_row = QHBoxLayout()
        self._ctapi_dll = QLineEdit(self._get("reader/ct_api_dll"))
        self._ctapi_dll.setPlaceholderText("z.B. ctpcsc32.dll (leer = nur PC/SC)")
        self._ctapi_dll.setToolTip(
            "CT-API DLL für KVK/PKV-Speicherkarten.\n"
            "Leer lassen = nur PC/SC (funktioniert nur mit kompatiblen Lesern).\n"
            "Die DLL muss im System-Pfad oder neben der EXE liegen."
        )
        ctapi_row.addWidget(self._ctapi_dll, stretch=1)

        self._btn_ctapi_select = QPushButton("Auswählen...")
        self._btn_ctapi_select.clicked.connect(self._select_ctapi_dll)
        ctapi_row.addWidget(self._btn_ctapi_select)

        reader_form.addRow("CT-API DLL (KVK):", ctapi_row)

        # Preset combo for known DLLs
        self._ctapi_preset = QComboBox()
        self._ctapi_preset.addItem("-- Bekannte DLLs --")
        for label, dll_name in CT_API_DLLS.items():
            self._ctapi_preset.addItem(f"{label} ({dll_name})", dll_name)
        self._ctapi_preset.currentIndexChanged.connect(self._on_ctapi_preset_changed)
        reader_form.addRow("Hersteller-Vorlage:", self._ctapi_preset)

        self._ctapi_pn = QSpinBox()
        self._ctapi_pn.setRange(0, 255)
        self._ctapi_pn.setValue(int(self._get("reader/ct_api_pn")))
        self._ctapi_pn.setToolTip("CT-API Port-Nummer (herstellerspezifisch, meist 1)")
        reader_form.addRow("CT-API Port-Nr.:", self._ctapi_pn)

        reader_group.setLayout(reader_form)
        layout.addWidget(reader_group)

        # --- Praxisdaten ---
        praxis_group = QGroupBox("Praxisdaten (Etikett Zeile 4)")
        praxis_form = QFormLayout()
        self._bsnr = QLineEdit(self._get("praxis/bsnr"))
        self._bsnr.setPlaceholderText("z.B. 123456789")
        self._bsnr.setMaxLength(9)
        praxis_form.addRow("Betriebsstätten-Nr. (BSNR):", self._bsnr)

        self._lanr = QLineEdit(self._get("praxis/lanr"))
        self._lanr.setPlaceholderText("z.B. 987654321")
        self._lanr.setMaxLength(9)
        praxis_form.addRow("Arzt-Nr. (LANR):", self._lanr)
        praxis_group.setLayout(praxis_form)
        layout.addWidget(praxis_group)

        # --- Drucker ---
        printer_group = QGroupBox("Etikettendrucker")
        printer_form = QFormLayout()

        printer_uri_row = QHBoxLayout()
        self._printer_uri = QLineEdit(self._get("printer/uri"))
        self._printer_uri.setPlaceholderText("usb://0x04F9:0x209B")
        printer_uri_row.addWidget(self._printer_uri, stretch=1)

        self._btn_detect_printer = QPushButton("Erkennen")
        self._btn_detect_printer.clicked.connect(self._detect_printer)
        printer_uri_row.addWidget(self._btn_detect_printer)

        printer_form.addRow("Drucker-URI:", printer_uri_row)

        self._printer_model = QLineEdit(self._get("printer/model"))
        printer_form.addRow("Druckermodell:", self._printer_model)

        self._copies = QSpinBox()
        self._copies.setRange(1, 20)
        self._copies.setValue(int(self._get("label/copies_default")))
        printer_form.addRow("Standard-Kopien:", self._copies)
        printer_group.setLayout(printer_form)
        layout.addWidget(printer_group)

        # --- API ---
        api_group = QGroupBox("REST API")
        api_form = QFormLayout()
        self._api_enabled = QCheckBox("API aktivieren")
        self._api_enabled.setChecked(self._get_bool("api/enabled"))
        api_form.addRow(self._api_enabled)

        self._api_port = QSpinBox()
        self._api_port.setRange(1024, 65535)
        self._api_port.setValue(int(self._get("api/port")))
        api_form.addRow("API Port:", self._api_port)
        api_group.setLayout(api_form)
        layout.addWidget(api_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

        # Initial reader discovery
        self._refresh_readers()

    def _get(self, key: str) -> str:
        return str(self._settings.value(key, DEFAULTS.get(key, "")))

    def _get_bool(self, key: str) -> bool:
        val = self._settings.value(key, DEFAULTS.get(key, True))
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def _refresh_readers(self):
        """Discover PC/SC card readers and populate the combo box."""
        self._reader_combo.clear()
        try:
            from kvk_reader.card.card_detector import CardReaderWorker

            worker = CardReaderWorker()
            names = worker.discover_readers()
            if names:
                for name in names:
                    self._reader_combo.addItem(name)
                # Select previously saved reader
                saved_index = int(self._get("reader/index"))
                if saved_index < len(names):
                    self._reader_combo.setCurrentIndex(saved_index)
            else:
                self._reader_combo.addItem("(Kein Kartenleser gefunden)")
        except Exception:
            self._reader_combo.addItem("(pyscard nicht verfügbar)")

    def _select_ctapi_dll(self):
        """Open file dialog to select CT-API DLL."""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "CT-API DLL auswählen",
            "",
            "DLL-Dateien (*.dll);;Alle Dateien (*)",
        )
        if path:
            self._ctapi_dll.setText(path)

    def _on_ctapi_preset_changed(self, index: int):
        """Fill DLL name from preset combo."""
        if index > 0:
            dll_name = self._ctapi_preset.itemData(index)
            if dll_name:
                self._ctapi_dll.setText(dll_name)

    def _detect_printer(self):
        """Try to detect Brother QL USB printers."""
        try:
            from kvk_reader.printer.label_printer import list_usb_printers

            printers = list_usb_printers()
            if printers:
                self._printer_uri.setText(printers[0])
            else:
                self._printer_uri.setPlaceholderText("Kein Drucker gefunden")
        except Exception:
            self._printer_uri.setPlaceholderText("brother_ql nicht verfügbar")

    def _save_and_accept(self):
        self._settings.setValue("reader/index", self._reader_combo.currentIndex())
        self._settings.setValue("reader/ct_api_dll", self._ctapi_dll.text().strip())
        self._settings.setValue("reader/ct_api_pn", self._ctapi_pn.value())
        self._settings.setValue("praxis/bsnr", self._bsnr.text())
        self._settings.setValue("praxis/lanr", self._lanr.text())
        self._settings.setValue("printer/uri", self._printer_uri.text())
        self._settings.setValue("printer/model", self._printer_model.text())
        self._settings.setValue("label/copies_default", self._copies.value())
        self._settings.setValue("api/enabled", self._api_enabled.isChecked())
        self._settings.setValue("api/port", self._api_port.value())
        self.accept()
