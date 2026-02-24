"""QTableWidget for displaying patient card data."""

from __future__ import annotations

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PyQt5.QtCore import Qt

from kvk_reader.card.models import PatientData

# Fields to display: (label, accessor)
_FIELDS = [
    ("Kartentyp", lambda p: p.card_type),
    ("Name", lambda p: p.full_name),
    ("Geburtsdatum", lambda p: p.geburtsdatum),
    ("Geschlecht", lambda p: p.geschlecht),
    ("Adresse", lambda p: f"{p.strasse} {p.hausnummer}".strip() if p.strasse else ""),
    ("PLZ / Ort", lambda p: f"{p.plz} {p.ort}".strip()),
    ("Krankenkasse", lambda p: p.krankenkasse_name),
    ("Kostenträger-Nr.", lambda p: p.krankenkassen_nummer),
    ("Versicherten-Nr.", lambda p: p.versichertennummer),
    ("Status", lambda p: p.versichertenstatus),
    ("Versichertenart", lambda p: _versichertenart_text(p.versichertenart)),
    ("Gültig bis", lambda p: p.gueltig_bis),
]

_VERSICHERTENART_MAP = {
    "1": "1 (Mitglied)",
    "3": "3 (Familienvers.)",
    "5": "5 (Rentner)",
}


def _versichertenart_text(art: str) -> str:
    return _VERSICHERTENART_MAP.get(art, art)


class CardDataTable(QTableWidget):
    """Table widget showing patient data fields and values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Feld", "Wert"])
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        self._clear_table()

    def _clear_table(self):
        self.setRowCount(len(_FIELDS))
        for i, (label, _) in enumerate(_FIELDS):
            item = QTableWidgetItem(label)
            item.setFlags(Qt.ItemIsEnabled)
            self.setItem(i, 0, item)
            self.setItem(i, 1, QTableWidgetItem(""))

    def update_data(self, patient: PatientData | None):
        """Update table with patient data, or clear if None."""
        if patient is None:
            self._clear_table()
            return

        for i, (label, accessor) in enumerate(_FIELDS):
            value = accessor(patient) or ""
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.setItem(i, 1, item)
