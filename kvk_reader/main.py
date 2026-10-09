"""Application entry point.

Two modes:
  --server (default)  Headless REST API and web UI — no Qt required.
  --gui               The classic desktop window, needs the "gui" extra.

When running as a frozen PyInstaller EXE, any unhandled exception is
caught and written to kvk_reader_crash.log next to the executable.
This is critical because console=False hides all error output.
"""

import argparse
import os
import sys
import traceback


def _crash_log_path():
    """Path for the crash log — next to the EXE or in cwd."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "kvk_reader_crash.log")
    return os.path.join(os.getcwd(), "kvk_reader_crash.log")


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="kvk-reader",
        description="KVK/eGK Reader — Kartenleser-Server mit Weboberfläche",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--server",
        action="store_true",
        help="Serverbetrieb mit Weboberfläche (Standard)",
    )
    mode.add_argument(
        "--gui",
        action="store_true",
        help="Klassisches Desktop-Fenster starten",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port für den Server (Standard: aus den Einstellungen)",
    )
    return parser.parse_args(argv)


def _write_crash_log(tb: str) -> str:
    """Write crash details to a file and return its path."""
    crash_file = _crash_log_path()
    try:
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write("KVK-Reader Crash Log\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Executable: {sys.executable}\n")
            f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
            f.write(f"Platform: {sys.platform}\n\n")
            f.write(tb)
    except Exception:
        pass
    return crash_file


def main():
    args = _parse_args(sys.argv[1:])

    try:
        if args.gui:
            from kvk_reader.app import run_app
            sys.exit(run_app())

        from kvk_reader.server_app import run_server
        sys.exit(run_server(args.port))

    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        crash_file = _write_crash_log(tb)

        # Console output first — in server mode that is all there is.
        try:
            sys.stderr.write(f"\nFehler beim Start:\n{tb}\nDetails: {crash_file}\n")
        except Exception:
            pass

        # In GUI mode additionally show a message box if PyQt is available.
        if args.gui:
            try:
                from PyQt5.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.critical(
                    None,
                    "KVK-Reader - Fehler",
                    f"Die Anwendung konnte nicht gestartet werden.\n\n"
                    f"Details wurden gespeichert in:\n{crash_file}\n\n"
                    f"{tb[:500]}",
                )
            except Exception:
                pass

        sys.exit(1)


if __name__ == "__main__":
    main()
