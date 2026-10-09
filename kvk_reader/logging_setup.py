"""Logging configuration shared by the GUI and the server.

The log file lives in the application data directory next to the database
and the configuration. That matters for server mode: as a scheduled task
the working directory is not writable by the service account.
"""

from __future__ import annotations

import logging
import os
import sys

from kvk_reader.paths import app_data_dir

_LOG_FILENAME = "kvk_reader.log"


def init_logging(level: int = logging.INFO) -> str:
    """Configure logging to stdout and to a rotating-by-run log file.

    Returns:
        Path of the log file.
    """
    log_file = os.path.join(app_data_dir(), _LOG_FILENAME)

    handlers: list[logging.Handler] = []
    # pythonw.exe has no usable stdout; guard against a None stream.
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    try:
        handlers.append(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    except OSError:
        pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    logging.getLogger(__name__).info("Logdatei: %s", log_file)
    return log_file


def local_ip() -> str:
    """Best-effort LAN address of this host, for printing a reachable URL."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        sock.close()
        return address
    except Exception:
        return "localhost"
