"""Tests for label rendering."""

from pathlib import Path

from kvk_reader.card.models import PatientData
from kvk_reader.printer.label_renderer import (
    _column_positions,
    datum_field_box,
    label_font_path,
    render_label,
)
from kvk_reader.printer.label_config import FONT_VALUE_SIZE, LABEL_WIDTH
from kvk_reader.printer.label_printer import _is_redirected


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


class TestDatumFieldBox:
    """The web UI puts an editable input on this rectangle, so it has to
    stay inside the preview image and line up with the rendered date."""

    def test_box_lies_inside_the_image(self):
        box = datum_field_box()
        assert box["x"] >= 0 and box["y"] >= 0
        assert box["x"] + box["width"] <= box["image_width"]
        assert box["y"] + box["height"] <= box["image_height"]

    def test_box_matches_preview_dimensions(self):
        """Preview is the landscape rendering, i.e. the label rotated back."""
        box = datum_field_box()
        preview = render_label(PatientData.demo_data()).rotate(-90, expand=True)
        assert (preview.width, preview.height) == (box["image_width"], box["image_height"])

    def test_box_sits_in_the_bottom_right_cell(self):
        """Datum is the last column of the bottom row."""
        box = datum_field_box()
        assert box["x"] > box["image_width"] * 0.6
        assert box["y"] > box["image_height"] * 0.8

    def test_box_starts_after_the_lanr_column(self):
        box = datum_field_box()
        assert box["x"] > _column_positions()["r4_col1_x"]

    def test_bottom_border_stays_visible(self):
        """The overlay must not paint over the label's bottom line."""
        box = datum_field_box()
        assert box["y"] + box["height"] < box["image_height"]

    def test_font_size_matches_the_other_values(self):
        box = datum_field_box()
        assert box["font_size"] == FONT_VALUE_SIZE


class TestLabelFont:
    """The browser is served this exact file so the editable date matches
    the rendered label instead of using whatever font the client has."""

    def test_path_exists_or_is_none(self):
        path = label_font_path()
        if path is not None:
            assert Path(path).is_file()

    def test_box_reports_font_metrics(self):
        box = datum_field_box()
        assert box["ascent"] > 0
        assert box["ascent"] + box["descent"] >= box["font_size"] * 0.8


class TestRedirectedPrinters:
    """RDP redirects carry the device's name but print to the client, so
    auto-detection must never pick one."""

    def test_german_redirect_marker(self):
        assert _is_redirected("Brother QL-810W (umgeleitet 2)") is True

    def test_english_redirect_marker(self):
        assert _is_redirected("Brother QL-810W (redirected 3)") is True

    def test_real_device_is_not_redirected(self):
        assert _is_redirected("Brother QL-810W") is False
