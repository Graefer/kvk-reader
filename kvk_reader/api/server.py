"""Flask REST API and web UI server.

Everything that touches hardware — reading the card, rendering the label,
printing — happens here on the server. Browsers are remote controls: they
hold the currently displayed patient and send it back for preview and
printing, so each workstation prints exactly what it sees even when
someone else reads a card in between.

The server has no Qt dependency. In GUI mode the desktop window registers
a listener on the AppContext to stay in sync.
"""

from __future__ import annotations

import logging
import os
import threading

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from kvk_reader.card.models import PatientData
from kvk_reader.config import APP_VERSION, CT_API_DLLS
from kvk_reader.core.context import AppContext
from kvk_reader.core.label_service import (
    datum_overlay_box,
    label_font_file,
    patient_from_dict,
    render_for,
    render_preview_png,
)

log = logging.getLogger(__name__)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _windows_printers() -> list:
    """Printers the server itself can print to, for the settings page.

    Empty on non-Windows hosts; printing there goes through brother_ql.
    """
    try:
        from kvk_reader.printer.label_printer import list_all_windows_printers
        return list_all_windows_printers()
    except Exception as e:
        log.debug("Druckerliste nicht ermittelbar: %s", e)
        return []

# Paths served without an API key so the UI can load and ask for one.
_PUBLIC_PATHS = ("/", "/index.html", "/favicon.ico", "/api/label/font")


class ApiServer:
    """Serves the REST API and the web UI on a background thread."""

    def __init__(self, context: AppContext, port: int = 8899):
        self._context = context
        self._port = port
        self._app = Flask(
            __name__,
            static_folder=_STATIC_DIR,
            static_url_path="/static",
        )
        CORS(self._app)
        self._app.logger.setLevel(logging.WARNING)
        self._server = None
        self._thread: threading.Thread | None = None

        # Suppress werkzeug request logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        self._register_auth()
        self._register_ui_routes()
        self._register_api_routes()

    # --- infrastructure -------------------------------------------------

    def _register_auth(self):
        @self._app.before_request
        def check_api_key():
            key = self._context.settings.get_str("api/key")
            if not key:
                return None
            if request.path in _PUBLIC_PATHS or request.path.startswith("/static/"):
                return None
            if request.method == "OPTIONS":
                return None
            if request.headers.get("X-API-Key", "") == key:
                return None
            return jsonify({"error": "Nicht autorisiert"}), 401

    def _register_ui_routes(self):
        app = self._app

        @app.route("/", methods=["GET"])
        def index():
            return send_from_directory(_STATIC_DIR, "index.html")

        @app.route("/favicon.ico", methods=["GET"])
        def favicon():
            path = os.path.join(_STATIC_DIR, "favicon.ico")
            if not os.path.exists(path):
                return "", 404
            return send_from_directory(_STATIC_DIR, "favicon.ico")

    def _register_api_routes(self):
        app = self._app
        ctx = self._context

        # --- status and patient state -----------------------------------

        @app.route("/api/status", methods=["GET"])
        def get_status():
            """Reader, printer and version status for the UI header."""
            patient = ctx.current_patient
            readers = ctx.reader_names
            return jsonify({
                "reader_connected": len(readers) > 0,
                "readers": readers,
                "reader_error": ctx.reader_error,
                "reader_index": ctx.settings.get_int("reader/index", 0),
                "patient_loaded": patient is not None,
                "last_read_at": ctx.last_read_at,
                "last_patient_name": patient.full_name if patient else "",
                "api_port": self._port,
                "version": APP_VERSION,
                "demo_mode": ctx.settings.get_bool("api/demo_mode"),
            })

        @app.route("/api/patient", methods=["GET"])
        def get_patient():
            """Return the last read patient — unchanged contract for the PVS."""
            patient = ctx.current_patient
            if patient is None:
                return jsonify({"error": "Keine Kartendaten vorhanden"}), 404
            return jsonify(patient.to_dict())

        @app.route("/api/patient/read", methods=["GET", "POST"])
        def read_patient():
            """Trigger a card read and return the data."""
            try:
                patient, row_id = ctx.read_card()
            except Exception as e:
                log.warning("Kartenlesung fehlgeschlagen: %s", e)
                return jsonify({"error": str(e)}), 503

            result = patient.to_dict()
            result["id"] = row_id
            return jsonify(result)

        @app.route("/api/demo", methods=["GET", "POST"])
        def demo_patient():
            """Load demo data so the UI can be tested without a reader."""
            if not ctx.settings.get_bool("api/demo_mode"):
                return jsonify({
                    "error": "Demo-Modus ist deaktiviert "
                             "(Einstellungen → Demo-Modus)",
                }), 403

            patient = PatientData.demo_data()
            row_id = ctx.store(patient)
            ctx.set_patient(patient, row_id)

            result = patient.to_dict()
            result["id"] = row_id
            return jsonify(result)

        # --- label preview and printing ---------------------------------

        @app.route("/api/label/preview", methods=["POST"])
        def label_preview():
            """Render a label preview as base64 PNG.

            Body: {"patient": {...}, "datum": "TT.MM.JJJJ"}
            Without "patient" the last read card is used.
            """
            payload = request.get_json(silent=True) or {}
            try:
                patient = self._patient_from_payload(payload)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            if patient is None:
                return jsonify({"error": "Keine Kartendaten vorhanden"}), 400

            try:
                png = render_preview_png(
                    patient,
                    datum=payload.get("datum") or None,
                    settings=ctx.settings,
                )
            except Exception as e:
                log.error("Etikett-Vorschau fehlgeschlagen: %s", e)
                return jsonify({"error": f"Vorschau fehlgeschlagen: {e}"}), 500

            return jsonify({"png_base64": png, "datum_box": datum_overlay_box()})

        @app.route("/api/label/font", methods=["GET"])
        def label_font():
            """Serve the very font file the label is rendered with.

            Without this the browser would style the editable date with
            whatever monospace font the client happens to have, which does
            not match the server-rendered label.
            """
            path = label_font_file()
            if not path:
                return jsonify({"error": "Keine Schriftdatei ermittelbar"}), 404
            return send_file(path, mimetype="font/ttf", max_age=86400)

        @app.route("/api/print", methods=["POST"])
        def print_label_endpoint():
            """Print a label.

            Body (all optional): {"patient": {...}, "datum": "...", "copies": 1}
            Without "patient" the last read card is printed, which keeps the
            original PVS contract working.
            """
            payload = request.get_json(silent=True) or {}
            try:
                patient = self._patient_from_payload(payload)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            if patient is None:
                return jsonify({"error": "Keine Kartendaten zum Drucken"}), 400

            try:
                copies = int(payload.get("copies", 1))
            except (TypeError, ValueError):
                return jsonify({"error": "Ungültige Kopienzahl"}), 400
            if copies < 1 or copies > 20:
                return jsonify({"error": "Kopienzahl muss zwischen 1 und 20 liegen"}), 400

            try:
                image = render_for(
                    patient,
                    datum=payload.get("datum") or None,
                    settings=ctx.settings,
                )
            except Exception as e:
                log.error("Etikett-Rendering fehlgeschlagen: %s", e)
                return jsonify({"error": f"Etikett konnte nicht erzeugt werden: {e}"}), 500

            from kvk_reader.printer.label_printer import print_label, PrinterError

            try:
                print_label(
                    image,
                    printer_uri=ctx.settings.get_str("printer/uri"),
                    printer_model=ctx.settings.get_str("printer/model"),
                    printer_name=ctx.settings.get_str("printer/name"),
                    copies=copies,
                )
            except PrinterError as e:
                log.warning("Druck fehlgeschlagen: %s", e)
                return jsonify({"error": str(e)}), 503
            except Exception as e:
                log.error("Unerwarteter Druckfehler: %s", e)
                return jsonify({"error": f"Druckfehler: {e}"}), 500

            return jsonify({"status": "ok", "copies": copies})

        # --- history ----------------------------------------------------

        @app.route("/api/history", methods=["GET"])
        def get_history():
            try:
                return jsonify(ctx.storage.get_all())
            except Exception as e:
                log.error("Historie konnte nicht gelesen werden: %s", e)
                return jsonify({"error": str(e)}), 500

        @app.route("/api/history/<int:row_id>", methods=["GET"])
        def get_history_entry(row_id: int):
            record = ctx.storage.get_by_id(row_id)
            if record is None:
                return jsonify({"error": "Eintrag nicht gefunden"}), 404
            return jsonify(record)

        @app.route("/api/history/<int:row_id>", methods=["DELETE"])
        def delete_history_entry(row_id: int):
            if not ctx.storage.delete(row_id):
                return jsonify({"error": "Eintrag nicht gefunden"}), 404
            return jsonify({"status": "ok"})

        # --- settings and readers ---------------------------------------

        @app.route("/api/settings", methods=["GET"])
        def get_settings_endpoint():
            values = ctx.settings.as_dict()
            # Never hand the API key back out; the UI only needs to know
            # whether one is configured.
            values["api/key"] = ""
            values["api/key_set"] = bool(ctx.settings.get_str("api/key"))
            values["ct_api_dlls"] = CT_API_DLLS
            values["windows_printers"] = _windows_printers()
            return jsonify(values)

        @app.route("/api/settings", methods=["PUT", "POST"])
        def put_settings():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"error": "Ungültige Einstellungen"}), 400

            # An empty api/key in a normal save must not silently clear an
            # existing key — only an explicit null does that.
            if payload.get("api/key", None) == "":
                payload.pop("api/key")
            if payload.get("api/key", "missing") is None:
                payload["api/key"] = ""

            ctx.settings.update(payload)
            return jsonify({"status": "ok"})

        @app.route("/api/readers", methods=["GET"])
        def get_readers():
            return jsonify({"readers": ctx.discover_readers()})

    def _patient_from_payload(self, payload: dict) -> PatientData | None:
        """Resolve the patient a request refers to.

        Prefers an explicit ``patient`` object, then a history ``id``, and
        finally the last read card.

        Raises:
            ValueError: If the supplied patient object is malformed.
        """
        if isinstance(payload.get("patient"), dict):
            return patient_from_dict(payload["patient"])

        if payload.get("id") is not None:
            record = self._context.storage.get_by_id(int(payload["id"]))
            if record is None:
                raise ValueError("Eintrag nicht gefunden")
            return patient_from_dict(record)

        return self._context.current_patient

    # --- lifecycle ------------------------------------------------------

    def start(self):
        """Start the server in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="api-server",
        )
        self._thread.start()
        log.info("Server gestartet auf Port %d", self._port)

    def _run(self):
        from werkzeug.serving import make_server
        # threaded=True: several browsers poll the status concurrently.
        self._server = make_server("0.0.0.0", self._port, self._app, threaded=True)
        self._server.serve_forever()

    def serve_forever(self):
        """Run the server in the calling thread (headless mode)."""
        self._run()

    def stop(self):
        """Shut down the server gracefully."""
        if self._server:
            self._server.shutdown()
            log.info("Server gestoppt")
