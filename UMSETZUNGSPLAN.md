# Plantdiary – Umsetzungsplan (Redesign & KI-Erweiterung)

*Stand: 28. September 2026*

Dieses Dokument fasst die Ideen aus der gemeinsamen Planungsrunde zusammen und schlägt eine Umsetzungsreihenfolge vor. Es ersetzt nicht die bestehende `DOKUMENTATION.md` (Betrieb/Deployment) oder `plantdiary-ki-architektur.md` (ursprüngliches KI-Konzept), sondern konkretisiert und aktualisiert Teile davon.

## Ausgangslage

- Bestehende App: Flask-Backend + Single-File-Frontend (`index.html`), SQLite, bereits produktiv im Einsatz.
- Arten-ID läuft bereits über PlantNet (Cloud-API), Pflegewerte kommen von Open Plantbook.
- Push-Gieß-Erinnerungen laufen über einen täglichen systemd-Timer (`notify.py`), der `plants.last_watered` ausliest.
- Repo wurde neu unter Versionskontrolle gebracht; ein zuvor versehentlich committeter API-Key wurde aus der Git-History entfernt (Force-Push). **Offen:** PlantNet-Key und interner API-Key sollten trotzdem noch rotiert werden (siehe Abschnitt „Sicherheit" unten) – das ist unabhängig vom Rest dieses Plans und kann jederzeit erledigt werden.

## Bewusst verworfene/geänderte Ideen aus der ursprünglichen KI-Architektur-Doku

| Ursprünglich geplant | Jetzige Entscheidung | Warum |
|---|---|---|
| Eigenes TF.js-Modell für Arten-ID (iNaturalist-Daten) | **Verworfen** – PlantNet-API bleibt | PlantNet ist bereits integriert, deutlich genauer und breiter abgedeckt als ein selbst trainiertes MobileNet-Modell realistisch sein könnte |
| Eigenes TF.js-Modell für Krankheits-ID (PlantVillage + PlantDoc) | **Verworfen** – Vision-fähiger Cloud-Chat übernimmt das | PlantVillage/PlantDoc sind Nutzpflanzen-/Feldfrucht-Datensätze (Tomate, Mais, Apfel …), decken typische Zimmerpflanzen-Probleme (Spinnmilben, Wurzelfäule, Trauermücken) kaum ab. Kein Trainings-/Konvertierungsaufwand nötig, breiteres Allgemeinwissen |

---

## Gesamtbild: Was gebaut wird

### 1. Frontend-Redesign

- **Übersicht:** Galerie-artige Ansicht aller Pflanzen (statt der heutigen Stat-Karten), fotolastig – nutzt die bereits vorhandene `plant_images`-Funktionalität.
- **Detailansicht pro Pflanze:** Aufruf per Klick auf eine Kachel. Zwei Tabs:
  - **„Plant Details"** – alles, was heute im Edit-Modal + in der Lightbox steckt (Name, wiss. Name, Gieß-Rhythmus, Pflegewerte, Fotos), plus:
    - Gieß-Verlauf: nur letztes Datum sichtbar, Button öffnet volle Historie
    - Düngungs-Verlauf: gleiches Prinzip
  - **„Chat"** – pflanzenbezogener KI-Chat (siehe Abschnitt 4)
- Technische Implikation: Es gibt aktuell keine Navigationsebene (kein Router, kein View-State) – das muss neu eingeführt werden, ist aber ohne Framework machbar.

### 2. Datenmodell-Änderungen

Neue Tabellen (ersetzen `plants.last_watered`):

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

- Einträge sind **löschbar/korrigierbar** (analog zu `plant_images`).
- `plants.last_watered` wird entfernt; das "letzte Datum" wird live per `MAX(watered_at)` ermittelt statt redundant gespeichert.
- **Migration:** Bestehende `last_watered`-Werte müssen beim Umstieg als erster Eintrag in `plant_waterings` übernommen werden, sonst ist die Historie beim ersten Start leer.
- **`notify.py` muss angepasst werden** – liest aktuell direkt `plants.last_watered`; ohne Anpassung laufen die Push-Gieß-Erinnerungen sonst ins Leere.
- Schneller "Gießen"-Button bleibt zusätzlich auf der Kachel in der Galerie-Übersicht erhalten (nicht nur in der Detailansicht).

### 3. Authentifizierung vereinfachen

- Aktuell: zwei Auth-Schritte – Nginx Basic-Auth **und** ein App-interner "Login"-Screen, der eigentlich nur ein Open-Plantbook-OAuth-Token holt (Client-ID/Secret manuell eingegeben, in `localStorage` gecacht).
- **Neu:** Open-Plantbook-Credentials wandern serverseitig nach `/etc/plantdiary.env` (analog zum bestehenden `PLANTNET_API_KEY`-Muster). Der Token-Fetch läuft über einen neuen Backend-Proxy-Endpunkt statt direkt aus dem Browser.
- Ergebnis: Der Setup-Screen entfällt komplett, übrig bleibt nur noch die eine Basic-Auth-Abfrage. Nebeneffekt: Secret liegt nicht mehr im Browser-`localStorage`.

### 4. KI-Chat mit Tool-Use (pro Pflanze)

- Neuer Endpunkt, z. B. `POST /api/plants/<id>/chat`.
- **Wichtig für die Sicherheit:** Die `plant_id` kommt aus der URL, nicht vom LLM – Tools sind fest an die eine Pflanze gebunden, damit der Chat einer Pflanze nicht versehentlich eine andere verändern kann.
- Zwei Tool-Kategorien:
  - **Aktions-Tools** (schreibend): Gieß-Rhythmus ändern, Gießen/Düngen loggen (schreiben in die neuen Historie-Tabellen aus Abschnitt 2)
  - **Lese-Tools** (auf Abruf, nicht automatisch bei jeder Nachricht): `get_plant_photos` – die KI holt sich gezielt Fotos aus der Galerie, wenn die Frage das erfordert (z. B. Verlaufsvergleich, Diagnose). Vermeidet, dass bei jeder einfachen Textfrage unnötig alle Bilder mitgeschickt werden.
- **Krankheits-/Schädlings-Diagnose** läuft über denselben Chat: Foto hochladen, KI analysiert es direkt (Vision-Fähigkeit des LLM) – kein separates Feature, keine eigene Trainingspipeline.
- **Modellwahl:** Claude Sonnet 5 als solider Standard für zuverlässiges Tool-Use bei überschaubaren Kosten; Claude Haiku 4.5 als noch günstigere Alternative, falls die Antwortqualität dafür ausreicht. Bei diesem Nutzungsvolumen (eine Person, gelegentliche Anfragen) bewegen sich die Kosten ohnehin im Cent-Bereich pro Monat.

### 5. PWA / Offline (für das iPad-Terminal-Szenario)

- Bisher fehlt komplett: kein `manifest.json`, kein `<link rel="manifest">`.
- Der bestehende `sw.js` kann nur Push-Events, kein Caching von App-Shell/Assets.
- Nötig: `manifest.json` (Icon, Start-URL, Standalone-Display) + erweiterter Service Worker für Offline-Caching, damit "Zum Home-Bildschirm hinzufügen" wie eine echte App funktioniert.

---

## Vorgeschlagene Umsetzungsreihenfolge

Die Reihenfolge berücksichtigt Abhängigkeiten (z. B. braucht die Detailansicht die neuen Historie-Endpunkte) und versucht, früh nutzbare Verbesserungen zu liefern.

**Phase 1 – Datenbank-Fundament**
Neue Tabellen, Migration, CRUD-Endpunkte für Gieß-/Düngungs-Historie, `notify.py` umstellen. Grundlage für Phase 3 und 4.

**Phase 2 – Auth-Vereinfachung**
Kleine, in sich geschlossene Verbesserung, unabhängig vom Rest. Kann parallel oder vorgezogen werden, da sie sofort spürbar ist (nur noch ein Login-Schritt).

**Phase 3 – Frontend-Redesign**
Galerie-Ansicht, Detailansicht mit Tab-Navigation, Details-Tab inkl. Verlaufs-Anzeige (nutzt Phase 1).

**Phase 4 – KI-Chat**
Backend-Endpunkt, Aktions- und Lese-Tools, Vision-Diagnose, Chat-Tab im Frontend (nutzt Phase 1 für die Aktions-Tools, baut auf der Tab-Struktur aus Phase 3 auf).

**Phase 5 – PWA/Offline**
Kann grundsätzlich jederzeit unabhängig ergänzt werden, macht aber am meisten Sinn, wenn die neue Oberfläche (Phase 3) schon steht.

---

## Sicherheit – weiterhin offen

- PlantNet-API-Key rotieren (my.plantnet.org) – war öffentlich sichtbar.
- Internen `API_KEY` erneuern und in `/etc/plantdiary.env` sowie der aktiven Nginx-Config eintragen.
- Beides unabhängig vom restlichen Plan, jederzeit nachholbar.

## Offene Detailfragen für die Umsetzung

- Genaue Tool-Definitionen für den Chat (Namen, Parameter) – wird beim Bau von Phase 4 festgelegt.
- Feingranulare UI-Details der Historie-Ansicht (Modal vs. aufklappbarer Bereich) – kann beim Bau von Phase 3 entschieden werden.
- Manifest-Icons/Branding fürs Home-Bildschirm-Icon – braucht ggf. ein eigenes App-Icon-Design.
