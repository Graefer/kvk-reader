"""Main application window."""

from __future__ import annotations

import logging
import os
import sys
from datetime import date

from PyQt5.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QToolBar,
    QStatusBar,
    QLabel,
    QMessageBox,
    QSpinBox,
    QAction,
    QSplitter,
    QSystemTrayIcon,
    QMenu,
    QApplication,
)
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtCore import QSettings, QTimer, Qt, pyqtSlot

from kvk_reader.config import APP_NAME, APP_VERSION, ORG_NAME, DEFAULTS
from kvk_reader.card.models import PatientData
from kvk_reader.core.label_service import patient_from_dict
from kvk_reader.storage import PatientStorage
from kvk_reader.gui.patient_history_table import PatientHistoryTable
from kvk_reader.gui.label_preview import LabelPreview
from kvk_reader.gui.settings_dialog import SettingsDialog
from kvk_reader.gui.settings_bridge import sync_qsettings_to_json
from kvk_reader.gui.card_worker import CardReadThread, ReaderDiscoveryThread
from kvk_reader.printer.label_printer import print_label, PrinterError

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with toolbar, history table, and label preview."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(640, 480)

        self._settings = QSettings(ORG_NAME, APP_NAME)
        self._current_patient: PatientData | None = None
        self._card_thread: CardReadThread | None = None
        self._discovery_thread: ReaderDiscoveryThread | None = None
        self._reader_names: list[str] = []
        self._storage = PatientStorage()
        self._api_server = None   # set by app.py after start
        self._api_context = None  # set by app.py, keeps the REST API in sync

        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_tray()

        # Restore saved window geometry — ignore if from older version
        _GEO_VERSION = "5"
        geometry = self._settings.value("window/geometry")
        geo_version = self._settings.value("window/geometry_version", "")
        if geometry and geo_version == _GEO_VERSION:
            self.restoreGeometry(geometry)
            if self.width() < 1000 or self.height() < 600:
                self._resize_to_screen()
            splitter_state = self._settings.value("window/splitter")
            if splitter_state:
                self._splitter.restoreState(splitter_state)
        else:
            # Clear stale saved state from older version
            self._settings.remove("window/geometry")
            self._settings.remove("window/splitter")
            self._resize_to_screen()
            self._settings.setValue("window/geometry_version", _GEO_VERSION)
            # Defer splitter sizing until layout is complete
            QTimer.singleShot(0, self._apply_initial_splitter)

        # Load history from DB
        self._refresh_history()

        # Discover readers after GUI is shown
        QTimer.singleShot(500, self._discover_readers)

        # Periodically re-discover so a reader plugged in after startup
        # is picked up and the status bar stays in sync with reality.
        self._reader_poll_timer = QTimer(self)
        self._reader_poll_timer.setInterval(3000)
        self._reader_poll_timer.timeout.connect(self._discover_readers)
        self._reader_poll_timer.start()

    def _resize_to_screen(self):
        """Resize window to fit screen — max 1400x825 or screen size minus margins."""
        screen = QApplication.desktop().availableGeometry()
        w = min(1400, screen.width() - 40)
        h = min(825, screen.height() - 80)
        self.resize(w, h)
        log.info("Window resized to %dx%d (screen: %dx%d)", w, h, screen.width(), screen.height())

    def _apply_initial_splitter(self):
        """Set initial splitter sizes: 50% table, 50% preview."""
        total = self._splitter.height()
        if total > 100:
            table_h = total * 50 // 100
            preview_h = total - table_h
            self._splitter.setSizes([table_h, preview_h])
            log.info("Splitter sizes: table=%d, preview=%d", table_h, preview_h)
        # Also apply column widths now that the table has its final width
        self._history_table.apply_column_widths()

    def _setup_ui(self):
        central = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        # Splitter: history table (top) | label preview (bottom)
        splitter = QSplitter(Qt.Vertical)

        self._history_table = PatientHistoryTable()
        self._history_table.patient_selected.connect(self._on_patient_selected)
        splitter.addWidget(self._history_table)

        self._preview = LabelPreview()
        splitter.addWidget(self._preview)

        # Default sizes: table gets 60%, preview gets 40%
        splitter.setStretchFactor(0, 60)
        splitter.setStretchFactor(1, 40)

        self._splitter = splitter
        # Splitter state restored later in __init__ after geometry check

        layout.addWidget(splitter)
        central.setLayout(layout)
        self.setCentralWidget(central)

    def _setup_toolbar(self):
        toolbar = QToolBar("Aktionen")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Karte lesen
        self._action_read = QAction("Karte lesen", self)
        self._action_read.setShortcut(QKeySequence("F5"))
        self._action_read.setToolTip("Karte lesen (F5)")
        self._action_read.triggered.connect(self._on_read_card)
        toolbar.addAction(self._action_read)

        toolbar.addSeparator()

        # Drucken
        self._action_print = QAction("Drucken", self)
        self._action_print.setShortcut(QKeySequence("F6"))
        self._action_print.setToolTip("Etikett drucken (F6)")
        self._action_print.triggered.connect(self._on_print)
        toolbar.addAction(self._action_print)

        # Kopienanzahl
        self._copies_spin = QSpinBox()
        self._copies_spin.setRange(1, 20)
        self._copies_spin.setValue(DEFAULTS["label/copies_default"])
        self._copies_spin.setToolTip("Anzahl Kopien")
        self._copies_spin.setPrefix("x ")
        self._copies_spin.setFixedWidth(70)
        toolbar.addWidget(self._copies_spin)

        toolbar.addSeparator()

        # Löschen
        self._action_delete = QAction("Löschen", self)
        self._action_delete.setShortcut(QKeySequence("Delete"))
        self._action_delete.setToolTip("Ausgewählten Datensatz löschen (Entf)")
        self._action_delete.triggered.connect(self._on_delete)
        toolbar.addAction(self._action_delete)

        toolbar.addSeparator()

        # Einstellungen
        action_settings = QAction("Einstellungen", self)
        action_settings.setShortcut(QKeySequence("Ctrl+,"))
        action_settings.triggered.connect(self._on_settings)
        toolbar.addAction(action_settings)

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_reader = QLabel("Kartenleser: --")
        self._status_api = QLabel("")
        self._statusbar.addWidget(self._status_reader, stretch=1)
        self._statusbar.addPermanentWidget(self._status_api)

    # --- System Tray ---

    def _setup_tray(self):
        """Set up system tray icon with context menu."""
        self._tray = QSystemTrayIcon(self)

        # Find icon file (bundled assets or development path)
        icon_path = None
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icons", "app_icon.png"),
        ]
        if getattr(sys, "frozen", False):
            candidates.insert(0, os.path.join(sys._MEIPASS, "assets", "icons", "app_icon.png"))

        for p in candidates:
            p = os.path.normpath(p)
            if os.path.isfile(p):
                icon_path = p
                break

        if icon_path:
            icon = QIcon(icon_path)
            self._tray.setIcon(icon)
            self.setWindowIcon(icon)
        else:
            # Fallback: use application icon
            self._tray.setIcon(self.style().standardIcon(self.style().SP_ComputerIcon))

        # Context menu
        tray_menu = QMenu()
        action_show = tray_menu.addAction("Öffnen")
        action_show.triggered.connect(self._tray_show)
        tray_menu.addSeparator()
        action_quit = tray_menu.addAction("Beenden")
        action_quit.triggered.connect(self._quit_app)
        self._tray.setContextMenu(tray_menu)

        self._tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        """Handle tray icon click — double-click opens window."""
        if reason == QSystemTrayIcon.DoubleClick:
            self._tray_show()

    def _tray_show(self):
        """Restore window from tray."""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self):
        """Actually quit the application (from tray menu)."""
        log.info("Application quit requested — cleaning up...")

        # Stop API server
        if self._api_server:
            try:
                self._api_server.stop()
            except Exception as e:
                log.warning("Error stopping API server: %s", e)

        # Wait for card read thread
        if self._card_thread and self._card_thread.isRunning():
            log.info("Waiting for card read thread...")
            self._card_thread.quit()
            self._card_thread.wait(3000)

        # Wait for reader discovery thread
        if self._discovery_thread and self._discovery_thread.isRunning():
            log.info("Waiting for discovery thread...")
            self._discovery_thread.quit()
            self._discovery_thread.wait(3000)

        self._really_quit = True
        QApplication.quit()

    def showEvent(self, event):
        """Apply deferred layout after window is shown for the first time."""
        super().showEvent(event)
        if not hasattr(self, "_shown_once"):
            self._shown_once = True
            # Defer so widget has its final layout dimensions
            QTimer.singleShot(50, self._history_table.apply_column_widths)

    def closeEvent(self, event):
        """Minimize to tray instead of closing."""
        # Always save window geometry and splitter state
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/splitter", self._splitter.saveState())

        if not hasattr(self, "_really_quit"):
            self._really_quit = False

        if self._really_quit:
            event.accept()
        else:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                APP_NAME,
                "Läuft im Hintergrund weiter. Doppelklick zum Öffnen.",
                QSystemTrayIcon.Information,
                2000,
            )

    # --- History ---

    def _refresh_history(self):
        """Reload the history table from the database."""
        records = self._storage.get_all()
        self._history_table.load_data(records)

    def _on_patient_selected(self, row_id: int):
        """User clicked a row in the history table."""
        rec = self._storage.get_by_id(row_id)
        if rec is None:
            return

        patient = patient_from_dict(rec)
        self._current_patient = patient
        self._publish_patient(patient)

        bsnr = str(self._settings.value("praxis/bsnr", ""))
        lanr = str(self._settings.value("praxis/lanr", ""))
        self._preview.update_preview(
            patient, bsnr=bsnr, lanr=lanr,
            datum=date.today().strftime("%d.%m.%Y"),
        )

        self._statusbar.showMessage(
            f"{patient.full_name} ({patient.card_type})", 3000
        )

    def _publish_patient(self, patient: PatientData | None):
        """Mirror the displayed patient into the API context.

        Without this, /api/patient would go stale whenever a card is read
        from the window rather than through the API. Listeners are skipped
        because the window is already showing this patient.
        """
        if self._api_context is not None:
            self._api_context.set_patient(patient, notify=False)

    # --- Public methods (called by API server, etc.) ---

    def set_patient_data(self, patient: PatientData | None):
        """Update the UI with new patient data."""
        self._current_patient = patient
        self._publish_patient(patient)

        bsnr = str(self._settings.value("praxis/bsnr", ""))
        lanr = str(self._settings.value("praxis/lanr", ""))
        self._preview.update_preview(
            patient, bsnr=bsnr, lanr=lanr,
            datum=date.today().strftime("%d.%m.%Y") if patient else None,
        )

        if patient:
            self._statusbar.showMessage(
                f"Karte gelesen: {patient.full_name} ({patient.card_type})", 5000
            )

    def set_api_status(self, url: str):
        """Show API status in the status bar."""
        self._status_api.setText(f"API: {url}")

    def set_reader_status(self, text: str):
        """Update card reader status in the status bar."""
        self._status_reader.setText(f"Kartenleser: {text}")

    @pyqtSlot(int)
    def _on_api_card_read(self, row_id: int):
        """Called from API thread (via QMetaObject) after a card read."""
        self.set_patient_data(self._current_patient)
        self._refresh_history()
        if row_id:
            self._history_table.highlight_new_row(row_id)
            self._history_table.select_row_by_id(row_id)

    # --- Card reader ---

    def _discover_readers(self):
        """Discover available PC/SC readers in a background thread."""
        # Skip if a previous discovery is still running (poll timer may fire
        # faster than pcsc responds).
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            return
        self._discovery_thread = ReaderDiscoveryThread()
        self._discovery_thread.readers_found.connect(self._on_readers_found)
        self._discovery_thread.discovery_error.connect(self._on_reader_discovery_error)
        self._discovery_thread.start()

    def _on_readers_found(self, names: list[str]):
        # Only log / update status on state change to avoid log spam from polling.
        changed = names != self._reader_names
        self._reader_names = names
        if self._api_context is not None:
            self._api_context.set_readers(names)
        if names:
            self.set_reader_status(names[0])
            if changed:
                log.info("Found %d reader(s): %s", len(names), names)
        else:
            self.set_reader_status("Kein Leser gefunden")
            if changed:
                log.info("No card readers found")

    def _on_reader_discovery_error(self, error: str):
        self.set_reader_status("pyscard nicht verfügbar")
        log.warning("Reader discovery error: %s", error)

    # --- Slots ---

    def _on_read_card(self):
        """Triggered by 'Karte lesen' button / F5."""
        if self._card_thread and self._card_thread.isRunning():
            self._statusbar.showMessage("Lesevorgang läuft bereits...", 2000)
            return

        reader_index = int(self._settings.value("reader/index", DEFAULTS["reader/index"]))

        self._action_read.setEnabled(False)
        self._statusbar.showMessage("Karte wird gelesen...", 0)

        ct_api_dll = str(self._settings.value("reader/ct_api_dll", DEFAULTS["reader/ct_api_dll"]))
        ct_api_pn = int(self._settings.value("reader/ct_api_pn", DEFAULTS["reader/ct_api_pn"]))

        self._card_thread = CardReadThread(
            reader_index=reader_index,
            ct_api_dll=ct_api_dll,
            ct_api_pn=ct_api_pn,
        )
        self._card_thread.card_read.connect(self._on_card_read_success)
        self._card_thread.read_error.connect(self._on_card_read_error)
        self._card_thread.finished.connect(lambda: self._action_read.setEnabled(True))
        self._card_thread.start()

    def _on_card_read_success(self, patient: PatientData):
        """Card was read successfully — save and update UI."""
        # Auto-save to DB
        try:
            row_id = self._storage.save(patient)
        except Exception as e:
            log.error("Fehler beim Speichern: %s", e)

        # Update preview with new patient
        self.set_patient_data(patient)

        # Refresh history table, highlight and select the new entry
        self._refresh_history()
        try:
            self._history_table.highlight_new_row(row_id)
            self._history_table.select_row_by_id(row_id)
        except Exception:
            pass

    def _on_card_read_error(self, error: str):
        # Show first line only in status bar
        first_line = error.split("\n")[0] if "\n" in error else error
        self._statusbar.showMessage(f"Lesefehler: {first_line}", 10000)
        log.error("Card read error: %s", error)

        # Show detailed error dialog for read failures
        if "Alle Strategien" in error or "\n" in error:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("KVK-Karte Lesefehler")
            msg.setText("Die KVK-Karte konnte nicht gelesen werden.")
            msg.setDetailedText(error)
            msg.exec()
        elif "nicht" not in error.lower() and "kein" not in error.lower():
            QMessageBox.warning(self, "Kartenfehler", error)

    def _on_print(self):
        """Print the current label."""
        img = self._preview.get_print_image()
        if img is None:
            QMessageBox.warning(self, "Drucken", "Keine Kartendaten zum Drucken vorhanden.")
            return

        copies = self._copies_spin.value()
        uri = str(self._settings.value("printer/uri", DEFAULTS["printer/uri"]))
        model = str(self._settings.value("printer/model", DEFAULTS["printer/model"]))

        try:
            print_label(img, printer_uri=uri, printer_model=model, copies=copies)
            self._statusbar.showMessage(f"{copies}x Etikett gedruckt", 3000)
        except PrinterError as e:
            QMessageBox.critical(self, "Druckfehler", str(e))

    def _on_delete(self):
        """Delete the currently selected patient from the history."""
        selected = self._history_table.selectedItems()
        if not selected:
            self._statusbar.showMessage("Kein Datensatz ausgewählt.", 2000)
            return

        row = selected[0].row()
        row_id = self._history_table._row_ids[row] if row < len(self._history_table._row_ids) else None
        if row_id is None:
            return

        # Get patient name for confirmation
        name = self._history_table.item(row, 0).text()  # Nachname
        vorname = self._history_table.item(row, 1).text()  # Vorname

        reply = QMessageBox.question(
            self,
            "Datensatz löschen",
            f"{name}, {vorname} wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._storage.delete(row_id)
        self._current_patient = None
        self._preview.update_preview(None)
        self._refresh_history()
        self._statusbar.showMessage(f"{name}, {vorname} gelöscht.", 3000)

    def _on_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            # Keep the REST API on the same practice data as the window
            sync_qsettings_to_json()
            # Re-render preview with updated practice data
            if self._current_patient:
                self.set_patient_data(self._current_patient)
            # Re-discover readers in case settings changed
            self._discover_readers()
