"""Mirror the window's QSettings into the JSON settings used by the server.

The desktop window stores its configuration in QSettings, the REST API
reads the JSON file. When both run in the same process, a label printed
through the API must carry the same practice data the window shows — so
the GUI pushes its values across at startup and after every change.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore import QSettings

from kvk_reader.config import APP_NAME, DEFAULTS, ORG_NAME
from kvk_reader.settings import get_settings

log = logging.getLogger(__name__)


def sync_qsettings_to_json():
    """Copy every known settings key from QSettings into the JSON file."""
    qsettings = QSettings(ORG_NAME, APP_NAME)

    values = {}
    for key in DEFAULTS:
        raw = qsettings.value(key, None)
        if raw is not None:
            values[key] = raw

    if values:
        get_settings().update(values)
        log.debug("QSettings in JSON-Konfiguration übernommen (%d Werte)", len(values))
