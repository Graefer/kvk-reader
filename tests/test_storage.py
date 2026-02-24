"""Tests for patient storage."""

from kvk_reader.card.models import PatientData
from kvk_reader.storage import PatientStorage, MAX_RECORDS


class TestPatientStorage:
    def test_save_and_retrieve(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        patient = PatientData.demo_data()
        row_id = storage.save(patient)

        assert row_id == 1
        assert db.exists()

    def test_get_all(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        p1 = PatientData(nachname="Müller", vorname="Hans", card_type="KVK")
        p2 = PatientData(nachname="Schmidt", vorname="Anna", card_type="eGK")

        storage.save(p1)
        storage.save(p2)

        rows = storage.get_all()
        assert len(rows) == 2
        # Newest first
        assert rows[0]["nachname"] == "Schmidt"
        assert rows[1]["nachname"] == "Müller"

    def test_get_count(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        assert storage.get_count() == 0

        storage.save(PatientData(nachname="A", vorname="B", geburtsdatum="01.01.2000"))
        assert storage.get_count() == 1

        # Different patient → new record
        storage.save(PatientData(nachname="C", vorname="D", geburtsdatum="02.02.2000"))
        assert storage.get_count() == 2

    def test_duplicate_detection(self, tmp_path):
        """Same patient saved twice → only one record (updated)."""
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        p = PatientData.demo_data()
        id1 = storage.save(p)
        id2 = storage.save(p)

        assert id1 == id2  # Same row updated
        assert storage.get_count() == 1

    def test_duplicate_updates_timestamp(self, tmp_path):
        """Duplicate save updates the einlesedatum."""
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        p1 = PatientData(
            nachname="Müller", vorname="Hans",
            geburtsdatum="01.01.1990", versichertennummer="V123",
            read_timestamp="2024-01-01T10:00:00",
        )
        storage.save(p1)

        p2 = PatientData(
            nachname="Müller", vorname="Hans",
            geburtsdatum="01.01.1990", versichertennummer="V123",
            read_timestamp="2024-06-15T14:30:00",
        )
        storage.save(p2)

        rows = storage.get_all()
        assert len(rows) == 1
        assert rows[0]["einlesedatum"] == "2024-06-15T14:30:00"

    def test_max_records_enforced(self, tmp_path):
        """Storage keeps at most MAX_RECORDS entries."""
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        # Insert MAX_RECORDS + 5 unique patients
        for i in range(MAX_RECORDS + 5):
            p = PatientData(
                nachname=f"Patient{i:04d}",
                vorname="Test",
                geburtsdatum=f"{(i % 28) + 1:02d}.01.2000",
                versichertennummer=f"V{i:06d}",
            )
            storage.save(p)

        assert storage.get_count() == MAX_RECORDS

    def test_get_by_id(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        patient = PatientData.demo_data()
        row_id = storage.save(patient)

        rec = storage.get_by_id(row_id)
        assert rec is not None
        assert rec["nachname"] == "Mustermann"
        assert rec["vorname"] == "Max"

        # Non-existent
        assert storage.get_by_id(9999) is None

    def test_einlesedatum_stored(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        patient = PatientData.demo_data()
        storage.save(patient)

        rows = storage.get_all()
        assert rows[0]["einlesedatum"] == patient.read_timestamp
        assert rows[0]["einlesedatum"] != ""

    def test_delete(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        p1 = PatientData(nachname="Müller", vorname="Hans")
        p2 = PatientData(nachname="Schmidt", vorname="Anna")
        id1 = storage.save(p1)
        storage.save(p2)

        assert storage.get_count() == 2
        assert storage.delete(id1) is True
        assert storage.get_count() == 1

        rows = storage.get_all()
        assert rows[0]["nachname"] == "Schmidt"

    def test_delete_nonexistent(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        assert storage.delete(999) is False

    def test_all_fields_stored(self, tmp_path):
        db = tmp_path / "test.db"
        storage = PatientStorage(str(db))

        patient = PatientData.demo_data()
        storage.save(patient)

        row = storage.get_all()[0]
        assert row["vorname"] == "Max"
        assert row["nachname"] == "Mustermann"
        assert row["geburtsdatum"] == "01.01.1990"
        assert row["krankenkasse_name"] == "AOK Bayern"
        assert row["versichertennummer"] == "A123456789"
        assert row["card_type"] == "eGK"
