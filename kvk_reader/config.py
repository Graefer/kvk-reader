"""Application configuration and default settings."""

APP_NAME = "KVK/eGK Reader"
APP_VERSION = "2.0.1"
ORG_NAME = "KVKReader"

# Default settings
DEFAULTS = {
    "reader/index": 0,
    "reader/ct_api_dll": "",        # CT-API DLL Pfad (z.B. ctpcsc32.dll)
    "reader/ct_api_pn": 1,         # CT-API Port-Nummer
    "printer/uri": "usb://0x04F9:0x209B",  # Brother QL-800; WLAN: tcp://<ip>
    "printer/model": "QL-800",
    "printer/name": "",  # Windows-Druckername, leer = automatisch suchen
    "label/copies_default": 1,
    "label/font_size": 11,
    "label/font_name_size": 13,
    "label/width_px": 554,  # DK-22223 @ 300 DPI
    "label/margin_x": 15,
    "label/margin_y": 10,
    "praxis/bsnr": "",  # Betriebsstättennummer
    "praxis/lanr": "",  # Arzt-Nr. (LANR)
    "api/enabled": True,
    "api/port": 8899,
    "api/key": "",          # leer = keine Authentifizierung
    "api/demo_mode": False,  # Demo-Patient ohne Kartenleser erlauben
}

# Known CT-API DLL names by manufacturer
CT_API_DLLS = {
    "Cherry ST-2052": "ctpcsc32kv.dll",
    "Cherry ST-2100": "ctpcsc32.dll",
    "Cherry (alt)": "ctcym.dll",
    "Omnikey (CT-API)": "ctomni532.dll",
    "HID Omnikey (Sync API)": "scardsyn.dll",
    "Reiner SCT cyberJack": "ctrsct32.dll",
    "Reiner SCT (PC/SC)": "cjpcsc.dll",
    "SCM / Identiv": "ctscm32.dll",
    "Kobil KAAN": "ctkobil.dll",
    "Orga / Sagem": "ctorg32.dll",
}
