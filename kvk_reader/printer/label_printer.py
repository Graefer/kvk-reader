"""Brother QL-800 label printing.

Supports two print methods:
1. Windows printer driver (win32print) — uses the standard Brother driver,
   no additional software needed. This is the preferred method on Windows.
2. brother_ql via pyusb — direct USB access, requires libusb-win32 driver.
   Used as fallback or on Linux/macOS.

Uses DK-22223 (50mm continuous) labels.
"""

from __future__ import annotations

import logging
import sys

from PIL import Image

log = logging.getLogger(__name__)


class PrinterError(Exception):
    """Raised when printing fails."""


def print_label(
    image: Image.Image,
    printer_uri: str = "usb://0x04F9:0x209B",
    printer_model: str = "QL-800",
    printer_name: str = "",
    copies: int = 1,
) -> None:
    """Send a label image to the Brother QL printer.

    On Windows, tries the native Windows printer driver first (no libusb
    needed). Falls back to brother_ql via pyusb if that fails.

    Args:
        image: PIL Image to print (grayscale or RGB).
        printer_uri: USB identifier for brother_ql (e.g. 'usb://0x04F9:0x209B').
        printer_model: Brother printer model name.
        printer_name: Windows printer name (e.g. 'Brother QL-800').
                     Empty = auto-detect.
        copies: Number of copies to print.

    Raises:
        PrinterError: If printing fails.
    """
    # On Windows, try native printer driver first
    if sys.platform == "win32":
        try:
            _print_via_win32(image, printer_name=printer_name, copies=copies)
            return
        except PrinterError:
            raise
        except Exception as e:
            log.warning("Windows-Druckertreiber fehlgeschlagen: %s, versuche brother_ql...", e)

    # Fallback: brother_ql via pyusb
    _print_via_brother_ql(image, printer_uri, printer_model, copies)


def _print_via_win32(
    image: Image.Image,
    printer_name: str = "",
    copies: int = 1,
) -> None:
    """Print label via Windows printer driver using PIL ImageWin.

    Args:
        image: PIL Image to print.
        printer_name: Windows printer name. Empty = auto-detect Brother QL.
        copies: Number of copies.

    Raises:
        PrinterError: If printing fails.
    """
    try:
        import win32print
        import win32ui
        import win32con
        from PIL import ImageWin
    except ImportError as e:
        raise PrinterError(
            "pywin32 nicht installiert. "
            "Installieren mit: pip install pywin32"
        ) from e

    # Find Brother printer
    if not printer_name:
        printer_name = _find_brother_printer()

    if not printer_name:
        raise PrinterError(
            "Kein Brother-Drucker gefunden.\n"
            "Bitte Brother QL-800 Treiber installieren und "
            "Drucker anschließen."
        )

    log.info("Drucke über Windows-Treiber: '%s'", printer_name)

    # The renderer outputs a portrait image (554x938) that was rotated 90° CCW
    # for brother_ql. The Windows driver needs the landscape orientation back,
    # because the printer feeds along the short axis (50mm tape width).
    # Rotate 90° CW (-90°) to restore landscape layout for GDI printing.
    print_image = image.rotate(-90, expand=True)

    # Convert to RGB for printing
    rgb_image = print_image.convert("RGB")

    try:
        for _ in range(copies):
            # Paper size and cut position are configured in the Brother
            # printer driver (Druckeinstellungen: Bandbreite 50mm, Länge 80mm).
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name)

            hDC.StartDoc("KVK-Etikett")
            hDC.StartPage()

            # Get printer page size in pixels (set by driver)
            printer_width = hDC.GetDeviceCaps(win32con.HORZRES)
            printer_height = hDC.GetDeviceCaps(win32con.VERTRES)

            log.info("Drucker-Seitengröße: %dx%d px", printer_width, printer_height)

            # Fill entire print area — paper size is set in driver to match label
            dib = ImageWin.Dib(rgb_image)
            dib.draw(hDC.GetHandleOutput(), (0, 0, printer_width, printer_height))

            hDC.EndPage()
            hDC.EndDoc()
            hDC.DeleteDC()

        log.info("%dx Etikett gedruckt über '%s'", copies, printer_name)

    except PrinterError:
        raise
    except Exception as e:
        raise PrinterError(f"Windows-Druckfehler: {e}") from e


# Session printers redirected into an RDP session. They carry the same name
# as the real device but point at the client, so printing to one silently
# produces a PDF instead of a label.
_REDIRECTED_MARKERS = ("umgeleitet", "redirected")


def _is_redirected(name: str) -> bool:
    """True if the printer is an RDP session redirect rather than the device."""
    lowered = name.lower()
    return any(marker in lowered for marker in _REDIRECTED_MARKERS)


def _find_brother_printer() -> str:
    """Find a Brother QL printer in the Windows printer list.

    Returns:
        Printer name string, or empty string if not found.
    """
    try:
        import win32print
    except ImportError:
        return ""

    # The default printer is only a hint, and querying it fails outright when
    # running as a service account. That must not abort the search.
    try:
        default = win32print.GetDefaultPrinter()
        if ("brother" in default.lower() and "ql" in default.lower()
                and not _is_redirected(default)):
            return default
    except Exception as e:
        log.debug("Standarddrucker nicht abfragbar: %s", e)

    try:
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
        )
    except Exception as e:
        log.warning("Druckerliste nicht abfragbar: %s", e)
        return ""

    candidates = [
        name for flags, desc, name, comment in printers
        if "brother" in name.lower() and "ql" in name.lower()
    ]
    for name in candidates:
        if not _is_redirected(name):
            return name

    if candidates:
        log.warning(
            "Nur umgeleitete Brother-Drucker gefunden (%s) — diese drucken "
            "nicht auf das Gerät. Bitte Druckernamen fest eintragen.",
            ", ".join(candidates),
        )
    return ""


def _print_via_brother_ql(
    image: Image.Image,
    printer_uri: str,
    printer_model: str,
    copies: int,
) -> None:
    """Print label via brother_ql library (pyusb backend).

    Args:
        image: PIL Image to print.
        printer_uri: USB identifier.
        printer_model: Brother printer model.
        copies: Number of copies.

    Raises:
        PrinterError: If printing fails.
    """
    try:
        from brother_ql.raster import BrotherQLRaster
        from brother_ql.conversion import convert
        from brother_ql.backends.helpers import send
    except ImportError as e:
        raise PrinterError(
            "brother_ql nicht installiert. "
            "Installieren mit: pip install brother-ql"
        ) from e

    try:
        qlr = BrotherQLRaster(printer_model)
        instructions = convert(
            qlr=qlr,
            images=[image] * copies,
            label="50",  # 50mm continuous (DK-22223)
            cut=True,
            dither=False,
            compress=False,
            red=False,
            rotate="auto",
            hq=True,
        )

        last_error = None
        for backend in ("pyusb", "linux_kernel"):
            try:
                send(
                    instructions=instructions,
                    printer_identifier=printer_uri,
                    backend_identifier=backend,
                )
                return
            except Exception as e:
                last_error = e
                continue

        raise PrinterError(
            f"Drucker nicht erreichbar: {last_error}\n\n"
            f"Mögliche Ursachen:\n"
            f"- Brother QL-800 ist nicht angeschlossen oder ausgeschaltet\n"
            f"- libusb-win32 Treiber fehlt (für USB-Zugriff benötigt)\n"
            f"  Download: https://zadig.akeo.ie/"
        )
    except PrinterError:
        raise
    except Exception as e:
        raise PrinterError(f"Druckfehler: {e}") from e


def list_usb_printers() -> list[str]:
    """List available Brother QL USB printers.

    Returns:
        List of USB printer identifiers.
    """
    try:
        from brother_ql.backends.helpers import discover
        return discover(backend_identifier="pyusb")
    except Exception:
        return []


def list_all_windows_printers() -> list[str]:
    """Every Windows printer, so the settings page can offer a choice.

    Redirected session printers are filtered out — they look like the real
    device but print somewhere else entirely.
    """
    try:
        import win32print
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
        )
        return [
            name for flags, desc, name, comment in printers
            if not _is_redirected(name)
        ]
    except Exception:
        return []


def list_windows_printers() -> list[str]:
    """List available Windows printers (Brother QL models).

    Returns:
        List of Windows printer name strings.
    """
    try:
        import win32print
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
        )
        return [
            name for flags, desc, name, comment in printers
            if "brother" in name.lower()
        ]
    except Exception:
        return []
