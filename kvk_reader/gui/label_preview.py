"""Label preview widget showing the rendered KV-Personalienfeld.

Includes an editable date field so the user can change the label date
before printing.
"""

from __future__ import annotations

from datetime import date

from PyQt5.QtWidgets import (
    QLabel, QGroupBox, QVBoxLayout, QHBoxLayout, QLineEdit,
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QTimer
from PIL import Image

from kvk_reader.card.models import PatientData
from kvk_reader.printer.label_renderer import render_label


class LabelPreview(QGroupBox):
    """Widget that renders and displays a label preview with editable date."""

    def __init__(self, parent=None):
        super().__init__("Etikett-Vorschau", parent)

        layout = QVBoxLayout()

        # Date edit row
        date_row = QHBoxLayout()
        date_label = QLabel("Datum:")
        self._date_edit = QLineEdit()
        self._date_edit.setPlaceholderText("TT.MM.JJJJ")
        self._date_edit.setMaximumWidth(120)
        self._date_edit.setText(date.today().strftime("%d.%m.%Y"))
        self._date_edit.editingFinished.connect(self._on_date_changed)
        date_row.addWidget(date_label)
        date_row.addWidget(self._date_edit)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Image preview
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumHeight(300)
        layout.addWidget(self._image_label)

        self.setLayout(layout)

        self._current_image: Image.Image | None = None
        self._full_pixmap: QPixmap | None = None
        self._current_patient: PatientData | None = None
        self._bsnr = ""
        self._lanr = ""

    def update_preview(
        self,
        patient: PatientData | None,
        bsnr: str = "",
        lanr: str = "",
        datum: str | None = None,
    ):
        """Re-render the label with current patient data."""
        self._current_patient = patient
        self._bsnr = bsnr
        self._lanr = lanr

        if patient is None:
            self._image_label.clear()
            self._image_label.setText("Keine Kartendaten")
            self._current_image = None
            self._full_pixmap = None
            return

        if datum is not None:
            self._date_edit.setText(datum)

        label_datum = self._date_edit.text().strip() or date.today().strftime("%d.%m.%Y")
        self._current_image = render_label(
            patient, bsnr=bsnr, lanr=lanr, datum=label_datum,
        )
        self._build_full_pixmap(self._current_image)
        # Defer rescale so widget has its final size after layout
        QTimer.singleShot(0, self._rescale_pixmap)

    def _on_date_changed(self):
        """Re-render with updated date when user edits it."""
        if self._current_patient is not None:
            self.update_preview(
                self._current_patient,
                bsnr=self._bsnr,
                lanr=self._lanr,
            )

    def _build_full_pixmap(self, pil_image: Image.Image):
        """Convert PIL Image to full-size QPixmap (stored for re-scaling)."""
        preview_image = pil_image.rotate(-90, expand=True)
        rgb = preview_image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
        self._full_pixmap = QPixmap.fromImage(qimage)

    def _rescale_pixmap(self):
        """Scale stored pixmap to fill current label size."""
        if self._full_pixmap is None:
            return
        w = self._image_label.width() - 20
        h = self._image_label.height() - 20
        if w <= 0 or h <= 0:
            return
        scaled = self._full_pixmap.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        """Re-scale the preview image whenever the widget is resized."""
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rescale_pixmap)

    def get_print_image(self) -> Image.Image | None:
        """Get the current rendered label image for printing."""
        return self._current_image

    def get_datum(self) -> str:
        """Get the current date string from the edit field."""
        return self._date_edit.text().strip()
