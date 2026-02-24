# KVK/eGK Reader — Installationsanleitung Windows 7

## Voraussetzungen

- Windows 7 SP1 (64-bit)
- Update KB2533623 installiert (über Windows Update)
- USB-Kartenleser (z.B. Cherry ST-2100, HID Omnikey 3121)
- Brother QL-800 Etikettendrucker mit DK-22223 (50mm Endlos)

---

# Weg A: Fertige EXE installieren (empfohlen)

> Kein Python nötig! Die EXE enthält alles (Python, PyQt5, alle Bibliotheken).

## A1: Brother QL-800 USB-Treiber einrichten

Der Etikettendrucker wird NICHT über den normalen Brother-Treiber
angesprochen, sondern direkt über USB (libusb).

1. **Zadig** herunterladen: https://zadig.akeo.ie/
2. Brother QL-800 per USB anschließen
3. Zadig starten
4. Menü: Options → "List All Devices" aktivieren
5. Im Dropdown "Brother QL-800" auswählen
6. Treiber auf **WinUSB** oder **libusb-win32** setzen
7. "Replace Driver" klicken

**Achtung:** Nach dieser Änderung funktioniert der Brother-Druckertreiber
für normale Windows-Programme nicht mehr. Um ihn zurückzusetzen:
Geräte-Manager → Brother QL-800 → Treiber → Zurücksetzen.

## A2: CT-API Treiber installieren (für KVK/PKV-Karten)

Für das Lesen von **KVK/PKV-Speicherkarten** (SLE4428) wird eine herstellerspezifische
CT-API DLL benötigt. Für **eGK** allein ist dieser Schritt nicht nötig.

1. Den Treiber des Kartenlesers vom Hersteller installieren
2. Die CT-API DLL sollte danach im Windows-System vorhanden sein

| Kartenleser | CT-API DLL | Treiberquelle |
|---|---|---|
| Cherry ST-2100 | `ctpcsc32.dll` | Cherry SmartCard Toolbox |
| HID Omnikey 3121 | `ctomni532.dll` | HID Global Treiber |
| Reiner SCT cyberJack | `ctrsct32.dll` | reiner-sct.com |
| SCM / Identiv | `ctscm32.dll` | Identiv Treiber |

**Hinweis:** Manche Treiber-Installer legen die DLL automatisch in `C:\Windows\System32\`.
Falls nicht, die DLL neben die `KVK-Reader.exe` kopieren.

## A3: EXE kopieren und starten

1. `KVK-Reader.exe` auf den PC kopieren, z.B. nach `C:\KVK-Reader\`
2. Kartenleser per USB anschließen
3. `KVK-Reader.exe` starten

## A4: Ersteinrichtung

Beim ersten Start:
1. **Einstellungen** öffnen (Toolbar oder Ctrl+,)
2. **Praxisdaten** eintragen:
   - Betriebsstätten-Nr. (BSNR)
   - Arzt-Nr. (LANR)
3. **Kartenleser** sollte automatisch erkannt werden
4. **CT-API DLL (KVK):** Name der DLL eintragen (z.B. `ctpcsc32.dll`)
   oder über "Auswählen..." die DLL-Datei suchen.
   Alternativ: Hersteller-Vorlage aus dem Dropdown wählen.
5. **Drucker-URI** prüfen (Standard: `usb://0x04F9:0x209B`)
6. OK klicken

> **Ohne CT-API DLL** werden nur eGK-Karten gelesen. KVK/PKV funktioniert
> dann nur mit Lesern, die Speicherkarten über PC/SC unterstützen (z.B. Cherry ST-2100).

## A5: Desktop-Verknüpfung erstellen (optional)

Rechtsklick auf `KVK-Reader.exe` → "Senden an" → "Desktop (Verknüpfung erstellen)"

---

# Weg B: Aus Quellcode starten (für Entwicklung)

> Nur nötig, wenn man den Code ändern oder die EXE selbst bauen will.
> Funktioniert auch auf Windows 10/11 — der Entwicklungsrechner muss nicht Windows 7 sein.

## B1: Python 3.8 installieren

**Wichtig:** Für Windows-7-kompatible EXEs muss Python **3.8** verwendet werden
(nicht 3.9+). Python 3.8 lässt sich problemlos auf Windows 10/11 installieren,
auch neben einer neueren Python-Version.

**Wichtig:** Die **32-Bit** Version verwenden! Die meisten CT-API Treiber
liefern nur 32-Bit DLLs. Eine 64-Bit EXE kann keine 32-Bit DLL laden.

1. Herunterladen: https://www.python.org/downloads/release/python-3817/
   → **Windows x86 executable installer** (NICHT x86-64!)
2. Installer starten
3. **Wichtig:** Haken bei "Add Python 3.8 to PATH" setzen
   (Falls bereits ein neueres Python installiert ist: Haken weglassen
   und stattdessen den Installationspfad merken, z.B. `C:\Python38\`)
4. "Install Now" klicken
5. Prüfen: Eingabeaufforderung (cmd) öffnen und eingeben:
   ```
   python --version
   ```
   Ausgabe sollte sein: `Python 3.8.17` (oder ähnlich)

### PATH nachträglich setzen (falls Haken vergessen)

Falls `python --version` nicht funktioniert oder die falsche Version zeigt:

**Variante 1: Installer erneut ausführen**
1. Den gleichen Python-3.8-Installer nochmal starten
2. "Modify" wählen → "Next"
3. Haken bei "Add Python to environment variables" setzen
4. "Install" klicken

**Variante 2: Manuell in der Systemsteuerung**
1. Systemsteuerung → System → Erweiterte Systemeinstellungen → Umgebungsvariablen
2. Unter "Benutzervariablen" die Variable `Path` bearbeiten
3. Zwei Einträge hinzufügen (Standardpfade):
   ```
   C:\Users\<BENUTZERNAME>\AppData\Local\Programs\Python\Python38\
   C:\Users\<BENUTZERNAME>\AppData\Local\Programs\Python\Python38\Scripts\
   ```
4. OK → neues cmd-Fenster öffnen → `python --version` prüfen

> **Hinweis für Entwickler mit Python 3.12:** Falls Python 3.12 bereits als
> Standard installiert ist, das venv gezielt mit Python 3.8 erstellen:
> ```cmd
> C:\Python38\python.exe -m venv venv
> ```
> Der restliche Code ist mit Python 3.8–3.12 kompatibel.

## B2: Projekt kopieren

Den Ordner `kvk-reader` auf den Windows-PC kopieren, z.B. nach:
```
C:\kvk-reader\
```

## B3: Virtuelle Umgebung erstellen und Abhängigkeiten installieren

Eingabeaufforderung (cmd) als Administrator öffnen:

```cmd
cd C:\kvk-reader

python -m venv venv

venv\Scripts\activate

python -m pip install --upgrade pip

pip install PyQt5 pyscard Pillow lxml flask brother-ql
```

### Falls pyscard nicht installiert werden kann:

pyscard benötigt den PC/SC-Dienst (unter Windows 7 standardmäßig aktiv).
Falls der Build fehlschlägt, vorher installieren:
- Microsoft Visual C++ Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/
- Oder das vorkompilierte Wheel verwenden:
  ```cmd
  pip install https://github.com/LudovicRousseau/pyscard/releases/download/v2.0.10/pyscard-2.0.10-cp38-cp38-win_amd64.whl
  ```

## B4: Brother QL-800 USB-Treiber einrichten

→ Siehe **Schritt A1** oben (identisch).

## B5: Anwendung starten

```cmd
cd C:\kvk-reader
venv\Scripts\activate
python -m kvk_reader.main
```

Ersteinrichtung → siehe **Schritt A3** oben.

## B6: Verknüpfung erstellen (optional)

Für den Desktop eine Verknüpfung erstellen:

- Ziel: `C:\kvk-reader\venv\Scripts\pythonw.exe -m kvk_reader.main`
- Ausführen in: `C:\kvk-reader`

Oder eine Batch-Datei `C:\kvk-reader\start.bat` erstellen:
```bat
@echo off
cd /d C:\kvk-reader
venv\Scripts\pythonw.exe -m kvk_reader.main
```

## B7: Als EXE packen

Um die fertige EXE zu erzeugen (für Weg A):

```cmd
cd C:\kvk-reader
venv\Scripts\activate
pip install pyinstaller
pyinstaller kvk-reader.spec
```

Die fertige EXE liegt dann unter `dist\KVK-Reader.exe`.
Diese Datei kann ohne Python auf jedem Windows 7 (64-bit) PC genutzt werden.

> **Wichtig:** Die EXE ist nur mit dem Windows kompatibel, das auch die
> eingebettete Python-Version unterstützt. Für Windows 7 muss das venv
> mit **Python 3.8** erstellt worden sein (siehe B1). Eine mit Python 3.12
> gebaute EXE läuft erst ab Windows 8.1.

---

# Bedienung

| Taste | Aktion |
|-------|--------|
| **F5** | Karte lesen |
| **F6** | Etikett drucken |
| **Ctrl+,** | Einstellungen |

## REST API (für andere Programme)

Wenn aktiviert (Standard: ja), läuft ein lokaler Webserver:

```
GET  http://localhost:8899/api/patient      → Patientendaten abrufen
GET  http://localhost:8899/api/patient/read  → Karte lesen + Daten zurückgeben
POST http://localhost:8899/api/print         → Etikett drucken (Body: {"copies": 3})
GET  http://localhost:8899/api/status        → Reader/Drucker Status
```

---

# Fehlerbehebung

### "Kein Kartenleser gefunden"
- Ist der Kartenleser per USB angeschlossen?
- PC/SC-Dienst prüfen: `services.msc` → "Smart Card" Dienst muss laufen

### "pyscard nicht verfügbar" (nur Weg B)
- `pip install pyscard` erneut ausführen
- ggf. C++ Build Tools installieren (siehe Schritt B3)

### Drucker druckt nicht
- Zadig-Treiber korrekt installiert? (Schritt A1)
- Drucker-URI in Einstellungen prüfen
- Testbefehl (nur Weg B): `python -c "from brother_ql.backends.helpers import discover; print(discover('pyusb'))"`

### PKV/KVK-Karte wird nicht gelesen (nur eGK funktioniert)
- **CT-API DLL konfiguriert?** In Einstellungen → "CT-API DLL (KVK)" prüfen
- DLL muss zum Kartenleser passen (siehe Tabelle in Schritt A2)
- DLL muss im System-Pfad oder neben der EXE liegen
- CT-API Port-Nr. ist meist 1 (herstellerspezifisch)
- Ohne CT-API: Nur Leser mit PC/SC-Speicherkartenunterstützung (z.B. Cherry ST-2100)

### "CT-API DLL nicht gefunden"
- Kartenleser-Treiber vom Hersteller installiert?
- DLL-Name korrekt? Übliche Namen: `ctpcsc32.dll`, `ctrsct32.dll`, `ctomni532.dll`
- DLL in `C:\Windows\System32\` oder im EXE-Ordner vorhanden?
