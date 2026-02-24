"""Flask REST API server running in a background thread.

Provides endpoints to read patient data and trigger printing
from external applications.
"""

from __future__ import annotations

import threading
import logging

from flask import Flask, jsonify, request
from flask_cors import CORS

log = logging.getLogger(__name__)


class ApiServer:
    """Flask API server that runs in a QThread-compatible background thread.

    Provides thread-safe access to the current patient data via the main window.
    """

    def __init__(self, main_window, port: int = 8899):
        self._main_window = main_window
        self._port = port
        self._app = Flask(__name__)
        CORS(self._app)
        self._app.logger.setLevel(logging.WARNING)
        self._server = None

        # Suppress werkzeug request logging
        werkzeug_log = logging.getLogger("werkzeug")
        werkzeug_log.setLevel(logging.ERROR)

        self._register_routes()
        self._thread: threading.Thread | None = None

    def _register_routes(self):
        app = self._app

        @app.route("/api/patient", methods=["GET"])
        def get_patient():
            """Return the last read patient data as JSON."""
            patient = self._main_window._current_patient
            if patient is None:
                return jsonify({"error": "Keine Kartendaten vorhanden"}), 404
            return jsonify(patient.to_dict())

        @app.route("/api/patient/read", methods=["GET"])
        def read_patient():
            """Trigger a synchronous card read and return the data."""
            try:
                from kvk_reader.card.card_detector import CardReaderWorker
                from PyQt5.QtCore import QSettings
                from kvk_reader.config import ORG_NAME, APP_NAME, DEFAULTS

                settings = QSettings(ORG_NAME, APP_NAME)
                reader_index = int(settings.value("reader/index", DEFAULTS["reader/index"]))
                ct_api_dll = str(settings.value("reader/ct_api_dll", DEFAULTS["reader/ct_api_dll"]))
                ct_api_pn = int(settings.value("reader/ct_api_pn", DEFAULTS["reader/ct_api_pn"]))

                worker = CardReaderWorker(ct_api_dll=ct_api_dll, ct_api_pn=ct_api_pn)
                patient = worker.read_from_reader(reader_index)

                # Save to DB and update GUI (thread-safe via invokeMethod)
                try:
                    row_id = self._main_window._storage.save(patient)
                except Exception:
                    row_id = None

                # Update GUI on main thread
                from PyQt5.QtCore import QMetaObject, Qt as QtConst, Q_ARG
                self._main_window._current_patient = patient
                QMetaObject.invokeMethod(
                    self._main_window, "_on_api_card_read",
                    QtConst.QueuedConnection,
                    Q_ARG(int, row_id or 0),
                )

                return jsonify(patient.to_dict())
            except Exception as e:
                return jsonify({"error": str(e)}), 503

        @app.route("/api/print", methods=["POST"])
        def print_label_endpoint():
            """Print the current label.

            Optional JSON body: {"copies": 3}
            """
            patient = self._main_window._current_patient
            if patient is None:
                return jsonify({"error": "Keine Kartendaten zum Drucken"}), 400

            copies = 1
            if request.is_json and request.json:
                copies = request.json.get("copies", 1)

            img = self._main_window._preview.get_print_image()
            if img is None:
                return jsonify({"error": "Kein Label gerendert"}), 400

            try:
                from kvk_reader.printer.label_printer import print_label, PrinterError
                from PyQt5.QtCore import QSettings
                from kvk_reader.config import ORG_NAME, APP_NAME, DEFAULTS

                settings = QSettings(ORG_NAME, APP_NAME)
                uri = str(settings.value("printer/uri", DEFAULTS["printer/uri"]))
                model = str(settings.value("printer/model", DEFAULTS["printer/model"]))

                print_label(img, printer_uri=uri, printer_model=model, copies=copies)
                return jsonify({"status": "ok", "copies": copies})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/status", methods=["GET"])
        def get_status():
            """Return current reader and printer status."""
            has_patient = self._main_window._current_patient is not None
            return jsonify({
                "reader_connected": len(self._main_window._reader_names) > 0,
                "readers": self._main_window._reader_names,
                "patient_loaded": has_patient,
                "api_port": self._port,
            })

    def start(self):
        """Start the Flask server in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="api-server",
        )
        self._thread.start()
        log.info("API server started on port %d", self._port)

    def _run(self):
        from werkzeug.serving import make_server
        self._server = make_server("0.0.0.0", self._port, self._app)
        self._server.serve_forever()

    def stop(self):
        """Shut down the Werkzeug server gracefully."""
        if self._server:
            self._server.shutdown()
            log.info("API server stopped")
