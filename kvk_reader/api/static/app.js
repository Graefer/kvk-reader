/* KVK/eGK Reader — web UI.
 *
 * The browser is a remote control: the card reader, the label renderer and
 * the printer all live on the server. This file holds the patient currently
 * shown in THIS browser and sends it along for preview and printing, so two
 * workstations never print each other's card.
 */
(function () {
  'use strict';

  var FIELD_LABELS = [
    ['nachname', 'Nachname'],
    ['vorname', 'Vorname'],
    ['titel', 'Titel'],
    ['namenszusatz', 'Namenszusatz'],
    ['vorsatzwort', 'Vorsatzwort'],
    ['geburtsdatum', 'Geburtsdatum'],
    ['geschlecht', 'Geschlecht'],
    ['strasse', 'Straße'],
    ['hausnummer', 'Hausnummer'],
    ['plz', 'PLZ'],
    ['ort', 'Ort'],
    ['krankenkasse_name', 'Krankenkasse'],
    ['krankenkassen_nummer', 'Kassen-Nr. (IK)'],
    ['versichertennummer', 'Versichertennummer'],
    ['versichertenstatus', 'Versichertenstatus'],
    ['versichertenart', 'Versichertenart'],
    ['gueltig_bis', 'Gültig bis'],
    ['vknr', 'VKNR'],
    ['status_ergaenzung', 'Status-Ergänzung'],
    ['card_type', 'Kartentyp'],
    ['read_timestamp', 'Eingelesen']
  ];

  var KEY_STORAGE = 'kvk_api_key';
  var SORT_STORAGE = 'kvk_history_sort';
  var state = {
    patient: null, previewTimer: null, statusTimer: null, datumBox: null,
    records: [], sort: { field: 'einlesedatum', dir: 'desc' }
  };

  function $(id) { return document.getElementById(id); }

  function today() {
    var d = new Date();
    return String(d.getDate()).padStart(2, '0') + '.' +
           String(d.getMonth() + 1).padStart(2, '0') + '.' +
           d.getFullYear();
  }

  /* --- transport ---------------------------------------------------- */

  function apiKey() {
    try { return localStorage.getItem(KEY_STORAGE) || ''; } catch (e) { return ''; }
  }

  function storeApiKey(key) {
    try {
      if (key) { localStorage.setItem(KEY_STORAGE, key); }
      else { localStorage.removeItem(KEY_STORAGE); }
    } catch (e) { /* private mode — key stays for this page load only */ }
  }

  function api(path, options) {
    var opts = options || {};
    var headers = { 'Accept': 'application/json' };
    if (opts.body) { headers['Content-Type'] = 'application/json'; }
    var key = apiKey();
    if (key) { headers['X-API-Key'] = key; }

    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (res) {
      if (res.status === 401) {
        var entered = window.prompt('API-Schlüssel für den KVK-Reader:');
        if (entered) {
          storeApiKey(entered.trim());
          return api(path, options);
        }
        throw new Error('Nicht autorisiert');
      }
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) { throw new Error(data.error || ('Serverfehler ' + res.status)); }
        return data;
      });
    });
  }

  /* --- feedback ------------------------------------------------------ */

  function showBanner(message, isOk) {
    var banner = $('banner');
    $('banner-text').textContent = message;
    banner.classList.toggle('ok', !!isOk);
    banner.hidden = false;
    if (isOk) {
      window.setTimeout(function () { banner.hidden = true; }, 4000);
    }
  }

  function busy(text) {
    $('busy-text').textContent = text;
    $('busy').hidden = false;
  }

  function idle() { $('busy').hidden = true; }

  /* --- status -------------------------------------------------------- */

  function refreshStatus() {
    return api('/api/status').then(function (status) {
      $('version').textContent = 'v' + (status.version || '');

      var badge = $('reader-badge');
      var text = $('reader-text');
      badge.classList.toggle('online', !!status.reader_connected);
      badge.classList.toggle('offline', !status.reader_connected);

      if (status.reader_connected) {
        var index = status.reader_index || 0;
        var name = status.readers[index] || status.readers[0];
        text.textContent = name;
        badge.title = status.readers.join('\n');
      } else {
        text.textContent = status.reader_error
          ? 'Kartenleser: Fehler'
          : 'Kein Kartenleser';
        badge.title = status.reader_error || 'Am Server ist kein Leser angeschlossen';
      }

      $('btn-demo').hidden = !status.demo_mode;
      $('btn-read').disabled = false;
    }).catch(function () {
      var badge = $('reader-badge');
      badge.classList.remove('online');
      badge.classList.add('offline');
      $('reader-text').textContent = 'Server nicht erreichbar';
    });
  }

  /* --- patient display ----------------------------------------------- */

  function showPatient(patient) {
    state.patient = patient;

    var table = $('patient-table');
    var body = table.querySelector('tbody');
    body.textContent = '';

    FIELD_LABELS.forEach(function (pair) {
      var value = patient[pair[0]];
      if (value === undefined || value === null || value === '') { return; }
      var row = document.createElement('tr');
      var th = document.createElement('th');
      th.textContent = pair[1];
      var td = document.createElement('td');
      td.textContent = value;
      row.appendChild(th);
      row.appendChild(td);
      body.appendChild(row);
    });

    table.hidden = false;
    $('patient-empty').hidden = true;
    $('btn-print').disabled = false;
    updatePreview();
  }

  function clearPatient() {
    state.patient = null;
    $('patient-table').hidden = true;
    $('patient-empty').hidden = false;
    $('btn-print').disabled = true;
    $('preview-stage').hidden = true;
    $('preview-empty').hidden = false;
  }

  /* --- preview ------------------------------------------------------- */

  function updatePreview() {
    if (!state.patient) { return; }

    api('/api/label/preview', {
      method: 'POST',
      body: { patient: state.patient, datum: $('datum').value.trim() }
    }).then(function (data) {
      if (data.datum_box) { state.datumBox = data.datum_box; }
      $('preview-img').src = 'data:image/png;base64,' + data.png_base64;
      $('preview-stage').hidden = false;
      $('preview-empty').hidden = true;
      positionDatumField();
    }).catch(function (err) {
      showBanner('Vorschau fehlgeschlagen: ' + err.message);
    });
  }

  /* Places the date input exactly over the date rendered on the label.
     The server ships the rectangle with every preview, so the overlay
     follows the label layout instead of duplicating its geometry. */
  function positionDatumField() {
    var box = state.datumBox;
    var img = $('preview-img');
    var field = $('datum');
    if (!box || !img.naturalWidth) { return; }

    var scale = img.clientWidth / img.naturalWidth;
    var height = box.height * scale;

    field.style.left = (box.x * scale) + 'px';
    field.style.width = (box.width * scale) + 'px';
    field.style.height = height + 'px';
    field.style.fontSize = (box.font_size * scale) + 'px';
    field.style.lineHeight = height + 'px';

    // PIL setzt die Oberkante der Oberlaenge auf box.y, CSS zentriert den
    // Text in seiner Zeilenbox. Ueber Ascent/Descent rechnen wir die
    // Oberkante so, dass beide auf derselben Grundlinie sitzen.
    var top = box.y * scale;
    if (box.ascent) {
      var ascent = box.ascent * scale;
      var descent = (box.descent || 0) * scale;
      var baseline = (box.y + box.ascent) * scale;
      top = baseline - (height - (ascent + descent)) / 2 - ascent;
    }
    field.style.top = top + 'px';
  }

  function schedulePreview() {
    window.clearTimeout(state.previewTimer);
    state.previewTimer = window.setTimeout(updatePreview, 350);
  }

  /* --- actions -------------------------------------------------------- */

  function readCard() {
    busy('Karte wird gelesen…');
    api('/api/patient/read', { method: 'POST' }).then(function (patient) {
      $('datum').value = today();
      showPatient(patient);
      showBanner(patient.nachname + ', ' + patient.vorname +
                 ' (' + patient.card_type + ') eingelesen', true);
      loadHistory();
    }).catch(function (err) {
      showBanner(err.message);
    }).then(idle);
  }

  function loadDemo() {
    busy('Demo-Daten werden geladen…');
    api('/api/demo', { method: 'POST' }).then(function (patient) {
      $('datum').value = today();
      showPatient(patient);
      loadHistory();
    }).catch(function (err) {
      showBanner(err.message);
    }).then(idle);
  }

  function printLabel() {
    if (!state.patient) { return; }
    var copies = parseInt($('copies').value, 10) || 1;

    busy('Etikett wird gedruckt…');
    api('/api/print', {
      method: 'POST',
      body: { patient: state.patient, datum: $('datum').value.trim(), copies: copies }
    }).then(function (result) {
      showBanner(result.copies + '× Etikett gedruckt', true);
    }).catch(function (err) {
      showBanner('Druck fehlgeschlagen: ' + err.message);
    }).then(idle);
  }

  /* --- history -------------------------------------------------------- */

  function loadHistory() {
    return api('/api/history').then(function (records) {
      state.records = records;
      renderHistory();
    }).catch(function (err) {
      showBanner('Historie konnte nicht geladen werden: ' + err.message);
    });
  }

  /* The whole history (at most 250 rows) is already in the browser, so
     sorting happens here — no round trip, and the order survives a delete. */
  function renderHistory() {
    var list = $('history-list');
    var sichtbar = sortedRecords();
    var gesamt = state.records.length;

    list.textContent = '';
    $('history-count').textContent = sichtbar.length === gesamt
      ? (gesamt ? '(' + gesamt + ')' : '')
      : '(' + sichtbar.length + ' von ' + gesamt + ')';
    updateSortButtons();
    $('btn-liste-drucken').disabled = sichtbar.length === 0;

    if (!sichtbar.length) {
      var empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = gesamt
        ? 'Keine Einträge im gewählten Zeitraum.'
        : 'Noch keine Einträge.';
      list.appendChild(empty);
      return;
    }

    sichtbar.forEach(function (record) {
      list.appendChild(historyRow(record));
    });
  }

  /* "17:11, 03.06.2026" — sorts wrong as text, so parse it properly. */
  function parseTimestamp(value) {
    var m = /^(\d{1,2}):(\d{2}),\s*(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(value || '');
    if (!m) { return 0; }
    return new Date(+m[5], +m[4] - 1, +m[3], +m[1], +m[2]).getTime();
  }

  /* Der Zeitraumfilter arbeitet auf dem Einlesedatum. Leere Felder heben
     die jeweilige Grenze auf; beide leer zeigt alles. */
  function rangeBounds() {
    var von = $('filter-von').value;
    var bis = $('filter-bis').value;
    return {
      from: von ? new Date(von + 'T00:00:00').getTime() : null,
      to: bis ? new Date(bis + 'T23:59:59').getTime() : null
    };
  }

  function inRange(record, bounds) {
    if (bounds.from === null && bounds.to === null) { return true; }
    var stamp = parseTimestamp(record.einlesedatum);
    if (!stamp) { return false; }
    if (bounds.from !== null && stamp < bounds.from) { return false; }
    if (bounds.to !== null && stamp > bounds.to) { return false; }
    return true;
  }

  function filteredRecords() {
    var bounds = rangeBounds();
    return state.records.filter(function (record) {
      return inRange(record, bounds);
    });
  }

  function sortedRecords() {
    var field = state.sort.field;
    var factor = state.sort.dir === 'asc' ? 1 : -1;

    return filteredRecords().sort(function (a, b) {
      var result;
      if (field === 'einlesedatum') {
        result = parseTimestamp(a.einlesedatum) - parseTimestamp(b.einlesedatum);
        if (result === 0) { result = (a.id || 0) - (b.id || 0); }
      } else {
        result = (a.nachname || '').localeCompare(b.nachname || '', 'de',
                                                 { sensitivity: 'base' });
        if (result === 0) {
          result = (a.vorname || '').localeCompare(b.vorname || '', 'de',
                                                   { sensitivity: 'base' });
        }
      }
      return result * factor;
    });
  }

  function updateSortButtons() {
    var arrow = state.sort.dir === 'asc' ? ' ↑' : ' ↓';
    $('filter-von').addEventListener('change', renderHistory);
    $('filter-bis').addEventListener('change', renderHistory);
    $('btn-filter-reset').addEventListener('click', function () {
      $('filter-von').value = '';
      $('filter-bis').value = '';
      renderHistory();
    });
    $('btn-liste-drucken').addEventListener('click', printList);

    document.querySelectorAll('button.sort').forEach(function (button) {
      var field = button.getAttribute('data-sort');
      var active = field === state.sort.field;
      button.classList.toggle('active', active);
      button.textContent = (field === 'nachname' ? 'Name' : 'Datum') + (active ? arrow : '');
      button.title = active
        ? 'Klicken kehrt die Reihenfolge um'
        : 'Nach diesem Feld sortieren';
    });
  }

  function changeSort(field) {
    if (state.sort.field === field) {
      state.sort.dir = state.sort.dir === 'asc' ? 'desc' : 'asc';
    } else {
      // Names read naturally A→Z, dates most-recent-first.
      state.sort = { field: field, dir: field === 'nachname' ? 'asc' : 'desc' };
    }
    try {
      localStorage.setItem(SORT_STORAGE, JSON.stringify(state.sort));
    } catch (e) { /* private mode — order just resets on reload */ }
    renderHistory();
  }

  function restoreSort() {
    try {
      var stored = JSON.parse(localStorage.getItem(SORT_STORAGE) || 'null');
      if (stored && (stored.field === 'nachname' || stored.field === 'einlesedatum')
          && (stored.dir === 'asc' || stored.dir === 'desc')) {
        state.sort = stored;
      }
    } catch (e) { /* keep the default */ }
  }

  function historyRow(record) {
    var item = document.createElement('li');

    var main = document.createElement('span');
    main.className = 'hist-main';
    main.title = 'Datensatz anzeigen';

    var name = document.createElement('span');
    name.className = 'hist-name';
    name.textContent = [record.nachname, record.vorname].filter(Boolean).join(', ');

    var meta = document.createElement('span');
    meta.className = 'hist-meta';
    meta.textContent = [record.geburtsdatum, record.einlesedatum]
      .filter(Boolean).join(' · ');

    main.appendChild(name);
    main.appendChild(meta);
    main.addEventListener('click', function () {
      $('datum').value = today();
      showPatient(record);
    });

    var type = document.createElement('span');
    type.className = 'hist-type';
    type.textContent = record.card_type || '?';

    var del = document.createElement('button');
    del.className = 'hist-del';
    del.innerHTML = '&times;';
    del.title = 'Eintrag löschen';
    del.addEventListener('click', function () {
      if (!window.confirm('Diesen Eintrag löschen?')) { return; }
      api('/api/history/' + record.id, { method: 'DELETE' }).then(function () {
        loadHistory();
      }).catch(function (err) {
        showBanner('Löschen fehlgeschlagen: ' + err.message);
      });
    });

    item.appendChild(main);
    item.appendChild(type);
    item.appendChild(del);
    return item;
  }

  /* --- Liste drucken (DIN A4 quer) ------------------------------------ */

  function esc(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function vollerName(r) {
    var teile = [r.nachname, r.vorname].filter(Boolean).join(', ');
    var zusatz = [r.vorsatzwort, r.namenszusatz, r.titel].filter(Boolean).join(' ');
    return zusatz ? teile + ' (' + zusatz + ')' : teile;
  }

  function anschrift(r) {
    var strasse = r.strasse || '';
    if (r.hausnummer && strasse.indexOf(r.hausnummer) === -1) {
      strasse = (strasse + ' ' + r.hausnummer).trim();
    }
    return strasse;
  }

  function wohnort(r) {
    var ort = [r.plz, r.ort].filter(Boolean).join(' ');
    var land = r.wohnsitzlaendercode;
    return land && land !== 'D' ? ort + ' (' + land + ')' : ort;
  }

  function statusArt(r) {
    var s = [r.versichertenstatus, r.status_ergaenzung].filter(Boolean).join('');
    return [s, r.versichertenart].filter(Boolean).join(' / ');
  }

  var SPALTEN = [
    ['Nr.', function (r, i) { return i + 1; }],
    ['Name, Vorname', vollerName],
    ['geb. am', function (r) { return r.geburtsdatum; }],
    ['G.', function (r) { return r.geschlecht; }],
    ['Straße', anschrift],
    ['PLZ / Ort', wohnort],
    ['Krankenkasse', function (r) { return r.krankenkasse_name; }],
    ['Kassen-Nr.', function (r) { return r.krankenkassen_nummer; }],
    ['Versicherten-Nr.', function (r) { return r.versichertennummer; }],
    ['St./Art', statusArt],
    ['gültig bis', function (r) { return r.gueltig_bis; }],
    ['VKNR', function (r) { return r.vknr; }],
    ['Typ', function (r) { return r.card_type; }],
    ['Eingelesen', function (r) { return r.einlesedatum; }]
  ];

  function zeitraumText() {
    var von = $('filter-von').value;
    var bis = $('filter-bis').value;
    var fmt = function (iso) {
      var t = iso.split('-');
      return t[2] + '.' + t[1] + '.' + t[0];
    };
    if (von && bis) { return fmt(von) + ' bis ' + fmt(bis); }
    if (von) { return 'ab ' + fmt(von); }
    if (bis) { return 'bis ' + fmt(bis); }
    return 'gesamter Zeitraum';
  }

  function printList() {
    var records = sortedRecords();
    if (!records.length) {
      showBanner('Keine Einträge im gewählten Zeitraum.');
      return;
    }

    busy('Liste wird aufbereitet…');
    api('/api/settings').catch(function () { return {}; }).then(function (cfg) {
      var fenster = window.open('', '_blank');
      if (!fenster) {
        showBanner('Der Browser hat das Druckfenster blockiert — bitte Pop-ups für diese Seite erlauben.');
        return;
      }
      fenster.document.open();
      fenster.document.write(berichtHtml(records, cfg));
      fenster.document.close();
      fenster.focus();
    }).then(idle);
  }

  function berichtHtml(records, cfg) {
    var kopf = SPALTEN.map(function (s) {
      return '<th>' + esc(s[0]) + '</th>';
    }).join('');

    var zeilen = records.map(function (r, i) {
      return '<tr>' + SPALTEN.map(function (s) {
        return '<td>' + esc(s[1](r, i)) + '</td>';
      }).join('') + '</tr>';
    }).join('');

    var praxis = [cfg['praxis/bsnr'] ? 'BSNR ' + cfg['praxis/bsnr'] : '',
                  cfg['praxis/lanr'] ? 'LANR ' + cfg['praxis/lanr'] : '']
                 .filter(Boolean).join(' · ');
    var titel = 'Eingelesene Karten — ' + zeitraumText();

    return '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">' +
      '<title>' + esc(titel) + '</title><style>' +
      '@page { size: A4 landscape; margin: 12mm 10mm 14mm; }' +
      'body { font-family: "Segoe UI", Arial, sans-serif; font-size: 7.5pt; color: #000; margin: 0; }' +
      'header { margin-bottom: 4mm; }' +
      'h1 { font-size: 12pt; margin: 0 0 1mm; }' +
      '.meta { font-size: 8pt; color: #333; }' +
      'table { width: 100%; border-collapse: collapse; }' +
      'thead { display: table-header-group; }' +
      'th { text-align: left; font-size: 7pt; text-transform: uppercase; letter-spacing: .02em;' +
      '     border-bottom: .6pt solid #000; padding: 1mm .8mm; }' +
      'td { border-bottom: .3pt solid #bbb; padding: 1.1mm .8mm; vertical-align: top; }' +
      'tr { page-break-inside: avoid; }' +
      'td:first-child, th:first-child { text-align: right; color: #555; }' +
      '.toolbar { padding: 8px; background: #eef1f5; margin-bottom: 6mm; font-family: sans-serif; }' +
      '.toolbar button { font-size: 13px; padding: 6px 14px; cursor: pointer; }' +
      '@media print { .toolbar { display: none; } }' +
      '</style></head><body>' +
      '<div class="toolbar"><button onclick="window.print()">Drucken</button>' +
      '&nbsp;&nbsp;<span>DIN A4 quer — falls der Druckdialog nicht erscheint: Strg+P</span></div>' +
      '<header><h1>' + esc(titel) + '</h1><div class="meta">' +
      esc(records.length) + ' Datensätze' + (praxis ? ' · ' + esc(praxis) : '') +
      ' · gedruckt am ' + esc(today()) + '</div></header>' +
      '<table><thead><tr>' + kopf + '</tr></thead><tbody>' + zeilen + '</tbody></table>' +
      '<script>window.onload = function () { window.print(); };<\/script>' +
      '</body></html>';
  }

  /* --- settings ------------------------------------------------------- */

  function openSettings() {
    busy('Einstellungen werden geladen…');
    Promise.all([api('/api/settings'), api('/api/readers')])
      .then(function (results) {
        fillSettings(results[0], results[1].readers || []);
        $('settings-modal').hidden = false;
      })
      .catch(function (err) { showBanner(err.message); })
      .then(idle);
  }

  function fillSettings(values, readers) {
    document.querySelectorAll('[data-key]').forEach(function (input) {
      var key = input.getAttribute('data-key');
      if (input.type === 'checkbox') {
        input.checked = values[key] === true || values[key] === 'true';
      } else if (key !== 'api/key') {
        input.value = values[key] === undefined || values[key] === null ? '' : values[key];
      } else {
        input.value = '';
      }
    });

    $('key-hint').textContent = values['api/key_set'] ? '(gesetzt)' : '(nicht gesetzt)';

    var select = $('reader-select');
    select.textContent = '';
    if (!readers.length) {
      var none = document.createElement('option');
      none.value = '0';
      none.textContent = 'Kein Kartenleser gefunden';
      select.appendChild(none);
    } else {
      readers.forEach(function (name, index) {
        var option = document.createElement('option');
        option.value = String(index);
        option.textContent = index + ': ' + name;
        select.appendChild(option);
      });
    }
    select.value = String(values['reader/index'] || 0);

    var datalist = $('ct-api-list');
    datalist.textContent = '';
    Object.keys(values.ct_api_dlls || {}).forEach(function (vendor) {
      var option = document.createElement('option');
      option.value = values.ct_api_dlls[vendor];
      option.label = vendor;
      datalist.appendChild(option);
    });

    var printers = $('printer-list');
    printers.textContent = '';
    (values.windows_printers || []).forEach(function (name) {
      var option = document.createElement('option');
      option.value = name;
      printers.appendChild(option);
    });
  }

  function saveSettings() {
    var payload = {};
    document.querySelectorAll('[data-key]').forEach(function (input) {
      var key = input.getAttribute('data-key');
      if (input.type === 'checkbox') {
        payload[key] = input.checked;
      } else if (input.type === 'number') {
        payload[key] = parseInt(input.value, 10) || 0;
      } else {
        payload[key] = input.value.trim();
      }
    });

    // A typed key must also be stored locally, or the next request is 401.
    var typedKey = payload['api/key'];

    busy('Einstellungen werden gespeichert…');
    api('/api/settings', { method: 'PUT', body: payload }).then(function () {
      if (typedKey) { storeApiKey(typedKey); }
      $('settings-modal').hidden = true;
      showBanner('Einstellungen gespeichert', true);
      return Promise.all([refreshStatus(), applyDefaults()]);
    }).catch(function (err) {
      showBanner('Speichern fehlgeschlagen: ' + err.message);
    }).then(idle);
  }

  function clearApiKey() {
    if (!window.confirm('API-Schlüssel entfernen? Danach ist der Server ungeschützt.')) {
      return;
    }
    api('/api/settings', { method: 'PUT', body: { 'api/key': null } }).then(function () {
      storeApiKey('');
      $('key-hint').textContent = '(nicht gesetzt)';
      showBanner('API-Schlüssel entfernt', true);
    }).catch(function (err) {
      showBanner(err.message);
    });
  }

  function applyDefaults() {
    return api('/api/settings').then(function (values) {
      $('copies').value = values['label/copies_default'] || 1;
    }).catch(function () { /* keep the current value */ });
  }

  /* --- wiring --------------------------------------------------------- */

  function init() {
    $('datum').value = today();

    $('btn-read').addEventListener('click', readCard);
    $('btn-demo').addEventListener('click', loadDemo);
    $('btn-print').addEventListener('click', printLabel);
    $('datum').addEventListener('input', schedulePreview);
    $('datum').addEventListener('focus', function () { this.select(); });
    $('datum').addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); this.blur(); }
    });
    $('preview-img').addEventListener('load', positionDatumField);
    window.addEventListener('resize', positionDatumField);
    $('banner-close').addEventListener('click', function () { $('banner').hidden = true; });

    document.querySelectorAll('button.sort').forEach(function (button) {
      button.addEventListener('click', function () {
        changeSort(button.getAttribute('data-sort'));
      });
    });

    $('btn-settings').addEventListener('click', openSettings);
    $('btn-settings-save').addEventListener('click', saveSettings);
    $('btn-settings-cancel').addEventListener('click', function () {
      $('settings-modal').hidden = true;
    });
    $('btn-clear-key').addEventListener('click', clearApiKey);
    $('settings-modal').addEventListener('click', function (event) {
      if (event.target === $('settings-modal')) { $('settings-modal').hidden = true; }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'F5') { event.preventDefault(); readCard(); }
      if (event.key === 'F6') { event.preventDefault(); printLabel(); }
      if (event.key === 'Escape') { $('settings-modal').hidden = true; }
    });

    restoreSort();
    updateSortButtons();
    clearPatient();
    refreshStatus();
    applyDefaults();
    loadHistory();
    state.statusTimer = window.setInterval(refreshStatus, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
