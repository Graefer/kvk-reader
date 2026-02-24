"""Application setup and entry point."""

from __future__ import annotations

import logging
import os
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QSettings

from kvk_reader.config import APP_NAME, ORG_NAME, DEFAULTS

log = logging.getLogger(__name__)

_SOCKET_NAME = "KVKReader-SingleInstance"


def _init_logging():
    """Configure logging to console and log file.

    Log file is written next to the executable / script for easy access.
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_level = logging.INFO

    # Log file next to exe/script
    if getattr(sys, 'frozen', False):
        log_dir = os.path.dirname(sys.executable)
    else:
        log_dir = os.getcwd()

    log_file = os.path.join(log_dir, "kvk_reader.log")

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode='w', encoding='utf-8'),
    ]

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers,
    )

    logging.getLogger(__name__).info(
        "Logging konfiguriert: %s (Level: %s)", log_file, log_level
    )


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


def run_app() -> int:
    """Create and run the application."""
    _init_logging()

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
        port = int(settings.value("api/port", DEFAULTS["api/port"]))
        try:
            from kvk_reader.api.server import ApiServer

            api_server = ApiServer(window, port=port)
            api_server.start()
            window._api_server = api_server

            # Show LAN IP so other devices can reach the API
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = "localhost"
            window.set_api_status(f"http://{local_ip}:{port}")
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
