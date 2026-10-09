"""JSON-backed settings for server mode.

The GUI uses QSettings; the headless server cannot, because that would
pull in PyQt5. This module stores the same keys as
:data:`kvk_reader.config.DEFAULTS` in a JSON file next to the database.

Values are written through to disk on every change so a crash cannot
lose the practice configuration.
"""

from __future__ import annotations

import json
import logging
import os
import threading

from kvk_reader.config import DEFAULTS
from kvk_reader.paths import app_data_dir

log = logging.getLogger(__name__)

_CONFIG_FILENAME = "config.json"


def _config_path() -> str:
    """Path of the settings JSON file."""
    return os.path.join(app_data_dir(), _CONFIG_FILENAME)


def coerce_value(value, default):
    """Convert a value to the type implied by its default.

    HTML form fields and QSettings both hand back strings, so booleans and
    integers have to be restored explicitly — otherwise a port number would
    end up quoted in the config file.
    """
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "ja")
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return "" if value is None else str(value)


class Settings:
    """Thread-safe key/value settings backed by a JSON file.

    Keys are the same slash-separated strings used with QSettings,
    e.g. ``praxis/bsnr`` or ``api/port``.
    """

    def __init__(self, path: str | None = None):
        self._path = path or _config_path()
        self._lock = threading.Lock()
        self._values: dict = dict(DEFAULTS)
        self._load()

    def _load(self):
        """Read the JSON file, keeping defaults for missing keys."""
        if not os.path.exists(self._path):
            log.info("Keine Konfigurationsdatei, verwende Standardwerte: %s", self._path)
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self._values.update(stored)
                log.info("Konfiguration geladen: %s", self._path)
            else:
                log.warning("Konfigurationsdatei ist kein Objekt, ignoriert: %s", self._path)
        except (OSError, ValueError) as e:
            log.error("Konfiguration konnte nicht gelesen werden (%s): %s", self._path, e)

    def _write(self):
        """Persist the current values. Caller must hold the lock."""
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._values, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Konfiguration konnte nicht gespeichert werden: %s", e)

    def get(self, key: str, default=None):
        """Return a value, falling back to DEFAULTS and then to `default`."""
        with self._lock:
            if key in self._values:
                return self._values[key]
        return DEFAULTS.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return "" if value is None else str(value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "ja")
        return bool(value)

    def set(self, key: str, value):
        """Set a single value and persist immediately."""
        with self._lock:
            self._values[key] = value
            self._write()

    def update(self, values: dict):
        """Set several values at once and persist immediately.

        Unknown keys are ignored so a malformed API request cannot
        pollute the configuration file.
        """
        with self._lock:
            for key, value in values.items():
                if key in DEFAULTS:
                    self._values[key] = coerce_value(value, DEFAULTS[key])
                else:
                    log.warning("Unbekannter Einstellungs-Schlüssel ignoriert: %s", key)
            self._write()

    def as_dict(self) -> dict:
        """Return a copy of all settings."""
        with self._lock:
            return dict(self._values)


_instance: Settings | None = None
_instance_lock = threading.Lock()


def get_settings() -> Settings:
    """Return the process-wide Settings instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Settings()
        return _instance
