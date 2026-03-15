"""
status_server.py — Jalankan di RPi A
Simple HTTP server untuk sharing status IN/OUT antar RPi.

Run: python3 status_server.py
Port: 5050

API:
  GET  /status/{uid}         → ambil status user
  POST /status/{uid}         → set status user (body: {"status":"IN","name":"xxx"})
  GET  /status               → semua status
"""

from flask import Flask, request, jsonify
import json, os, threading

app = Flask(__name__)

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")
_lock = threading.Lock()


def load():
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
    except: pass
    return {}

def save(data):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@app.get("/status")
def get_all():
    with _lock:
        return jsonify(load())

@app.get("/status/<uid>")
def get_status(uid):
    with _lock:
        data = load()
        return jsonify(data.get(uid, {"status": "OUT", "name": ""}))

@app.post("/status/<uid>")
def set_status(uid):
    body = request.get_json(silent=True) or {}
    with _lock:
        data = load()
        data[uid] = {
            "status":     body.get("status", "OUT"),
            "name":       body.get("name", ""),
            "last_event": body.get("last_event", "")
        }
        save(data)
    print(f"[STATUS] {uid} → {data[uid]['status']}")
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 40)
    print("Status Server — RPi A")
    print("Port: 5050")
    print("=" * 40)
    app.run(host="0.0.0.0", port=5050, debug=False)
