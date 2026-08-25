#!/usr/bin/env python3
"""
Navigation Alerts V2
- Vérifie automatiquement les prévisions Météo-France via Open-Meteo.
- Applique les règles configurées dans config.json.
- Envoie une notification ntfy à J-3 et J-1 quand un créneau favorable apparaît.
- Envoie aussi une alerte d'annulation si un créneau précédemment détecté disparaît.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"

API_BASE = "https://api.open-meteo.com/v1/meteofrance"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def direction_ok(degrees: float, ranges: list[dict]) -> bool:
    d = degrees % 360
    return any(float(r["min"]) <= d <= float(r["max"]) for r in ranges)


def compass(degrees: float) -> str:
    names = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return names[int((degrees % 360 + 22.5) // 45) % 8]


def fetch_forecast(spot: dict, config: dict) -> dict:
    params = {
        "latitude": spot["latitude"],
        "longitude": spot["longitude"],
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn",
        "timezone": config["timezone"],
        "forecast_days": 4,
        "cell_selection": "sea",
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "navigation-alerts-v2/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_best_window(payload: dict, target_date: str, config: dict):
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    speeds = hourly.get("wind_speed_10m") or []
    directions = hourly.get("wind_direction_10m") or []
    gusts = hourly.get("wind_gusts_10m") or []

    min_kn = float(config["wind"]["min_knots"])
    max_kn = float(config["wind"]["max_knots"])
    ranges = config["wind"]["accepted_direction_ranges_degrees"]
    nav_start = int(config["navigation_hours"]["start"])
    nav_end = int(config["navigation_hours"]["end"])

    matches = []
    for i, stamp in enumerate(times):
        if not stamp.startswith(target_date):
            continue
        try:
            hour = int(stamp[11:13])
            speed = float(speeds[i])
            direction = float(directions[i])
            gust = float(gusts[i]) if i < len(gusts) and gusts[i] is not None else speed
        except (ValueError, TypeError, IndexError):
            continue

        if not (nav_start <= hour <= nav_end):
            continue
        if min_kn <= speed <= max_kn and direction_ok(direction, ranges):
            matches.append({
                "hour": hour,
                "speed": speed,
                "direction": direction,
                "gust": gust,
            })

    if not matches:
        return None

    # Regroupe les heures consécutives, puis retient le créneau le plus long.
    groups = []
    current = [matches[0]]
    for item in matches[1:]:
        if item["hour"] == current[-1]["hour"] + 1:
            current.append(item)
        else:
            groups.append(current)
            current = [item]
    groups.append(current)

    best = max(groups, key=lambda g: (len(g), sum(x["speed"] for x in g) / len(g)))
    avg_dir = sum(x["direction"] for x in best) / len(best)
    return {
        "start_hour": best[0]["hour"],
        "end_hour": min(best[-1]["hour"] + 1, 24),
        "min_speed": round(min(x["speed"] for x in best)),
        "max_speed": round(max(x["speed"] for x in best)),
        "max_gust": round(max(x["gust"] for x in best)),
        "direction": compass(avg_dir),
        "hours": len(best),
    }


def send_ntfy(title: str, message: str, priority: int = 4):
    topic = os.getenv("NTFY_TOPIC", "").strip()
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    token = os.getenv("NTFY_TOKEN", "").strip()

    if not topic:
        print("[MODE TEST] NTFY_TOPIC absent. Notification non envoyée:")
        print(title)
        print(message)
        return False

    payload = json.dumps({
        "topic": topic,
        "title": title,
        "message": message,
        "priority": priority,
        "tags": ["ocean", "wind_face"],
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        server,
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()
    return True


def check_once():
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})
    tz = ZoneInfo(config.get("timezone", "Europe/Paris"))
    today = datetime.now(tz).date()

    for spot in config["spots"]:
        try:
            forecast = fetch_forecast(spot, config)
        except Exception as exc:
            print(f"[ERREUR MÉTÉO] {spot['name']}: {exc}")
            continue

        for lead in config["alert_lead_days"]:
            target = today + timedelta(days=int(lead))
            target_str = target.isoformat()
            key = f"{spot['name']}|J-{lead}|{target_str}"
            window = extract_best_window(forecast, target_str, config)
            previous = state.get(key, {}).get("favorable")

            if window and previous is not True:
                title = f"🌊 Navigation favorable J-{lead}"
                message = (
                    f"{spot['name']}\n"
                    f"{target.strftime('%d/%m/%Y')} · {window['start_hour']:02d}h–{window['end_hour']:02d}h\n"
                    f"Vent {window['direction']} · {window['min_speed']}–{window['max_speed']} nd\n"
                    f"Rafales max prévues: {window['max_gust']} nd\n"
                    f"✅ Critères: 12–40 nd, E→SE ou SO→NO"
                )
                try:
                    send_ntfy(title, message, priority=4 if int(lead) == 1 else 3)
                    state[key] = {"favorable": True, "last_change": datetime.now(tz).isoformat()}
                    print(f"[ALERTE] {spot['name']} {target_str} J-{lead}")
                except Exception as exc:
                    print(f"[ERREUR NOTIFICATION] {exc}")

            elif not window and previous is True:
                title = f"⚠️ Créneau dégradé J-{lead}"
                message = (
                    f"{spot['name']} · {target.strftime('%d/%m/%Y')}\n"
                    "Le créneau précédemment favorable ne respecte plus tes critères "
                    "(12–40 nd, E→SE ou SO→NO)."
                )
                try:
                    send_ntfy(title, message, priority=4)
                    state[key] = {"favorable": False, "last_change": datetime.now(tz).isoformat()}
                    print(f"[ANNULATION] {spot['name']} {target_str} J-{lead}")
                except Exception as exc:
                    print(f"[ERREUR NOTIFICATION] {exc}")

            elif previous is None:
                state[key] = {"favorable": bool(window), "last_change": datetime.now(tz).isoformat()}

    # Nettoyage de l'historique ancien
    cutoff = today - timedelta(days=7)
    cleaned = {}
    for key, value in state.items():
        try:
            date_str = key.rsplit("|", 1)[-1]
            if datetime.fromisoformat(date_str).date() >= cutoff:
                cleaned[key] = value
        except Exception:
            cleaned[key] = value
    save_json(STATE_PATH, cleaned)


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/check":
            threading.Thread(target=check_once, daemon=True).start()
            body = b"Verification lancee.\n"
        else:
            body = (
                b"Navigation Alerts V2 actif.\n"
                b"GET /check pour lancer une verification manuelle.\n"
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[HTTP]", fmt % args)


def scheduler_loop():
    config = load_json(CONFIG_PATH, {})
    tz = ZoneInfo(config.get("timezone", "Europe/Paris"))
    hours = set(int(x) for x in config.get("check_hours_local", [7, 17]))
    last_slot = None

    # Un contrôle au démarrage, puis aux heures prévues.
    try:
        check_once()
    except Exception as exc:
        print("[ERREUR CONTRÔLE INITIAL]", exc)

    while True:
        now = datetime.now(tz)
        slot = now.strftime("%Y-%m-%d-%H")
        if now.hour in hours and now.minute < 5 and slot != last_slot:
            last_slot = slot
            try:
                check_once()
            except Exception as exc:
                print("[ERREUR PLANIFICATEUR]", exc)
        time.sleep(60)


def main():
    threading.Thread(target=scheduler_loop, daemon=True).start()
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), StatusHandler)
    print(f"Navigation Alerts V2 actif sur le port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
