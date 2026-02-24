"""Label layout configuration for KV-Personalienfeld (Muster 5).

Measurements derived from the official KBV Adressfeld PDF template.
DK-22223: 50mm continuous label tape on Brother QL-800.

The PDF template measures 80.1mm wide x 47.3mm tall.
We render the Adressfeld at its native aspect ratio, then rotate 90° CCW
so that:
  - Adressfeld height (47.3mm) maps to the label tape width (~50mm)
  - Adressfeld width (80.1mm) maps to the label feed length

This maximises the print area with minimal margin.
"""

# Print resolution
DPI = 300

# ---------------------------------------------------------------------------
# PDF reference dimensions (points, 1pt = 1/72 inch)
# Main box in PDF: (0.55, 0.70) -> (226.60, 133.40)
# ---------------------------------------------------------------------------
_PDF_BOX_W = 226.05   # total width in points
_PDF_BOX_H = 132.70   # total height in points

# PDF dimensions in mm
_PDF_W_MM = _PDF_BOX_W * 25.4 / 72   # ~80.1mm
_PDF_H_MM = _PDF_BOX_H * 25.4 / 72   # ~47.3mm

# ---------------------------------------------------------------------------
# Pixel dimensions — render at native PDF aspect ratio
# The Adressfeld height (47.3mm) should fill the 50mm tape width (554px).
# Scale: 554px / 47.3mm = 11.71 px/mm
# ---------------------------------------------------------------------------
LABEL_WIDTH = 554                                  # = tape printable width
_PX_PER_MM = LABEL_WIDTH / _PDF_H_MM              # ~11.71 px/mm

# Rendered image dimensions (before rotation)
RENDER_WIDTH = round(_PDF_W_MM * _PX_PER_MM)       # ~938px (becomes feed length)
RENDER_HEIGHT = round(_PDF_H_MM * _PX_PER_MM)      # ~554px (becomes tape width)

# No extra margins — the table fills the full area
MARGIN_X = 0
MARGIN_Y = 0

# Scale factor: pixels per PDF point
_SCALE = RENDER_WIDTH / _PDF_BOX_W   # ~4.15 px/pt

# Line thickness
LINE_WIDTH = 2

# ---------------------------------------------------------------------------
# Horizontal divider Y-positions (from PDF top of box, in points)
# ---------------------------------------------------------------------------
_PDF_ROW1_BOTTOM = 28.2   # Krankenkasse row bottom
_PDF_ROW2_BOTTOM = 84.8   # Name/geb.am row bottom
_PDF_ROW3_BOTTOM = 108.8  # Kostenträger/VNr/Status row bottom
# Row 4 ends at box bottom = 132.7

# Row heights in points
_PDF_ROW1_H = _PDF_ROW1_BOTTOM                          # ~28.2 pt
_PDF_ROW2_H = _PDF_ROW2_BOTTOM - _PDF_ROW1_BOTTOM       # ~56.6 pt
_PDF_ROW3_H = _PDF_ROW3_BOTTOM - _PDF_ROW2_BOTTOM       # ~24.0 pt
_PDF_ROW4_H = _PDF_BOX_H - _PDF_ROW3_BOTTOM             # ~23.9 pt

# Row heights in pixels
ROW1_HEIGHT = round(_PDF_ROW1_H * _SCALE)   # Krankenkasse
ROW2_HEIGHT = round(_PDF_ROW2_H * _SCALE)   # Name + geb. am
ROW3_HEIGHT = round(_PDF_ROW3_H * _SCALE)   # KTK | Vers-Nr | Status
ROW4_HEIGHT = round(_PDF_ROW4_H * _SCALE)   # BSNR | Arzt-Nr | Datum

# ---------------------------------------------------------------------------
# Column layout (fractions of total width)
# Row 3: columns at x=79.7 and x=173.3 in PDF
# Row 4: columns at x=79.7 and x=158.9 in PDF
# ---------------------------------------------------------------------------
COL1_FRAC = 79.15 / _PDF_BOX_W          # ~0.350

# Row 3 splits
COL2_ROW3_FRAC = 93.6 / _PDF_BOX_W      # ~0.414 (Versicherten-Nr.)

# Row 4 splits
COL2_ROW4_FRAC = 79.2 / _PDF_BOX_W      # ~0.350 (Arzt-Nr.)

# ---------------------------------------------------------------------------
# Vertical divider partial heights
# In the PDF, column dividers in rows 3+4 only span the bottom ~8.2pt.
# ---------------------------------------------------------------------------
DIVIDER_START_OFFSET_FRAC = 15.7 / 24.0  # fraction of row 3/4 height

# ---------------------------------------------------------------------------
# Font sizes (pixels, scaled from PDF point sizes)
# ---------------------------------------------------------------------------
FONT_LABEL_SIZE = round(7 * _SCALE)        # Field labels (~29px, +17%)
FONT_VALUE_SIZE = round(11 * _SCALE)       # Data values (~46px, +22%)
FONT_NAME_SIZE = round(11 * _SCALE)        # Name (~46px, +22%)

# "geb. am" label position: in the PDF it's at 21.2pt from row2 top
GEB_AM_Y_OFFSET = round(21.2 * _SCALE)    # from row2 top

# ---------------------------------------------------------------------------
# Colors (grayscale, 0=black, 255=white)
# ---------------------------------------------------------------------------
COLOR_BLACK = 0
COLOR_LABEL = 0        # Field labels are black (matching PDF)
COLOR_WHITE = 255
