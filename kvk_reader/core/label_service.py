"""Label rendering independent of the desktop GUI.

In the GUI the rendered label lives inside the preview widget. The server
has no widget, so it renders on demand from patient data plus the practice
settings — this is what makes printing possible without Qt.
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import date

from PIL import Image

from kvk_reader.card.models import PatientData
from kvk_reader.printer.label_renderer import (
    datum_field_box,
    label_font_path,
    render_label,
)
from kvk_reader.settings import Settings, get_settings

log = logging.getLogger(__name__)


def patient_from_dict(data: dict) -> PatientData:
    """Build a PatientData from a JSON payload, ignoring unknown keys.

    History records carry extra columns (``id``, ``einlesedatum``) that are
    not dataclass fields, so they are filtered out here.

    Args:
        data: Mapping with a subset of PatientData field names.

    Returns:
        PatientData with defaults for every missing field.

    Raises:
        ValueError: If `data` is not a mapping.
    """
    if not isinstance(data, dict):
        raise ValueError("Patientendaten müssen ein Objekt sein")

    from dataclasses import fields

    known = {f.name for f in fields(PatientData)}
    values = {k: v for k, v in data.items() if k in known}
    # The dataclass expects strings throughout; None would break rendering.
    values = {k: ("" if v is None else str(v)) for k, v in values.items()}
    return PatientData(**values)


def render_for(
    patient: PatientData,
    datum: str | None = None,
    settings: Settings | None = None,
) -> Image.Image:
    """Render the label for a patient using the stored practice data.

    Args:
        patient: Patient to render.
        datum: Label date as DD.MM.YYYY. Defaults to today.
        settings: Settings instance; defaults to the process-wide one.

    Returns:
        PIL Image ready for printing.
    """
    cfg = settings or get_settings()
    return render_label(
        patient,
        bsnr=cfg.get_str("praxis/bsnr"),
        lanr=cfg.get_str("praxis/lanr"),
        datum=datum or date.today().strftime("%d.%m.%Y"),
    )


def render_preview_png(
    patient: PatientData,
    datum: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Render the label as a base64-encoded PNG for display in a browser.

    The image is rotated the same way the GUI preview rotates it, so the
    browser shows the label in reading orientation rather than in the
    printer's tape orientation.

    Args:
        patient: Patient to render.
        datum: Label date as DD.MM.YYYY. Defaults to today.
        settings: Settings instance; defaults to the process-wide one.

    Returns:
        Base64 string without a data-URI prefix.
    """
    image = render_for(patient, datum=datum, settings=settings)
    preview = image.rotate(-90, expand=True)

    buffer = io.BytesIO()
    preview.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def datum_overlay_box() -> dict:
    """Geometry the web UI needs to place its date input on the label.

    Coordinates match the preview PNG, which is the landscape rendering.
    """
    return datum_field_box()


def label_font_file() -> str | None:
    """Path of the font file the label is rendered with, for the web UI."""
    return label_font_path()
