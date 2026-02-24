"""Tests for REST API server."""

import json
import pytest
from unittest.mock import MagicMock

from kvk_reader.api.server import ApiServer
from kvk_reader.card.models import PatientData


@pytest.fixture
def mock_window():
    """Create a mock main window with demo patient data."""
    window = MagicMock()
    window._current_patient = PatientData.demo_data()
    window._preview = MagicMock()
    window._preview.get_print_image.return_value = None
    window._reader_names = []  # No readers in test environment
    return window


@pytest.fixture
def api_client(mock_window):
    """Create a Flask test client."""
    server = ApiServer(mock_window, port=0)
    server._app.config["TESTING"] = True
    with server._app.test_client() as client:
        yield client


class TestApiPatient:
    def test_get_patient(self, api_client):
        resp = api_client.get("/api/patient")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["vorname"] == "Max"
        assert data["nachname"] == "Mustermann"
        assert data["krankenkasse_name"] == "AOK Bayern"

    def test_get_patient_no_data(self, api_client, mock_window):
        mock_window._current_patient = None
        resp = api_client.get("/api/patient")
        assert resp.status_code == 404

    def test_read_patient_no_hardware(self, api_client):
        """Without pyscard/hardware, /api/patient/read returns 503."""
        resp = api_client.get("/api/patient/read")
        # Without a real card reader this will fail with 503
        assert resp.status_code == 503
        data = json.loads(resp.data)
        assert "error" in data


class TestApiStatus:
    def test_get_status(self, api_client):
        resp = api_client.get("/api/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["patient_loaded"] is True
        assert data["reader_connected"] is False
        assert data["readers"] == []
        assert "api_port" in data

    def test_get_status_with_readers(self, api_client, mock_window):
        mock_window._reader_names = ["Cherry ST-2100"]
        resp = api_client.get("/api/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["reader_connected"] is True
        assert "Cherry ST-2100" in data["readers"]


class TestApiPrint:
    def test_print_no_image(self, api_client):
        resp = api_client.post(
            "/api/print",
            data=json.dumps({"copies": 1}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_print_no_patient(self, api_client, mock_window):
        mock_window._current_patient = None
        resp = api_client.post("/api/print")
        assert resp.status_code == 400
