"""Tests for label rendering."""

from pathlib import Path

from kvk_reader.card.models import PatientData
from kvk_reader.printer.label_renderer import render_label
from kvk_reader.printer.label_config import LABEL_WIDTH


class TestLabelRenderer:
    def test_render_returns_image(self):
        patient = PatientData.demo_data()
        img = render_label(patient, bsnr="123456789", lanr="987654321", datum="14.02.2026")

        assert img is not None
        assert img.mode == "L"
        assert img.width == LABEL_WIDTH
        assert img.height > 0

    def test_render_saves_png(self, tmp_path: Path):
        patient = PatientData.demo_data()
        img = render_label(patient, bsnr="123456789", lanr="987654321", datum="14.02.2026")

        out = tmp_path / "label_test.png"
        img.save(str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_render_empty_patient(self):
        """Should not crash with empty patient data."""
        patient = PatientData()
        img = render_label(patient)
        assert img is not None
        assert img.width == LABEL_WIDTH

    def test_render_long_name(self):
        """Long names should not crash."""
        patient = PatientData.demo_data()
        patient.nachname = "Freiherr von und zu Guttenberg-Schwarzenberg"
        patient.vorname = "Karl-Theodor Maria Nikolaus Johann Jacob Philipp Franz Joseph Sylvester"
        img = render_label(patient, bsnr="123456789", lanr="987654321")
        assert img is not None
