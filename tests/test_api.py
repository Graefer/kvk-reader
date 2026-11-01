"""Tests for the REST API server.

These use a real AppContext with an isolated settings file and database,
so the tests exercise the same code paths a browser hits. Nothing here
may touch a card reader or a printer.
"""

import base64
import json
from unittest.mock import patch

import pytest

from kvk_reader.api.server import ApiServer
from kvk_reader.card.models import PatientData
from kvk_reader.core.context import AppContext
from kvk_reader.settings import Settings
from kvk_reader.storage import PatientStorage


@pytest.fixture
def context(tmp_path):
    """AppContext backed by a throwaway config file and database."""
    settings = Settings(path=str(tmp_path / "config.json"))
    storage = PatientStorage(db_path=str(tmp_path / "kvk_reader.db"))
    return AppContext(settings=settings, storage=storage)


@pytest.fixture
def api_client(context):
    server = ApiServer(context, port=0)
    server._app.config["TESTING"] = True
    with server._app.test_client() as client:
        yield client


@pytest.fixture
def with_patient(context):
    """Store a demo patient as the last read card."""
    patient = PatientData.demo_data()
    context.set_patient(patient, notify=False)
    return patient


def post_json(client, path, payload):
    return client.post(
        path, data=json.dumps(payload), content_type="application/json"
    )


class TestPatient:
    def test_no_data_yet(self, api_client):
        assert api_client.get("/api/patient").status_code == 404

    def test_returns_last_read(self, api_client, with_patient):
        resp = api_client.get("/api/patient")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["vorname"] == "Max"
        assert data["nachname"] == "Mustermann"
        assert data["krankenkasse_name"] == "AOK Bayern"

    def test_read_without_hardware(self, api_client):
        """No reader attached must be a clean 503, never a traceback."""
        resp = api_client.post("/api/patient/read")
        assert resp.status_code == 503
        assert "error" in json.loads(resp.data)


class TestStatus:
    def test_reports_empty_state(self, api_client):
        data = json.loads(api_client.get("/api/status").data)
        assert data["patient_loaded"] is False
        assert data["reader_connected"] is False
        assert data["readers"] == []
        assert "api_port" in data
        assert "version" in data

    def test_reports_readers_and_patient(self, api_client, context, with_patient):
        context.set_readers(["Cherry ST-2100"])
        data = json.loads(api_client.get("/api/status").data)
        assert data["reader_connected"] is True
        assert "Cherry ST-2100" in data["readers"]
        assert data["patient_loaded"] is True


class TestPreview:
    def test_renders_png_for_supplied_patient(self, api_client):
        resp = post_json(api_client, "/api/label/preview", {
            "patient": PatientData.demo_data().to_dict(),
            "datum": "01.07.2026",
        })
        assert resp.status_code == 200
        png = base64.b64decode(json.loads(resp.data)["png_base64"])
        assert png[:4] == b"\x89PNG"

    def test_ignores_unknown_fields(self, api_client):
        """History records carry id/einlesedatum, which are not card fields."""
        payload = PatientData.demo_data().to_dict()
        payload["id"] = 7
        payload["einlesedatum"] = "01.01.2026"
        resp = post_json(api_client, "/api/label/preview", {"patient": payload})
        assert resp.status_code == 200

    def test_without_any_patient(self, api_client):
        assert post_json(api_client, "/api/label/preview", {}).status_code == 400


class TestPrint:
    def test_without_patient(self, api_client):
        assert api_client.post("/api/print").status_code == 400

    def test_rejects_absurd_copy_count(self, api_client, with_patient):
        resp = post_json(api_client, "/api/print", {"copies": 99})
        assert resp.status_code == 400
        assert "Kopienzahl" in json.loads(resp.data)["error"]

    def test_rejects_malformed_patient(self, api_client):
        resp = post_json(api_client, "/api/print", {"patient": "Mustermann"})
        assert resp.status_code == 400

    def test_uses_configured_printer_name(self, api_client, context, with_patient):
        context.settings.set("printer/name", "Brother QL-810W (WLAN)")
        with patch("kvk_reader.printer.label_printer.print_label") as mock_print:
            resp = post_json(api_client, "/api/print", {"copies": 2})

        assert resp.status_code == 200
        kwargs = mock_print.call_args.kwargs
        assert kwargs["printer_name"] == "Brother QL-810W (WLAN)"
        assert kwargs["copies"] == 2


class TestHistory:
    def test_roundtrip(self, api_client, context):
        row_id = context.store(PatientData.demo_data())

        records = json.loads(api_client.get("/api/history").data)
        assert len(records) == 1
        assert records[0]["nachname"] == "Mustermann"

        single = json.loads(api_client.get(f"/api/history/{row_id}").data)
        assert single["id"] == row_id

        assert api_client.delete(f"/api/history/{row_id}").status_code == 200
        assert json.loads(api_client.get("/api/history").data) == []

    def test_missing_entry(self, api_client):
        assert api_client.get("/api/history/999").status_code == 404
        assert api_client.delete("/api/history/999").status_code == 404


class TestSettings:
    def test_roundtrip_and_coercion(self, api_client, context):
        resp = api_client.put(
            "/api/settings",
            data=json.dumps({"praxis/bsnr": "123456789", "reader/index": "2"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert context.settings.get_str("praxis/bsnr") == "123456789"
        # Sent as a string by the HTML form, stored as the int it should be.
        assert context.settings.get("reader/index") == 2

    def test_unknown_keys_are_ignored(self, api_client, context):
        api_client.put(
            "/api/settings",
            data=json.dumps({"boese/key": "x"}),
            content_type="application/json",
        )
        assert "boese/key" not in context.settings.as_dict()

    def test_key_is_never_returned(self, api_client, context):
        context.settings.set("api/key", "geheim")
        data = json.loads(
            api_client.get("/api/settings", headers={"X-API-Key": "geheim"}).data
        )
        assert data["api/key"] == ""
        assert data["api/key_set"] is True


class TestAuth:
    def test_open_without_key(self, api_client):
        assert api_client.get("/api/status").status_code == 200

    def test_blocks_without_header(self, api_client, context):
        context.settings.set("api/key", "geheim")
        assert api_client.get("/api/status").status_code == 401

    def test_allows_with_header(self, api_client, context):
        context.settings.set("api/key", "geheim")
        resp = api_client.get("/api/status", headers={"X-API-Key": "geheim"})
        assert resp.status_code == 200

    def test_ui_stays_reachable(self, api_client, context):
        """The page must load so the user can enter the key at all."""
        context.settings.set("api/key", "geheim")
        assert api_client.get("/").status_code == 200

    def test_blank_key_does_not_clear(self, api_client, context):
        context.settings.set("api/key", "geheim")
        api_client.put(
            "/api/settings",
            data=json.dumps({"api/key": "", "praxis/bsnr": "1"}),
            content_type="application/json",
            headers={"X-API-Key": "geheim"},
        )
        assert context.settings.get_str("api/key") == "geheim"

    def test_null_key_clears(self, api_client, context):
        context.settings.set("api/key", "geheim")
        api_client.put(
            "/api/settings",
            data=json.dumps({"api/key": None}),
            content_type="application/json",
            headers={"X-API-Key": "geheim"},
        )
        assert context.settings.get_str("api/key") == ""


class TestDemo:
    def test_disabled_by_default(self, api_client):
        assert api_client.post("/api/demo").status_code == 403

    def test_enabled(self, api_client, context):
        context.settings.set("api/demo_mode", True)
        resp = api_client.post("/api/demo")
        assert resp.status_code == 200
        assert json.loads(resp.data)["nachname"] == "Mustermann"
        assert context.current_patient is not None


class TestLabelFont:
    def test_font_is_served(self, api_client):
        resp = api_client.get("/api/label/font")
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert resp.mimetype == "font/ttf"
            assert len(resp.data) > 1000

    def test_font_needs_no_api_key(self, api_client, context):
        """@font-face requests carry no custom headers, so the font must
        stay reachable even when the server is protected."""
        context.settings.set("api/key", "geheim")
        assert api_client.get("/api/label/font").status_code != 401
