"""Table widget showing patient read history (last 250 entries)."""

from __future__ import annotations

import logging

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

log = logging.getLogger(__name__)

# Columns: (header label, dict key)
_COLUMNS = [
    ("Nachname", "nachname"),
    ("Vorname", "vorname"),
    ("Geb.-Datum", "geburtsdatum"),
    ("PLZ", "plz"),
    ("Krankenkasse", "krankenkasse_name"),
    ("Eingelesen", "einlesedatum"),
]

# Proportional column widths (sum < 1.0 to leave room for scrollbar)
# Nachname 17%, Vorname 10%, Geb.-Datum 12%, PLZ 7%, Krankenkasse 35%, Eingelesen 15%
_COL_RATIOS = [0.17, 0.10, 0.12, 0.07, 0.35, 0.15]


class PatientHistoryTable(QTableWidget):
    """Table showing stored patient reads with click-to-select.

    Emits ``patient_selected(int)`` with the database row id when
    the user clicks a row.
    """

    patient_selected = pyqtSignal(int)  # emits DB row id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(_COLUMNS))
        self.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(False)

        # All columns Interactive — widths set proportionally in apply_column_widths
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for i in range(len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.Interactive)

        # Row IDs stored per row
        self._row_ids: list[int] = []

        self.cellClicked.connect(self._on_cell_clicked)

    def apply_column_widths(self):
        """Calculate and set column widths proportional to available width."""
        available = self.viewport().width()
        if available < 100:
            available = 1200  # fallback before widget is shown
        header = self.horizontalHeader()
        for i, ratio in enumerate(_COL_RATIOS):
            w = max(40, int(available * ratio))
            header.resizeSection(i, w)
        log.info(
            "Column widths (avail=%d): %s",
            available,
            [header.sectionSize(i) for i in range(len(_COLUMNS))],
        )

    def load_data(self, records: list[dict]):
        """Populate the table from a list of storage dicts (newest first)."""
        self.setRowCount(0)
        self._row_ids.clear()

        self.setRowCount(len(records))
        for i, rec in enumerate(records):
            self._row_ids.append(rec.get("id", 0))
            for j, (_, key) in enumerate(_COLUMNS):
                value = rec.get(key, "") or ""
                # Convert old ISO format to hh:mm, dd.mm.yyyy if needed
                if key == "einlesedatum" and "T" in value:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(value)
                        value = dt.strftime("%H:%M, %d.%m.%Y")
                    except (ValueError, TypeError):
                        value = value.replace("T", " ")[:16]
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.setItem(i, j, item)

        # Re-apply after data load (Qt may reset widths when rows are added)
        self.apply_column_widths()

    def select_row_by_id(self, row_id: int):
        """Select (highlight) the row with the given DB id."""
        if row_id in self._row_ids:
            row_index = self._row_ids.index(row_id)
            self.selectRow(row_index)

    def highlight_new_row(self, row_id: int):
        """Briefly highlight a newly created row with a green background."""
        if row_id not in self._row_ids:
            return
        row_index = self._row_ids.index(row_id)
        highlight = QColor(200, 240, 200)  # light green
        for col in range(self.columnCount()):
            item = self.item(row_index, col)
            if item:
                item.setBackground(highlight)
        # Remove highlight after 5 seconds
        QTimer.singleShot(5000, lambda: self._clear_row_highlight(row_index))

    def _clear_row_highlight(self, row_index: int):
        """Reset row background to default."""
        if row_index >= self.rowCount():
            return
        for col in range(self.columnCount()):
            item = self.item(row_index, col)
            if item:
                item.setBackground(QColor(0, 0, 0, 0))  # transparent = default

    def _on_cell_clicked(self, row: int, _col: int):
        if 0 <= row < len(self._row_ids):
            self.patient_selected.emit(self._row_ids[row])
