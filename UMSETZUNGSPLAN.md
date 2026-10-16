# Plantdiary – Umsetzungsplan & Stand der Umsetzung

*Ursprünglich erstellt am 28. September 2026 als Plan vor Baubeginn. Aktualisiert am 15. Oktober 2026 auf den tatsächlichen Umsetzungsstand.*

Dieses Dokument fasste ursprünglich die Ideen aus der gemeinsamen Planungsrunde zusammen und schlug eine Umsetzungsreihenfolge vor. Alle darin beschriebenen Phasen sind inzwischen umgesetzt und produktiv im Einsatz; das Dokument wurde entsprechend nachgezogen und dient jetzt auch als Rückblick, was tatsächlich gebaut wurde (inkl. Abweichungen vom ursprünglichen Plan). Es ersetzt weiterhin nicht die `DOKUMENTATION.md` (Betrieb/Deployment) oder `plantdiary-ki-architektur.md` (ursprüngliches KI-Konzept), sondern konkretisiert und aktualisiert Teile davon.

## Ausgangslage (Stand vor Baubeginn)

- Bestehende App: Flask-Backend + Single-File-Frontend (`index.html`), SQLite, bereits produktiv im Einsatz.
- Arten-ID lief bereits über PlantNet (Cloud-API), Pflegewerte kamen von Open Plantbook.
- Push-Gieß-Erinnerungen liefen über einen täglichen systemd-Timer (`notify.py`), der `plants.last_watered` auslas.
- Repo wurde neu unter Versionskontrolle gebracht; ein zuvor versehentlich committeter API-Key wurde aus der Git-History entfernt (Force-Push).
- **Sicherheits-Update:** Alle betroffenen Keys (PlantNet-API-Key und interner `API_KEY`) wurden zwischenzeitlich erneuert (bestätigt).

## Bewusst verworfene/geänderte Ideen aus der ursprünglichen KI-Architektur-Doku

| Ursprünglich geplant | Jetzige Entscheidung | Warum |
|---|---|---|
| Eigenes TF.js-Modell für Arten-ID (iNaturalist-Daten) | **Verworfen** – PlantNet-API bleibt | PlantNet ist bereits integriert, deutlich genauer und breiter abgedeckt als ein selbst trainiertes MobileNet-Modell realistisch sein könnte |
| Eigenes TF.js-Modell für Krankheits-ID (PlantVillage + PlantDoc) | **Verworfen** – Vision-fähiger Cloud-Chat übernimmt das | PlantVillage/PlantDoc sind Nutzpflanzen-/Feldfrucht-Datensätze (Tomate, Mais, Apfel …), decken typische Zimmerpflanzen-Probleme (Spinnmilben, Wurzelfäule, Trauermücken) kaum ab. Kein Trainings-/Konvertierungsaufwand nötig, breiteres Allgemeinwissen |

---

## Gesamtbild: Was gebaut wurde

### 1. Frontend-Redesign ✅ umgesetzt

- **Übersicht:** Galerie-artige Ansicht aller Pflanzen (statt der früheren Stat-Karten), fotolastig – nutzt `plant_images`.
- **Detailansicht pro Pflanze:** Aufruf per Klick auf eine Kachel. **Drei** Tabs (ursprünglich waren zwei geplant, „Notizen" kam später als eigenständige Anforderung dazu, siehe Abschnitt 6):
  - **„Details"** – Name, wiss. Name, Gieß-Rhythmus, Pflegewerte, Fotos, plus Gieß- und Düngungs-Verlauf (jeweils nur letztes Datum sichtbar, Button öffnet volle Historie als Modal)
  - **„Chat"** – pflanzenbezogener KI-Chat (siehe Abschnitt 4)
  - **„Notizen"** – freie Text-/Skizzen-Notizen, mehrseitig (siehe Abschnitt 6)

### 2. Datenmodell-Änderungen ✅ umgesetzt

`plants.last_watered` wurde durch eigene Historientabellen ersetzt:

```sql
CREATE TABLE plant_waterings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id   TEXT NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    watered_at TEXT NOT NULL,
    note       TEXT
);

CREATE TABLE plant_fertilizations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id       TEXT NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    fertilized_at  TEXT NOT NULL,
    note           TEXT
);
```

- Einträge sind löschbar/korrigierbar (analog zu `plant_images`).
- `plants.last_watered` wurde entfernt; das „letzte Datum" wird live per `MAX(watered_at)` ermittelt.
- Migration der bestehenden `last_watered`-Werte lief beim ersten Start automatisch (`migrate_last_watered()`).
- `notify.py` wurde angepasst und liest jetzt die neue Tabelle.
- Der schnelle „Gießen"-Button ist zusätzlich weiterhin direkt auf der Galerie-Kachel verfügbar.
- Die Notizen-Tabelle(n) kamen als separate, spätere Erweiterung dazu – siehe Abschnitt 6.

### 3. Authentifizierung vereinfacht ✅ umgesetzt

- Open-Plantbook-Credentials liegen serverseitig in `/etc/plantdiary.env` (analog zum `PLANTNET_API_KEY`-Muster).
- Der Token-Fetch läuft über einen Backend-Proxy-Endpunkt (`GET /api/plants/opb-token`) statt direkt aus dem Browser.
- Der frühere eigene Login-Screen entfällt; übrig bleibt nur noch die Nginx-Basic-Auth-Abfrage. Secret liegt nicht mehr im Browser-`localStorage`.

### 4. KI-Chat mit Tool-Use (pro Pflanze) ✅ umgesetzt — mit Abweichung beim Modell-Anbieter

- Endpunkt: `POST /api/plants/<id>/chat`.
- Die `plant_id` kommt aus der URL, nicht vom LLM – Tools sind fest an die eine Pflanze gebunden.
- Zwei Tool-Kategorien, wie geplant:
  - **Aktions-Tools** (schreibend): `set_watering_days`, `log_watering`, `log_fertilization`
  - **Lese-Tools** (auf Abruf): `get_plant_photos`
- Krankheits-/Schädlings-Diagnose läuft über denselben Chat per Bild-Upload (Vision-Fähigkeit des LLM).

**Abweichung vom ursprünglichen Plan:** Geplant war Claude (Sonnet 5 bzw. Haiku 4.5) als Anbieter. In der Praxis erforderte die Anthropic-API ein Prepaid-Guthaben, das nicht eingezahlt werden sollte — der Chat läuft daher stattdessen über **Google Gemini** (kostenlose Nutzungsstufe). Das brachte eigene, erst im Live-Betrieb sichtbare Probleme mit sich:
- `gemini-2.5-flash`/`-flash-lite` sind für neue API-Keys nicht mehr verfügbar, `gemini-2.0-flash` ist abgekündigt.
- `gemini-3.8-flash` (Googles aktuelle Empfehlung) hatte in der Praxis ein sehr knappes Freikontingent (~20 Anfragen/Tag) und lieferte auch danach wiederholt `503 UNAVAILABLE` wegen Überlastung.
- Finale Wahl: **`gemini-3.5-flash-lite`** (großzügigeres Freikontingent, ~1500 Anfragen/Tag), zusätzlich mit Retry-Logik (bis zu 3 Versuche, 2s/4s-Backoff) speziell für 5xx-Serverfehler, nicht für Rate-Limit-Fehler (429).
- Das Wire-Format zwischen Frontend und Backend blieb beim Umbau unverändert (Anthropic-Content-Block-Form), sodass die Migration rein Backend-seitig war.

### 5. PWA / Offline ✅ umgesetzt — mit zwei Nachbesserungen

- `manifest.json` (Icon, Start-URL, Standalone-Display) + `sw.js` mit App-Shell-Caching (cache-first für `/`, Manifest, Icons; network-only für API/Bilder/Pflanzensuche, damit Pflanzendaten nie veraltet aus dem Cache kommen).
- **Nachbesserung 1 – Cache-Versionierung:** Der Service Worker erkennt nur dann eine neue App-Shell-Version, wenn sich `sw.js` selbst ändert. Bei einem reinen `index.html`-Update ohne `sw.js`-Änderung blieb die alte Seite im Cache hängen und rief inzwischen entfernte Backend-Endpunkte auf (404s). Lösung: `CACHE_NAME` wird bei jedem App-Shell-relevanten Release mit hochgezählt.
- **Nachbesserung 2 – Maskable Icons:** `icon-192.png`/`icon-512.png` hatten ursprünglich transparente, bereits abgerundete Ecken statt eines randlos füllenden Hintergrunds – das widerspricht der in `manifest.json` deklarierten `purpose: "any maskable"` und kann dazu führen, dass das Home-Bildschirm-Icon kaputt/fehlend aussieht, wenn das Betriebssystem seine eigene Maske darüberlegt. Ecken wurden mit der Theme-Farbe (`#3d6b25`) aufgefüllt.
- **Noch unbestätigt:** Ob das Icon auf dem iPad nach diesen Fixes tatsächlich korrekt auf dem Home-Bildschirm erscheint, wurde zuletzt noch nicht zurückgemeldet/getestet.

---

## 6. Notizen-Feature (nicht im ursprünglichen Plan — später ergänzte Anforderung)

Kam erst nach Abschluss der ursprünglich geplanten Phasen als eigener Wunsch dazu: ein dritter Tab für freie, pflanzenbezogene Notizen, mit Apple-Pencil-Unterstützung.

**V1 – ein Notizblatt pro Pflanze:**
- Zwei Eingabebereiche: ein `<textarea>` (iPadOS Scribble wandelt Pencil-Handschrift darin automatisch in Text um – keine App-Logik nötig) und ein `<canvas>` für freie Skizzen, per Pointer Events API (inkl. `pressure` für Apple-Pencil-Strichstärke).
- Tabelle `plant_notes` (eine Zeile pro Pflanze), Endpunkte `GET/PATCH /api/plants/<id>/note`, `POST/DELETE /api/plants/<id>/note/sketch`.

**V2 – mehrseitige Notizblätter** (Umstieg, nachdem sich zeigte, dass ein Blatt nicht reicht):
- `plant_notes` ersetzt durch `plant_note_pages` (eine Zeile pro Seite statt pro Pflanze), mit einmaliger Migration der bisherigen Notiz als jeweils erste Seite.
- Neue Endpunkte: `GET/POST /api/plants/<id>/notes`, `PATCH/DELETE /api/plants/<id>/notes/<page_id>`, `POST/DELETE /api/plants/<id>/notes/<page_id>/sketch`.
- Seiten-Navigation im Tab (‹ Seite X/Y ›, „+ Neues Blatt", „🗑 Blatt löschen"), nach demselben Carousel-Muster wie die Foto-Galerie. Wird die letzte Seite gelöscht, legt die App automatisch eine neue leere Seite an.
- Das Textfeld wächst inzwischen dynamisch mit dem Inhalt mit (Start-Höhe 160px, kein manueller Resize-Griff mehr nötig).

---

## Umsetzungsreihenfolge – tatsächlicher Verlauf

**Phase 1 – Datenbank-Fundament** ✅ erledigt
Neue Tabellen, Migration, CRUD-Endpunkte für Gieß-/Düngungs-Historie, `notify.py` umgestellt.

**Phase 2 – Auth-Vereinfachung** ✅ erledigt

**Phase 3 – Frontend-Redesign** ✅ erledigt
Galerie-Ansicht, Detailansicht mit Tab-Navigation, Details-Tab inkl. Verlaufs-Anzeige.

**Phase 4 – KI-Chat** ✅ erledigt, Anbieter abweichend von der Planung (Gemini statt Claude, siehe Abschnitt 4)

**Phase 5 – PWA/Offline** ✅ erledigt, inkl. zweier Nachbesserungen (siehe Abschnitt 5)

**Phase 6 – Notizen** ✅ erledigt, inkl. Umstieg von Einzelblatt auf Mehrseiten-Notizblätter (nicht im ursprünglichen Plan, siehe Abschnitt 6)

Zusätzlich im laufenden Betrieb gefixt:
- Deployment-Lücke: `plantdiary.service` wurde ursprünglich nie auf die aktive Systemd-Unit synchronisiert (nur die Nginx-Config war im Runbook enthalten) — Schritt ergänzt.
- „Per Foto identifizierte Pflanze ließ sich nicht hinzufügen": Wenn OpenPlantbook die von PlantNet erkannte Art nicht kennt, gab es keinen Weg mehr, sie trotzdem anzulegen. Fix: direkter „+ Diese Pflanze hinzufügen"-Button direkt nach der Fotoerkennung, unabhängig vom OpenPlantbook-Suchergebnis.

---

## Sicherheit – aktueller Stand

- **PlantNet-API-Key:** ✅ erneuert (bestätigt).
- **Interner `API_KEY`:** ✅ erneuert (bestätigt).

## Offene Punkte

- Bestätigen, ob das Home-Bildschirm-Icon auf dem iPad nach den PWA-Nachbesserungen korrekt angezeigt wird (siehe Abschnitt 5).
