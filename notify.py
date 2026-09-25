"""
Standalone push-notification script — run via systemd timer (daily 08:00).
Sends a browser push to all subscribed devices when ≥1 plant is urgently overdue.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone
from pywebpush import webpush, WebPushException

DB_PATH          = os.path.join(os.path.dirname(__file__), "plants.db")
VAPID_PRIVATE_PEM = os.path.join(os.path.dirname(__file__), "vapid_private.pem")
VAPID_CLAIMS      = {"sub": "mailto:alkjewenigsson@gmail.com"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def urgent_count():
    now = datetime.now(timezone.utc)
    count = 0
    with get_db() as conn:
        for row in conn.execute("SELECT last_watered, watering_days FROM plants"):
            days = row["watering_days"] or 7
            lw   = row["last_watered"]
            if not lw:
                count += 1
                continue
            last = datetime.fromisoformat(lw.replace("Z", "+00:00"))
            if (now - last).days >= days:
                count += 1
    return count


def subscriptions():
    with get_db() as conn:
        rows = conn.execute("SELECT subscription FROM push_subscriptions").fetchall()
    return [json.loads(r["subscription"]) for r in rows]


def send(sub, n):
    payload = json.dumps({
        "title": "Plantdiary 🌿",
        "body":  f"{n} Pflanze(n) müssen dringend gegossen werden!",
        "urgentCount": n,
    })
    try:
        webpush(
            subscription_info=sub,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_PEM,
            vapid_claims=VAPID_CLAIMS,
        )
        print(f"Push sent → {sub['endpoint'][:60]}...")
    except WebPushException as exc:
        print(f"Push failed: {exc}")


if __name__ == "__main__":
    if not os.path.exists(VAPID_PRIVATE_PEM):
        print("vapid_private.pem not found — run key generation first")
        raise SystemExit(1)

    n = urgent_count()
    if n == 0:
        print("No urgent plants — no notification sent")
        raise SystemExit(0)

    subs = subscriptions()
    if not subs:
        print("No push subscriptions registered — nothing to do")
        raise SystemExit(0)

    print(f"Sending push to {len(subs)} subscriber(s) — {n} urgent plant(s)")
    for sub in subs:
        send(sub, n)
