"""Render KV-Personalienfeld (Muster 5) label as PIL Image.

The Adressfeld is rendered at its native landscape aspect ratio (~80x47mm),
then rotated 90° counter-clockwise so that the Adressfeld height maps to the
Brother QL-800 DK-22223 tape width (50mm) with minimal margin.

The final image is 554px wide (tape width) x ~938px tall (feed length).
"""

from __future__ import annotations

import os
import sys
from datetime import date

from PIL import Image, ImageDraw, ImageFont

from kvk_reader.card.models import PatientData
from kvk_reader.printer.label_config import (
    LABEL_WIDTH,
    RENDER_WIDTH,
    RENDER_HEIGHT,
    MARGIN_X,
    MARGIN_Y,
    LINE_WIDTH,
    ROW1_HEIGHT,
    ROW2_HEIGHT,
    ROW3_HEIGHT,
    ROW4_HEIGHT,
    COL1_FRAC,
    COL2_ROW3_FRAC,
    COL2_ROW4_FRAC,
    DIVIDER_START_OFFSET_FRAC,
    FONT_LABEL_SIZE,
    FONT_VALUE_SIZE,
    FONT_NAME_SIZE,
    GEB_AM_Y_OFFSET,
    COLOR_BLACK,
    COLOR_LABEL,
    COLOR_WHITE,
)


def _find_font(name: str) -> str | None:
    """Search for a font file by name in common system locations."""
    search_paths = []

    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        search_paths.append(os.path.join(windir, "Fonts"))
    elif sys.platform == "darwin":
        search_paths.extend([
            "/System/Library/Fonts",
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ])
    else:
        search_paths.extend([
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype",
            "/usr/share/fonts",
        ])

    # Also check bundled assets/fonts directory
    bundle_dir = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts")
    search_paths.insert(0, os.path.normpath(bundle_dir))

    for d in search_paths:
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return None


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a monospace font, falling back gracefully."""
    candidates = [
        "consola.ttf", "Consola.ttf",           # Consolas (Windows)
        "cour.ttf", "Cour.ttf",                 # Courier New (Windows)
        "courbd.ttf",                            # Courier New Bold (Windows)
        "Courier New.ttf",
        "DejaVuSansMono.ttf",                   # Linux
    ]

    for name in candidates:
        path = _find_font(name)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue

    # Direct truetype attempt (PIL internal search)
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    # macOS .ttc fallback — Courier is monospace
    for ttc in ["Courier New.ttc", "Courier.ttc"]:
        path = _find_font(ttc)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue

    return ImageFont.load_default()


# Padding inside table cells (pixels)
TEXT_PAD = 8


def _column_positions() -> dict:
    """Column x-positions of the table, in render (landscape) pixels.

    Shared by the renderer and by :func:`datum_field_box` so the editable
    overlay in the web UI can never drift away from what is drawn.
    """
    x0 = MARGIN_X
    x_end = RENDER_WIDTH - MARGIN_X
    usable_width = x_end - x0
    col1_w = round(usable_width * COL1_FRAC)
    return {
        "x0": x0,
        "x_end": x_end,
        "usable_width": usable_width,
        "r3_col1_x": x0 + col1_w,
        "r3_col2_x": x0 + col1_w + round(usable_width * COL2_ROW3_FRAC),
        "r4_col1_x": x0 + col1_w,
        "r4_col2_x": x0 + col1_w + round(usable_width * COL2_ROW4_FRAC),
    }


def label_font_path() -> str | None:
    """Path of the font file the renderer actually uses, if it is a real file.

    The web UI serves this very file to the browser, so the editable date
    matches the rendered label on any client OS — relying on the client
    happening to have Consolas installed does not work.
    """
    font = _get_font(FONT_VALUE_SIZE)
    path = getattr(font, "path", None)
    if path and os.path.isfile(path):
        return path
    return None


def datum_field_box() -> dict:
    """Rectangle, font and metrics of the Datum value, in render pixels.

    The web UI places an input exactly here so the date can be edited on the
    label itself instead of in a separate field. Ascent and descent let the
    browser line the text up on the same baseline PIL draws on: PIL puts the
    ascender line at y, CSS centres the text in its line box.
    """
    pos = _column_positions()
    row4_y = MARGIN_Y + ROW1_HEIGHT + ROW2_HEIGHT + ROW3_HEIGHT
    x = pos["r4_col2_x"] + TEXT_PAD

    try:
        ascent, descent = _get_font(FONT_VALUE_SIZE).getmetrics()
    except (AttributeError, OSError):
        ascent, descent = FONT_VALUE_SIZE, 0

    return {
        "x": x,
        "y": row4_y + ROW4_HEIGHT - FONT_VALUE_SIZE - 6,
        "width": pos["x_end"] - x - TEXT_PAD,
        "height": FONT_VALUE_SIZE + 2,   # laesst die untere Rahmenlinie frei
        "font_size": FONT_VALUE_SIZE,
        "ascent": ascent,
        "descent": descent,
        "image_width": RENDER_WIDTH,
        "image_height": RENDER_HEIGHT,
    }


def render_label(
    patient: PatientData,
    bsnr: str = "",
    lanr: str = "",
    datum: str | None = None,
) -> Image.Image:
    """Render a KV-Personalienfeld label as a PIL Image.

    The label is rendered landscape then rotated 90° CCW so that the
    Adressfeld height fills the tape width with minimal margin.

    Args:
        patient: Patient data to render.
        bsnr: Betriebsstättennummer (from practice settings).
        lanr: Arzt-Nr. / LANR (from practice settings).
        datum: Date string, defaults to today (DD.MM.YYYY).

    Returns:
        PIL Image in grayscale ('L' mode), LABEL_WIDTH wide, ready for printing.
    """
    if datum is None:
        datum = date.today().strftime("%d.%m.%Y")

    # Render landscape (wide) then rotate
    img = Image.new("L", (RENDER_WIDTH, RENDER_HEIGHT), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    # Fonts — all proportional (no bold)
    font_label = _get_font(FONT_LABEL_SIZE)
    font_value = _get_font(FONT_VALUE_SIZE)
    font_name = _get_font(FONT_NAME_SIZE)

    # Full-width table — geometry shared with datum_field_box()
    _pos = _column_positions()
    x0 = _pos["x0"]
    x_end = _pos["x_end"]
    usable_width = _pos["usable_width"]
    text_pad = TEXT_PAD

    r3_col1_x = _pos["r3_col1_x"]
    r3_col2_x = _pos["r3_col2_x"]
    r4_col1_x = _pos["r4_col1_x"]
    r4_col2_x = _pos["r4_col2_x"]

    # =====================================================================
    # Row 1: Krankenkasse bzw. Kostenträger
    # =====================================================================
    y = MARGIN_Y

    # Top border
    draw.line([(x0, y), (x_end, y)], fill=COLOR_BLACK, width=LINE_WIDTH)
    # Side borders
    draw.line([(x0, y), (x0, y + ROW1_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)
    draw.line([(x_end - 1, y), (x_end - 1, y + ROW1_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)

    # Label
    draw.text(
        (x0 + text_pad, y + 4),
        "Krankenkasse bzw. Kostenträger",
        fill=COLOR_LABEL, font=font_label,
    )
    # Value
    draw.text(
        (x0 + text_pad, y + 4 + FONT_LABEL_SIZE + 8),
        patient.krankenkasse_name,
        fill=COLOR_BLACK, font=font_value,
    )

    # =====================================================================
    # Row 2: Name, Vorname des Versicherten + geb. am
    # =====================================================================
    y += ROW1_HEIGHT

    # Horizontal divider
    draw.line([(x0, y), (x_end, y)], fill=COLOR_BLACK, width=LINE_WIDTH)
    # Side borders
    draw.line([(x0, y), (x0, y + ROW2_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)
    draw.line([(x_end - 1, y), (x_end - 1, y + ROW2_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)

    # "Name, Vorname des Versicherten" label (top-left)
    draw.text(
        (x0 + text_pad, y + 4),
        "Name, Vorname des Versicherten",
        fill=COLOR_LABEL, font=font_label,
    )

    # "geb. am" label — positioned lower and right-aligned (matching PDF)
    geb_label = "geb. am"
    geb_label_bbox = draw.textbbox((0, 0), geb_label, font=font_label)
    geb_label_w = geb_label_bbox[2] - geb_label_bbox[0]
    draw.text(
        (x_end - text_pad - geb_label_w, y + GEB_AM_Y_OFFSET),
        geb_label,
        fill=COLOR_LABEL, font=font_label,
    )

    # Name value — directly below the label text
    name_str = patient.full_name
    name_y = y + 4 + FONT_LABEL_SIZE + 8
    draw.text(
        (x0 + text_pad, name_y),
        name_str,
        fill=COLOR_BLACK, font=font_name,
    )

    # Address lines — below name, smaller font
    addr_line_height = FONT_LABEL_SIZE + 4
    addr_y = name_y + FONT_NAME_SIZE + 4

    # Street + house number
    street_str = patient.strasse
    if patient.hausnummer and patient.hausnummer not in patient.strasse:
        street_str = f"{patient.strasse} {patient.hausnummer}"
    if street_str:
        draw.text(
            (x0 + text_pad, addr_y),
            street_str,
            fill=COLOR_BLACK, font=font_value,
        )
        addr_y += FONT_VALUE_SIZE + 2

    # PLZ + Ort
    plz_ort = f"{patient.plz} {patient.ort}".strip()
    if plz_ort:
        draw.text(
            (x0 + text_pad, addr_y),
            plz_ort,
            fill=COLOR_BLACK, font=font_value,
        )

    # Geburtsdatum value — right-aligned, below "geb. am" label
    # Display as DD.MM.YY (short year) on label
    geb_value = patient.geburtsdatum
    if len(geb_value) == 10 and geb_value[2] == "." and geb_value[5] == ".":
        geb_value = geb_value[:6] + geb_value[8:]  # "01.01.1990" → "01.01.90"
    geb_bbox = draw.textbbox((0, 0), geb_value, font=font_value)
    geb_w = geb_bbox[2] - geb_bbox[0]
    geb_value_y = y + GEB_AM_Y_OFFSET + FONT_LABEL_SIZE + 8
    draw.text(
        (x_end - text_pad - geb_w, geb_value_y),
        geb_value,
        fill=COLOR_BLACK, font=font_value,
    )

    # =====================================================================
    # Row 3: Kostenträgerkennung | Versicherten-Nr. | Status
    # =====================================================================
    y += ROW2_HEIGHT

    # Horizontal divider
    draw.line([(x0, y), (x_end, y)], fill=COLOR_BLACK, width=LINE_WIDTH)
    # Side borders
    draw.line([(x0, y), (x0, y + ROW3_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)
    draw.line([(x_end - 1, y), (x_end - 1, y + ROW3_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)

    # Labels
    draw.text(
        (x0 + text_pad, y + 4),
        "Kostenträgerkennung",
        fill=COLOR_LABEL, font=font_label,
    )
    draw.text(
        (r3_col1_x + text_pad, y + 4),
        "Versicherten-Nr.",
        fill=COLOR_LABEL, font=font_label,
    )
    draw.text(
        (r3_col2_x + text_pad, y + 4),
        "Status",
        fill=COLOR_LABEL, font=font_label,
    )

    # Partial vertical dividers (only in value area)
    divider_start_y = y + round(ROW3_HEIGHT * DIVIDER_START_OFFSET_FRAC)
    divider_end_y = y + ROW3_HEIGHT
    draw.line(
        [(r3_col1_x, divider_start_y), (r3_col1_x, divider_end_y)],
        fill=COLOR_BLACK, width=LINE_WIDTH,
    )
    draw.line(
        [(r3_col2_x, divider_start_y), (r3_col2_x, divider_end_y)],
        fill=COLOR_BLACK, width=LINE_WIDTH,
    )

    # Values (bottom of row)
    value_y = y + ROW3_HEIGHT - FONT_VALUE_SIZE - 6
    draw.text(
        (x0 + text_pad, value_y),
        patient.krankenkassen_nummer,
        fill=COLOR_BLACK, font=font_value,
    )
    draw.text(
        (r3_col1_x + text_pad, value_y),
        patient.versichertennummer,
        fill=COLOR_BLACK, font=font_value,
    )
    draw.text(
        (r3_col2_x + text_pad, value_y),
        patient.versichertenstatus,
        fill=COLOR_BLACK, font=font_value,
    )

    # =====================================================================
    # Row 4: Betriebsstätten-Nr. | Arzt-Nr. | Datum
    # =====================================================================
    y += ROW3_HEIGHT

    # Horizontal divider
    draw.line([(x0, y), (x_end, y)], fill=COLOR_BLACK, width=LINE_WIDTH)
    # Side borders
    draw.line([(x0, y), (x0, y + ROW4_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)
    draw.line([(x_end - 1, y), (x_end - 1, y + ROW4_HEIGHT)], fill=COLOR_BLACK, width=LINE_WIDTH)

    # Labels
    draw.text(
        (x0 + text_pad, y + 4),
        "Betriebsstätten-Nr.",
        fill=COLOR_LABEL, font=font_label,
    )
    draw.text(
        (r4_col1_x + text_pad, y + 4),
        "Arzt-Nr.",
        fill=COLOR_LABEL, font=font_label,
    )
    draw.text(
        (r4_col2_x + text_pad, y + 4),
        "Datum",
        fill=COLOR_LABEL, font=font_label,
    )

    # Partial vertical dividers (only in value area)
    divider_start_y = y + round(ROW4_HEIGHT * DIVIDER_START_OFFSET_FRAC)
    divider_end_y = y + ROW4_HEIGHT
    draw.line(
        [(r4_col1_x, divider_start_y), (r4_col1_x, divider_end_y)],
        fill=COLOR_BLACK, width=LINE_WIDTH,
    )
    draw.line(
        [(r4_col2_x, divider_start_y), (r4_col2_x, divider_end_y)],
        fill=COLOR_BLACK, width=LINE_WIDTH,
    )

    # Values
    value_y = y + ROW4_HEIGHT - FONT_VALUE_SIZE - 6
    draw.text(
        (x0 + text_pad, value_y),
        bsnr,
        fill=COLOR_BLACK, font=font_value,
    )
    draw.text(
        (r4_col1_x + text_pad, value_y),
        lanr,
        fill=COLOR_BLACK, font=font_value,
    )
    draw.text(
        (r4_col2_x + text_pad, value_y),
        datum,
        fill=COLOR_BLACK, font=font_value,
    )

    # Bottom border
    y += ROW4_HEIGHT
    draw.line([(x0, y), (x_end, y)], fill=COLOR_BLACK, width=LINE_WIDTH)

    # Rotate 90° CCW so the Adressfeld height maps to tape width
    rotated = img.rotate(90, expand=True)

    return rotated
