"""Application entry point.

When running as a frozen PyInstaller EXE, any unhandled exception is
caught and written to kvk_reader_crash.log next to the executable.
This is critical because console=False hides all error output.
"""

import os
import sys
import traceback


def _crash_log_path():
    """Path for the crash log — next to the EXE or in cwd."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "kvk_reader_crash.log")
    return os.path.join(os.getcwd(), "kvk_reader_crash.log")


def main():
    try:
        from kvk_reader.app import run_app
        sys.exit(run_app())
    except Exception:
        # Write crash info to file so the user can diagnose
        crash_file = _crash_log_path()
        tb = traceback.format_exc()
        try:
            with open(crash_file, "w", encoding="utf-8") as f:
                f.write(f"KVK-Reader Crash Log\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Executable: {sys.executable}\n")
                f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
                f.write(f"Platform: {sys.platform}\n\n")
                f.write(tb)
        except Exception:
            pass

        # Also try to show a message box if PyQt is available
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
