"""Application setup and entry point."""

from __future__ import annotations

import logging
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QSettings

from kvk_reader.config import APP_NAME, ORG_NAME, DEFAULTS
from kvk_reader.logging_setup import init_logging, local_ip

log = logging.getLogger(__name__)

_SOCKET_NAME = "KVKReader-SingleInstance"


def _init_settings():
    """Initialize default settings if not already set."""
    settings = QSettings(ORG_NAME, APP_NAME)
    for key, value in DEFAULTS.items():
        if settings.value(key) is None:
            settings.setValue(key, value)


def _check_single_instance() -> bool:
    """Return True if this is the first instance, False if another is running.

    Uses QLocalSocket — imported lazily to avoid loading QtNetwork DLLs
    at module level (can interfere with CT-API DLL loading on Win7).
    """
    try:
        from PyQt5.QtNetwork import QLocalSocket
    except ImportError:
        return True  # QtNetwork not available — skip check

    socket = QLocalSocket()
    socket.connectToServer(_SOCKET_NAME)
    if socket.waitForConnected(500):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return False
    return True


def _start_single_instance_server(window):
    """Start QLocalServer so subsequent launches bring this window up.

    Returns the server object (must be kept alive) or None.
    """
    try:
        from PyQt5.QtNetwork import QLocalServer
    except ImportError:
        return None

    QLocalServer.removeServer(_SOCKET_NAME)
    server = QLocalServer()
    server.listen(_SOCKET_NAME)

    def _on_new_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(300)
            conn.readAll()
            conn.disconnectFromServer()
            window._tray_show()

    server.newConnection.connect(_on_new_connection)
    return server


def _attach_api_server(window) -> None:
    """Start the REST API alongside the window and keep both in sync.

    The API runs on its own thread, so a card read arriving through HTTP
    has to hop back onto the Qt thread before touching any widget.
    """
    from PyQt5.QtCore import QMetaObject, Qt as QtConst, Q_ARG

    from kvk_reader.api.server import ApiServer
    from kvk_reader.core.context import AppContext
    from kvk_reader.gui.settings_bridge import sync_qsettings_to_json

    sync_qsettings_to_json()

    settings = QSettings(ORG_NAME, APP_NAME)
    port = int(settings.value("api/port", DEFAULTS["api/port"]))

    context = AppContext(storage=window._storage)

    def on_api_card_read(patient, row_id):
        window._current_patient = patient
        QMetaObject.invokeMethod(
            window, "_on_api_card_read",
            QtConst.QueuedConnection,
            Q_ARG(int, row_id or 0),
        )

    context.add_listener(on_api_card_read)
    window._api_context = context

    api_server = ApiServer(context, port=port)
    api_server.start()
    window._api_server = api_server

    window.set_api_status(f"http://{local_ip()}:{port}")


def run_app() -> int:
    """Create and run the application."""
    init_logging()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # Single-instance check: if already running, bring existing window to front
    if not _check_single_instance():
        return 0

    _init_settings()

    from kvk_reader.gui.main_window import MainWindow

    window = MainWindow()

    # Start API server if enabled
    settings = QSettings(ORG_NAME, APP_NAME)
    api_enabled = settings.value("api/enabled", DEFAULTS["api/enabled"])
    if isinstance(api_enabled, str):
        api_enabled = api_enabled.lower() in ("true", "1", "yes")

    if api_enabled:
        try:
            _attach_api_server(window)
        except Exception as e:
            log.error("API server failed to start: %s", e)
            window.set_api_status("API: Fehler")

    # Start single-instance server
    si_server = _start_single_instance_server(window)

    window.show()
    result = app.exec()

    if si_server:
        si_server.close()
        try:
            from PyQt5.QtNetwork import QLocalServer
            QLocalServer.removeServer(_SOCKET_NAME)
        except ImportError:
            pass
    return result
