from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import json
import uuid
import requests as http
import urllib.parse
from datetime import datetime, timezone
from PIL import Image, ImageOps

app = Flask(__name__)
CORS(app, origins=["https://plantdiary.olga-allerdings.de"])

API_KEY          = os.environ.get("API_KEY", "")
PLANTNET_API_KEY = os.environ.get("PLANTNET_API_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_PEM = os.path.join(os.path.dirname(__file__), "vapid_private.pem")

app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB

DB_PATH = os.path.join(os.path.dirname(__file__), "plants.db")
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plants (
                id TEXT PRIMARY KEY,
                pid TEXT NOT NULL,
                name TEXT NOT NULL,
                scientific_name TEXT,
                last_watered TEXT,
                watering_days INTEGER DEFAULT 7,
                details TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plant_images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id    TEXT NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
                filename    TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint     TEXT NOT NULL UNIQUE,
                subscription TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
        """)
        conn.commit()


init_db()


@app.before_request
def check_api_key():
    if request.path == "/api/health":
        return
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401


# ── GET all plants ─────────────────────────────────────────────────────────────
@app.route("/api/plants", methods=["GET"])
def get_plants():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM plants ORDER BY name").fetchall()
    plants = []
    for row in rows:
        plant = dict(row)
        plant["details"] = json.loads(plant["details"]) if plant["details"] else {}
        plant["wateringDays"] = plant.pop("watering_days")
        plant["lastWatered"] = plant.pop("last_watered")
        plant["scientificName"] = plant.pop("scientific_name")
        plants.append(plant)
    return jsonify(plants)


# ── POST create plant ──────────────────────────────────────────────────────────
@app.route("/api/plants", methods=["POST"])
def create_plant():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    plant_id = data.get("id") or datetime.now().strftime("%Y%m%d%H%M%S%f")
    details = json.dumps(data.get("details", {}))

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO plants
               (id, pid, name, scientific_name, last_watered, watering_days, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                plant_id,
                data.get("pid", ""),
                data.get("name", ""),
                data.get("scientificName", ""),
                data.get("lastWatered"),
                data.get("wateringDays", 7),
                details,
            ),
        )
        conn.commit()

    return jsonify({"id": plant_id}), 201


# ── PATCH water plant ──────────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>/water", methods=["PATCH"])
def water_plant(plant_id):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_db() as conn:
        conn.execute(
            "UPDATE plants SET last_watered = ? WHERE id = ?", (now, plant_id)
        )
        conn.commit()
    return jsonify({"lastWatered": now})


# ── PATCH update plant ────────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>", methods=["PATCH"])
def update_plant(plant_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    with get_db() as conn:
        conn.execute("""
            UPDATE plants SET
                name = ?, scientific_name = ?, last_watered = ?,
                watering_days = ?, details = ?
            WHERE id = ?
        """, (
            data.get("name", ""),
            data.get("scientificName", ""),
            data.get("lastWatered"),
            data.get("wateringDays", 7),
            json.dumps(data.get("details", {})),
            plant_id
        ))
        conn.commit()
    return jsonify({"ok": True})


# ── DELETE plant ───────────────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>", methods=["DELETE"])
def delete_plant(plant_id):
    with get_db() as conn:
        conn.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
        conn.commit()
    return jsonify({"ok": True})


# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ── GET images for a plant ─────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>/images", methods=["GET"])
def get_images(plant_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, filename, uploaded_at FROM plant_images WHERE plant_id = ? ORDER BY uploaded_at",
            (plant_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── POST upload image ──────────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>/images", methods=["POST"])
def upload_image(plant_id):
    if "image" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["image"]
    if not file.content_type or not file.content_type.startswith("image/"):
        return jsonify({"error": "Not an image"}), 400

    try:
        img = Image.open(file.stream)
        # Try to read the original capture date from EXIF before transposing strips it
        taken_at = None
        try:
            exif = img.getexif()
            dt_str = exif.get(36867) or exif.get(306)  # DateTimeOriginal or DateTime
            if dt_str:
                taken_at = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S") \
                               .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except Exception:
            pass
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if img.width > 1200:
            ratio = 1200 / img.width
            img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
        filename = f"{plant_id}_{uuid.uuid4().hex}.jpg"
        img.save(os.path.join(IMAGES_DIR, filename), "JPEG", quality=80, optimize=True)
    except Exception:
        return jsonify({"error": "Invalid image"}), 400

    now = taken_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO plant_images (plant_id, filename, uploaded_at) VALUES (?, ?, ?)",
            (plant_id, filename, now)
        )
        conn.commit()
    return jsonify({"filename": filename, "uploaded_at": now}), 201


# ── DELETE image ───────────────────────────────────────────────────────────────
@app.route("/api/plants/<plant_id>/images/<int:image_id>", methods=["DELETE"])
def delete_image(plant_id, image_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT filename FROM plant_images WHERE id = ? AND plant_id = ?",
            (image_id, plant_id)
        ).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        conn.execute("DELETE FROM plant_images WHERE id = ?", (image_id,))
        conn.commit()
    filepath = os.path.join(IMAGES_DIR, row["filename"])
    if os.path.exists(filepath):
        os.remove(filepath)
    return jsonify({"ok": True})


# ── POST identify plant via PlantNet ──────────────────────────────────────────
@app.route("/api/identify", methods=["POST"])
def identify():
    if "image" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["image"]
    if not file.content_type or not file.content_type.startswith("image/"):
        return jsonify({"error": "Not an image"}), 400
    if not PLANTNET_API_KEY:
        return jsonify({"error": "PlantNet not configured"}), 503

    try:
        resp = http.post(
            "https://my-api.plantnet.org/v2/identify/all",
            params={"api-key": PLANTNET_API_KEY, "lang": "de", "nb-results": 3},
            files={"images": (file.filename or "photo.jpg", file.stream, file.content_type)},
            data={"organs": "auto"},
            timeout=15
        )
    except http.RequestException as e:
        app.logger.error(f"PlantNet request failed: {e}")
        return jsonify({"error": "PlantNet nicht erreichbar"}), 502

    if resp.status_code == 404:
        return jsonify({"results": []}), 200
    if not resp.ok:
        return jsonify({"error": f"PlantNet Fehler ({resp.status_code})"}), 502

    top = resp.json().get("results", [])[:3]

    def wiki_images(scientific_name):
        try:
            title = urllib.parse.quote(scientific_name.replace(" ", "_"))
            w = http.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
                timeout=4,
                headers={"User-Agent": "plantdiary/1.0 (plant care app)"}
            )
            if w.ok:
                data = w.json()
                thumb = data.get("thumbnail", {}).get("source", "")
                full  = data.get("originalimage", {}).get("source", thumb)
                return thumb, full
        except Exception:
            pass
        return "", ""

    results = []
    for r in top:
        species = r.get("species", {})
        common_names = species.get("commonNames", [])
        scientific_name = species.get("scientificNameWithoutAuthor", "")
        thumb, full = wiki_images(scientific_name)
        results.append({
            "scientificName": scientific_name,
            "commonName": common_names[0] if common_names else "",
            "confidence": round(r.get("score", 0) * 100, 1),
            "imageUrl": thumb,
            "imageFullUrl": full,
            "imageAuthor": ""
        })
    return jsonify({"results": results})


# ── Push notification routes ──────────────────────────────────────────────────
@app.route("/api/push/vapid-key")
def push_vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.get_json()
    if not data or "endpoint" not in data:
        return jsonify({"error": "Invalid subscription"}), 400
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, subscription, created_at) VALUES (?, ?, ?)",
            (data["endpoint"], json.dumps(data), now)
        )
        conn.commit()
    return jsonify({"ok": True}), 201


@app.route("/api/push/subscribe", methods=["DELETE"])
def push_unsubscribe():
    data = request.get_json()
    if not data or "endpoint" not in data:
        return jsonify({"error": "No endpoint"}), 400
    with get_db() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (data["endpoint"],)
        )
        conn.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
