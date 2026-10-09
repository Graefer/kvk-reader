"""Application data directory shared by storage and settings.

The directory lives in %APPDATA%/KVKReader/ (Windows) or ~/.kvkreader/
so that database and configuration survive application updates. Set
KVK_DATA_DIR to override it — useful when the server runs as a scheduled
task under an account without a roaming profile.
"""

from __future__ import annotations

import os
import sys

_ENV_VAR = "KVK_DATA_DIR"


def app_data_dir() -> str:
    """Return the application data directory, creating it if needed.

    Uses $KVK_DATA_DIR if set, else %APPDATA%/KVKReader/ on Windows and
    ~/.kvkreader/ elsewhere. Falls back to the executable directory if
    APPDATA is not available.

    Returns:
        Absolute path to an existing directory.
    """
    override = os.environ.get(_ENV_VAR, "").strip()
    if override:
        base = os.path.abspath(override)
        os.makedirs(base, exist_ok=True)
        return base

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            base = os.path.join(appdata, "KVKReader")
        elif getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.getcwd()
    else:
        base = os.path.join(os.path.expanduser("~"), ".kvkreader")

    os.makedirs(base, exist_ok=True)
    return base
