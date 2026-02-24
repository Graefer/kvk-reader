"""SQLite storage for patient card read history.

Stores every card read in a simple table alongside the read timestamp.
The database file lives in %APPDATA%/KVKReader/ (Windows) or ~/.kvkreader/
so it survives application updates.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from dataclasses import fields

from kvk_reader.card.models import PatientData

log = logging.getLogger(__name__)

# Columns derived from PatientData dataclass fields
_PATIENT_FIELDS = [f.name for f in fields(PatientData)]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS lesevorgaenge (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    einlesedatum    TEXT NOT NULL,
    vorname         TEXT,
    nachname        TEXT,
    geburtsdatum    TEXT,
    titel           TEXT,
    namenszusatz    TEXT,
    vorsatzwort     TEXT,
    geschlecht      TEXT,
    strasse         TEXT,
    hausnummer      TEXT,
    plz             TEXT,
    ort             TEXT,
    wohnsitzlaendercode TEXT,
    krankenkasse_name   TEXT,
    krankenkassen_nummer TEXT,
    versichertennummer  TEXT,
    versichertenstatus  TEXT,
    versichertenart     TEXT,
    gueltig_bis     TEXT,
    vknr            TEXT,
    status_ergaenzung TEXT,
    card_type       TEXT,
    read_timestamp  TEXT
)
"""


def _db_path() -> str:
    """Determine the database file path.

    Uses %APPDATA%/KVKReader/ on Windows, ~/.kvkreader/ otherwise.
    This ensures the database survives application updates/reinstalls.
    Falls back to the executable directory if APPDATA is not available.
    """
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
    return os.path.join(base, "kvk_reader.db")


MAX_RECORDS = 250


class PatientStorage:
    """SQLite storage for patient card read history.

    - Detects duplicates by (nachname, vorname, geburtsdatum, versichertennummer).
      If a duplicate exists, the existing record is updated with the new timestamp.
    - Keeps at most MAX_RECORDS (250) entries, removing the oldest when full.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _db_path()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()
        log.info("Patient-DB: %s", self._db_path)

    def _find_duplicate(self, conn: sqlite3.Connection, patient: PatientData) -> int | None:
        """Check if the same patient already exists. Returns row id or None."""
        row = conn.execute(
            "SELECT id FROM lesevorgaenge "
            "WHERE nachname = ? AND vorname = ? AND geburtsdatum = ? "
            "AND versichertennummer = ?",
            (patient.nachname, patient.vorname, patient.geburtsdatum,
             patient.versichertennummer),
        ).fetchone()
        return row[0] if row else None

    def _enforce_limit(self, conn: sqlite3.Connection):
        """Delete oldest records if count exceeds MAX_RECORDS."""
        count = conn.execute("SELECT COUNT(*) FROM lesevorgaenge").fetchone()[0]
        if count > MAX_RECORDS:
            excess = count - MAX_RECORDS
            conn.execute(
                "DELETE FROM lesevorgaenge WHERE id IN "
                "(SELECT id FROM lesevorgaenge ORDER BY id ASC LIMIT ?)",
                (excess,),
            )

    def save(self, patient: PatientData) -> int:
        """Save a patient read to the database. Returns the row id.

        If the same patient (name + birthday + Versichertennummer) already
        exists, the record is updated instead of creating a duplicate.
        """
        data = patient.to_dict()
        einlesedatum = data.get("read_timestamp", "")

        with sqlite3.connect(self._db_path) as conn:
            existing_id = self._find_duplicate(conn, patient)

            if existing_id is not None:
                # Update existing record with fresh data and timestamp
                set_parts = ", ".join(f"{f} = ?" for f in _PATIENT_FIELDS)
                values = [data.get(f, "") for f in _PATIENT_FIELDS]
                values.append(einlesedatum)
                values.append(existing_id)
                conn.execute(
                    f"UPDATE lesevorgaenge SET {set_parts}, einlesedatum = ? "
                    f"WHERE id = ?",
                    values,
                )
                conn.commit()
                log.info(
                    "Aktualisiert: id=%d %s %s (%s)",
                    existing_id, patient.nachname, patient.vorname, patient.card_type,
                )
                return existing_id

            # Insert new record
            columns = ["einlesedatum"] + _PATIENT_FIELDS
            values = [einlesedatum] + [data.get(f, "") for f in _PATIENT_FIELDS]
            placeholders = ", ".join("?" for _ in columns)
            col_names = ", ".join(columns)

            cursor = conn.execute(
                f"INSERT INTO lesevorgaenge ({col_names}) VALUES ({placeholders})",
                values,
            )
            self._enforce_limit(conn)
            conn.commit()
            row_id = cursor.lastrowid
            log.info(
                "Gespeichert: id=%d %s %s (%s)",
                row_id, patient.nachname, patient.vorname, patient.card_type,
            )
            return row_id

    def get_all(self) -> list[dict]:
        """Return all stored reads, newest first."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM lesevorgaenge ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_by_id(self, row_id: int) -> dict | None:
        """Return a single record by id, or None."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM lesevorgaenge WHERE id = ?", (row_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete(self, row_id: int) -> bool:
        """Delete a single record by id. Returns True if a row was deleted."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM lesevorgaenge WHERE id = ?", (row_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                log.info("Gelöscht: id=%d", row_id)
            return deleted

    def get_count(self) -> int:
        """Return the total number of stored reads."""
        with sqlite3.connect(self._db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM lesevorgaenge").fetchone()[0]
