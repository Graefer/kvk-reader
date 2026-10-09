"""Tests for the Qt-free application context and label service."""

import base64

from kvk_reader.card.models import PatientData
from kvk_reader.core.context import AppContext
from kvk_reader.core.label_service import patient_from_dict, render_preview_png
from kvk_reader.settings import Settings
from kvk_reader.storage import PatientStorage


def make_context(tmp_path) -> AppContext:
    return AppContext(
        settings=Settings(path=str(tmp_path / "config.json")),
        storage=PatientStorage(db_path=str(tmp_path / "kvk_reader.db")),
    )


class TestPatientFromDict:
    def test_drops_unknown_columns(self):
        record = PatientData.demo_data().to_dict()
        record.update({"id": 5, "einlesedatum": "01.01.2026"})
        patient = patient_from_dict(record)
        assert patient.nachname == "Mustermann"

    def test_missing_fields_default_to_empty(self):
        patient = patient_from_dict({"nachname": "Meier"})
        assert patient.nachname == "Meier"
        assert patient.vorname == ""

    def test_none_becomes_empty_string(self):
        assert patient_from_dict({"vorname": None}).vorname == ""


class TestAppContext:
    def test_starts_empty(self, tmp_path):
        context = make_context(tmp_path)
        assert context.current_patient is None
        assert context.reader_names == []

    def test_set_patient_notifies_listeners(self, tmp_path):
        context = make_context(tmp_path)
        seen = []
        context.add_listener(lambda patient, row_id: seen.append((patient, row_id)))

        patient = PatientData.demo_data()
        context.set_patient(patient, row_id=3)

        assert context.current_patient is patient
        assert seen == [(patient, 3)]

    def test_notify_false_skips_listeners(self, tmp_path):
        """The GUI pushes its own reads in and must not be called back."""
        context = make_context(tmp_path)
        seen = []
        context.add_listener(lambda patient, row_id: seen.append(patient))

        context.set_patient(PatientData.demo_data(), notify=False)
        assert seen == []

    def test_failing_listener_does_not_propagate(self, tmp_path):
        context = make_context(tmp_path)
        context.add_listener(lambda patient, row_id: 1 / 0)
        context.set_patient(PatientData.demo_data())
        assert context.current_patient is not None

    def test_store_returns_row_id(self, tmp_path):
        context = make_context(tmp_path)
        row_id = context.store(PatientData.demo_data())
        assert row_id is not None
        assert context.storage.get_by_id(row_id)["nachname"] == "Mustermann"

    def test_set_readers(self, tmp_path):
        context = make_context(tmp_path)
        context.set_readers(["Cherry ST-2100"])
        assert context.reader_names == ["Cherry ST-2100"]


class TestRenderPreview:
    def test_returns_png(self, tmp_path):
        settings = Settings(path=str(tmp_path / "config.json"))
        encoded = render_preview_png(
            PatientData.demo_data(), datum="01.07.2026", settings=settings
        )
        assert base64.b64decode(encoded)[:4] == b"\x89PNG"
