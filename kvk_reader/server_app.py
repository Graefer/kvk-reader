"""Headless server mode — REST API and web UI without Qt.

This is the default entry point in 2.0: the card reader sits on this
machine, and every workstation operates it through a browser.
"""

from __future__ import annotations

import logging
import signal
import threading

from kvk_reader.config import APP_VERSION
from kvk_reader.logging_setup import init_logging, local_ip
from kvk_reader.settings import get_settings

log = logging.getLogger(__name__)


def run_server(port: int | None = None) -> int:
    """Run the server in the foreground until interrupted.

    Args:
        port: TCP port; defaults to the configured ``api/port``.

    Returns:
        Process exit code.
    """
    init_logging()

    from kvk_reader.api.server import ApiServer
    from kvk_reader.core.context import AppContext

    settings = get_settings()
    port = port or settings.get_int("api/port", 8899)

    context = AppContext(settings=settings)
    context.start_reader_polling()

    server = ApiServer(context, port=port)

    def shutdown(signum, frame):
        log.info("Signal %s empfangen, fahre herunter…", signum)
        # shutdown() blocks until serve_forever() returns, and the handler
        # runs in the very thread that is serving — calling it directly
        # deadlocks. Hand it to a separate thread instead.
        threading.Thread(target=server.stop, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, shutdown)
        except (ValueError, AttributeError, OSError):
            # Not available on every platform/thread — Ctrl+C still works.
            pass

    log.info("KVK/eGK Reader %s — Serverbetrieb", APP_VERSION)
    log.info("Bedienoberfläche: http://%s:%d/", local_ip(), port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Abbruch durch Benutzer")
    finally:
        context.stop()

    return 0
