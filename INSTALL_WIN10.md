# KVK/eGK Reader 2.0 — Installation als Server (Windows 10)

Ab Version 2.0 läuft die Anwendung als **Server**: Der Kartenleser steckt an
diesem einen Rechner, bedient wird sie von jedem Arbeitsplatz im Praxisnetz
über den Browser. Ein Programmfenster gibt es im Normalbetrieb nicht mehr.

Zielsystem in dieser Praxis: **Windows-10-VM auf Proxmox, 192.168.5.177**.

---

## 1. Python installieren

**32-Bit-Version verwenden (x86, nicht x86-64).** Die CT-API-Treiber der
Kartenleser liefern überwiegend nur 32-Bit-DLLs, und Windows lädt eine DLL
nur in einen Prozess gleicher Bitness. Eine 64-Bit-Installation kann diese
Treiber nicht ansprechen.

1. Download: https://www.python.org/downloads/windows/
   → **Windows installer (32-bit)**, Python 3.12
2. Im Installer **„Add python.exe to PATH"** ankreuzen
3. Prüfen (Eingabeaufforderung):
   ```cmd
   python --version
   python -c "import struct; print(struct.calcsize('P')*8)"
   ```
   Erwartet: `Python 3.12.x` und `32`

## 2. Programm holen

```cmd
cd C:\
git clone https://github.com/Graefer/kvk-reader.git
cd kvk-reader
```

Ohne Git: ZIP von GitHub herunterladen und nach `C:\kvk-reader\` entpacken.

## 3. Abhängigkeiten installieren

```cmd
cd C:\kvk-reader
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
```

`requirements.txt` enthält bewusst **kein PyQt5** — der Server braucht keine
Oberfläche. Wer zusätzlich das alte Fenster will: `pip install -r requirements-gui.txt`.

> Falls `pyscard` nicht baut, das vorkompilierte Wheel passend zur
> **32-Bit-**Installation nehmen (Dateiname endet auf `win32`, nicht `win_amd64`):
> https://github.com/LudovicRousseau/pyscard/releases

## 4. Kartenleser-Treiber

| Leser | Was installieren | Hinweis |
|---|---|---|
| HID Omnikey 3121 | HID-Treiberpaket inkl. Sync-API | Für KVK/PKV nötig; die passende DLL-Variante (`scardsyn.dll` / `scardsynx64.dll`) wählt das Programm selbst |
| Cherry ST-2100 | Cherry SmartCard Toolbox | KVK teils schon über PC/SC lesbar |
| Reiner SCT cyberJack | Treiber von reiner-sct.com | CT-API `ctrsct32.dll` |

Für **eGK allein** genügt der in Windows enthaltene CCID-Treiber; ein
CT-API-Treiber ist dann nicht nötig.

Prüfen: Der Leser muss im Geräte-Manager unter „Smartcard-Lesegeräte" ohne
gelbes Ausrufezeichen erscheinen, und der Dienst **„Smartcard"**
(`services.msc`) muss laufen.

## 5. Erster Start

```cmd
cd C:\kvk-reader
venv\Scripts\python -m kvk_reader.main --server
```

Im Log erscheint die erreichbare Adresse, z. B.
`Bedienoberfläche: http://192.168.5.177:8899/`.

Diese Adresse im Browser öffnen — auch von einem anderen Rechner aus.

## 6. Firewall freigeben

Ohne diese Regel ist der Server nur lokal erreichbar. In einer
Eingabeaufforderung **als Administrator**:

```cmd
netsh advfirewall firewall add rule name="KVK-Reader 8899" dir=in action=allow protocol=TCP localport=8899
```

> Dass die VM nicht auf `ping` antwortet, ist normal — Windows blockt ICMP
> standardmäßig. Das sagt nichts über die Erreichbarkeit von Port 8899 aus.

## 7. Einstellungen im Browser

Oben rechts auf **Einstellungen**:

- **Praxis:** BSNR und LANR — erscheinen auf dem Etikett
- **Kartenleser:** Leser auswählen; für KVK/PKV ggf. CT-API-DLL eintragen
- **Drucker:** siehe nächster Abschnitt
- **API-Schlüssel:** optional. Gesetzt schützt er alle Endpunkte; die
  Weboberfläche fragt ihn dann einmalig ab und merkt ihn sich im Browser.

## 8. Etikettendrucker

Gedruckt wird **vom Server aus**, nicht vom Browser-Rechner.

**Brother QL im WLAN** (Modelle QL-810W / QL-820NWB):
feste IP vergeben, dann in den Einstellungen
`Drucker-URI` = `tcp://192.168.5.x` und `Modell` passend zum Gerät setzen
(brother_ql rastert modellabhängig — ein falsches Modell druckt Müll).

**Über den Windows-Treiber** (auch für Netzwerkdrucker): Brother-Treiber
installieren, in den Druckeinstellungen Bandbreite 50 mm / Länge 80 mm
einstellen und in den KVK-Einstellungen den `Windows-Druckername` eintragen
(leer = automatische Suche nach einem Brother-QL-Gerät). Dieser Weg braucht
kein libusb/Zadig.

## 9. Autostart einrichten

Damit der Server nach jedem VM-Neustart von selbst läuft. Aufgabenplanung
(`taskschd.msc`) → **Aufgabe erstellen**:

- **Allgemein:** „Unabhängig von der Benutzeranmeldung ausführen",
  „Mit höchsten Privilegien ausführen"
- **Trigger:** Beim Start des Computers
- **Aktionen:** Programm starten
  - Programm: `C:\kvk-reader\venv\Scripts\pythonw.exe`
  - Argumente: `-m kvk_reader.main --server`
  - Starten in: `C:\kvk-reader`
- **Einstellungen:** „Neu starten, falls Fehler" aktivieren

> **Wichtig bei Ausführung als SYSTEM:** `%APPDATA%` zeigt dann nicht auf das
> Benutzerprofil, die Konfiguration aus Schritt 7 wäre nicht auffindbar.
> Deshalb das Datenverzeichnis fest vorgeben — Systemumgebungsvariable
> `KVK_DATA_DIR` = `C:\kvk-reader\data` setzen (Systemsteuerung → System →
> Erweiterte Systemeinstellungen → Umgebungsvariablen → Systemvariablen),
> danach die Aufgabe neu starten.

Der PC/SC-Dienst funktioniert auch in Session 0, ein angemeldeter Benutzer
ist für den Kartenleser also nicht erforderlich.

## 10. Wo liegen Daten und Log?

Im Datenverzeichnis — `%APPDATA%\KVKReader\` oder das per `KVK_DATA_DIR`
gesetzte Verzeichnis:

| Datei | Inhalt |
|---|---|
| `config.json` | Einstellungen |
| `kvk_reader.db` | Historie der letzten 250 Lesevorgänge |
| `kvk_reader.log` | Protokoll des letzten Laufs |

## 11. Aktualisieren

```cmd
cd C:\kvk-reader
git pull
venv\Scripts\pip install -r requirements.txt
```

Danach die geplante Aufgabe neu starten. Einstellungen und Historie bleiben
erhalten, weil sie außerhalb des Programmverzeichnisses liegen.

---

# Fehlerbehebung

### Weboberfläche von anderen Rechnern nicht erreichbar
- Firewall-Regel aus Schritt 6 gesetzt?
- Läuft der Server? `netstat -an | findstr 8899` muss `LISTENING` zeigen.

### „Kein Kartenleser" trotz angeschlossenem Gerät
- Dienst „Smartcard" in `services.msc` gestartet?
- Leser im Geräte-Manager ohne Fehler?
- Nach dem Einstecken einige Sekunden warten — die Liste wird alle 5 s neu geprüft.

### eGK wird gelesen, KVK/PKV nicht
- CT-API-DLL in den Einstellungen eingetragen und zum Leser passend?
- **Bitness:** Fehler `[WinError 193] keine zulässige Win32-Anwendung` heißt,
  die DLL hat die falsche Bitness (siehe Schritt 1). `[WinError 126]` heißt
  dagegen, die Datei wurde nicht gefunden.
- Auf 64-Bit-Windows liegen 32-Bit-DLLs in `C:\Windows\SysWOW64\`, nicht in
  `System32`. Sicherste Variante: die DLL nach `C:\kvk-reader\` kopieren.

### Druck schlägt fehl
- Bei `tcp://`: Drucker-IP erreichbar, Modell korrekt eingetragen?
- Über den Windows-Treiber: Druckername exakt wie in „Geräte und Drucker"?

### Server startet nicht
`kvk_reader.log` und `kvk_reader_crash.log` im Datenverzeichnis prüfen.
Zum Mitlesen im Vordergrund starten:
```cmd
venv\Scripts\python -m kvk_reader.main --server
```
