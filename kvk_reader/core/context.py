"""Shared application state for the REST API and the web UI.

This is the Qt-free replacement for the state that used to live in the
main window: the last card read, the reader list and the patient history.
The GUI can register a listener so it stays in sync when a card is read
through the API.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

from kvk_reader.card.models import PatientData
from kvk_reader.settings import Settings, get_settings
from kvk_reader.storage import PatientStorage

log = logging.getLogger(__name__)

# How often the reader list is refreshed so a reader plugged in after
# startup shows up without restarting the server.
_READER_POLL_SECONDS = 5.0


class AppContext:
    """Holds application state shared across HTTP requests.

    A single card reader is a shared resource, so every read is serialized
    through one lock — two browsers clicking "Karte lesen" at the same
    moment must not talk to PC/SC concurrently.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        storage: PatientStorage | None = None,
    ):
        self._settings = settings or get_settings()
        self._storage = storage or PatientStorage()

        self._state_lock = threading.Lock()
        self._read_lock = threading.Lock()

        self._current_patient: Optional[PatientData] = None
        self._last_read_at: str = ""
        self._reader_names: List[str] = []
        self._reader_error: str = ""

        self._listeners: List[Callable[[PatientData, Optional[int]], None]] = []

        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

    # --- properties -----------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def storage(self) -> PatientStorage:
        return self._storage

    @property
    def current_patient(self) -> Optional[PatientData]:
        with self._state_lock:
            return self._current_patient

    @property
    def last_read_at(self) -> str:
        with self._state_lock:
            return self._last_read_at

    @property
    def reader_names(self) -> List[str]:
        with self._state_lock:
            return list(self._reader_names)

    @property
    def reader_error(self) -> str:
        with self._state_lock:
            return self._reader_error

    # --- patient state --------------------------------------------------

    def add_listener(self, callback: Callable[[PatientData, Optional[int]], None]):
        """Register a callback invoked after a card was read via the API.

        Used by the GUI to update its widgets. Exceptions raised by a
        listener are logged and swallowed so they cannot break a request.
        """
        self._listeners.append(callback)

    def set_patient(
        self,
        patient: Optional[PatientData],
        row_id: int | None = None,
        notify: bool = True,
    ):
        """Store the most recently read patient.

        Args:
            patient: The patient, or None to clear.
            row_id: Database row id, passed on to listeners.
            notify: Whether to invoke listeners. The GUI sets this to False
                when it pushes its own reads in, to avoid a feedback loop.
        """
        with self._state_lock:
            self._current_patient = patient
            if patient is not None:
                self._last_read_at = patient.read_timestamp

        if notify and patient is not None:
            for callback in self._listeners:
                try:
                    callback(patient, row_id)
                except Exception as e:
                    log.error("Listener-Fehler nach Kartenlesung: %s", e)

    def read_card(self) -> tuple[PatientData, Optional[int]]:
        """Read a card from the configured reader and store the result.

        Returns:
            Tuple of the patient data and the database row id (None if the
            record could not be saved).

        Raises:
            RuntimeError: If no reader is present, no card is inserted, or
                the read fails. The message is suitable for display.
        """
        from kvk_reader.card.card_detector import CardReaderWorker

        try:
            import smartcard  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "pyscard ist nicht installiert — ohne diese Bibliothek kann "
                "kein Kartenleser angesprochen werden. "
                "Installation: pip install pyscard"
            ) from e

        reader_index = self._settings.get_int("reader/index", 0)
        ct_api_dll = self._settings.get_str("reader/ct_api_dll")
        ct_api_pn = self._settings.get_int("reader/ct_api_pn", 1)

        worker = CardReaderWorker(ct_api_dll=ct_api_dll, ct_api_pn=ct_api_pn)

        with self._read_lock:
            patient = worker.read_from_reader(reader_index)

        row_id = self.store(patient)
        self.set_patient(patient, row_id)
        return patient, row_id

    def store(self, patient: PatientData) -> Optional[int]:
        """Save a patient to the history, returning the row id.

        A failing history write must not fail the card read itself, so
        errors are logged and reported as a missing row id.
        """
        try:
            return self._storage.save(patient)
        except Exception as e:
            log.error("Speichern in der Historie fehlgeschlagen: %s", e)
            return None

    # --- readers --------------------------------------------------------

    def discover_readers(self) -> List[str]:
        """Query the reader list synchronously and update the cached state."""
        from kvk_reader.card.card_detector import CardReaderWorker

        try:
            names = CardReaderWorker().discover_readers()
            error = ""
        except Exception as e:
            names = []
            error = str(e)
            log.error("Kartenleser-Suche fehlgeschlagen: %s", e)

        with self._state_lock:
            changed = names != self._reader_names
            self._reader_names = names
            self._reader_error = error

        if changed:
            log.info("Kartenleser: %s", ", ".join(names) if names else "keine gefunden")
        return names

    def set_readers(self, names: List[str]):
        """Publish a reader list discovered elsewhere.

        In GUI mode the window already polls for readers; it pushes the
        result here instead of a second poller querying PC/SC in parallel.
        """
        with self._state_lock:
            self._reader_names = list(names)
            self._reader_error = ""

    def start_reader_polling(self):
        """Start the background thread that refreshes the reader list."""
        if self._poll_thread is not None:
            return

        self._poll_thread = threading.Thread(
            target=self._poll_readers,
            daemon=True,
            name="reader-poll",
        )
        self._poll_thread.start()

    def _poll_readers(self):
        while not self._stop_event.is_set():
            self.discover_readers()
            self._stop_event.wait(_READER_POLL_SECONDS)

    def stop(self):
        """Stop background activity."""
        self._stop_event.set()
