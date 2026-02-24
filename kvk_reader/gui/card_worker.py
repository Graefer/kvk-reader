"""QThread-based worker for non-blocking card reading operations."""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from kvk_reader.card.models import PatientData
from kvk_reader.card.card_detector import CardReaderWorker


class CardReadThread(QThread):
    """Background thread that reads a card and emits the result.

    Signals:
        card_read: Emitted with PatientData on successful read.
        read_error: Emitted with error message string on failure.
    """

    card_read = pyqtSignal(object)  # PatientData
    read_error = pyqtSignal(str)

    def __init__(
        self,
        reader_index: int = 0,
        ct_api_dll: str = "",
        ct_api_pn: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._reader_index = reader_index
        self._worker = CardReaderWorker(
            ct_api_dll=ct_api_dll,
            ct_api_pn=ct_api_pn,
        )

    def run(self):
        try:
            patient = self._worker.read_from_reader(self._reader_index)
            self.card_read.emit(patient)
        except Exception as e:
            self.read_error.emit(str(e))


class ReaderDiscoveryThread(QThread):
    """Background thread to discover available card readers."""

    readers_found = pyqtSignal(list)
    discovery_error = pyqtSignal(str)

    def run(self):
        try:
            worker = CardReaderWorker()
            names = worker.discover_readers()
            self.readers_found.emit(names)
        except Exception as e:
            self.discovery_error.emit(str(e))
