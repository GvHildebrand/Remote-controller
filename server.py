"""Flask server exposing a mobile-friendly TV remote.

Run with:  python server.py
Then open http://<this-machine-ip>:5000 on your phone (same Wi-Fi).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from discovery import DiscoveredTV, discover_tvs, manual_tv
from tv_controller import power_on, reachable, send_key

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "tvs.json"

app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="")


def _load_saved() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(store: dict[str, dict]) -> None:
    STATE_FILE.write_text(json.dumps(store, indent=2))


def _merge_into_store(tvs: list[DiscoveredTV]) -> dict[str, dict]:
    store = _load_saved()
    for tv in tvs:
        existing = store.get(tv.ip, {})
        merged = {**existing, **{k: v for k, v in tv.to_dict().items() if v}}
        store[tv.ip] = merged
    _save(store)
    return store


@app.route("/")
def index() -> object:
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/tvs", methods=["GET"])
def list_tvs() -> object:
    return jsonify(list(_load_saved().values()))


@app.route("/api/discover", methods=["POST"])
def discover() -> object:
    found = discover_tvs()
    store = _merge_into_store(found)
    return jsonify({"found": [tv.to_dict() for tv in found], "all": list(store.values())})


@app.route("/api/tvs", methods=["POST"])
def add_tv() -> object:
    data = request.get_json(force=True) or {}
    ip = (data.get("ip") or "").strip()
    if not ip:
        return jsonify({"error": "ip is required"}), 400
    tv = manual_tv(ip=ip, brand=data.get("brand", "generic"), mac=data.get("mac", ""))
    store = _load_saved()
    store[tv.ip] = {**store.get(tv.ip, {}), **tv.to_dict(), "name": data.get("name") or tv.name}
    _save(store)
    return jsonify(store[tv.ip])


@app.route("/api/tvs/<ip>", methods=["DELETE"])
def remove_tv(ip: str) -> object:
    store = _load_saved()
    if ip in store:
        del store[ip]
        _save(store)
    return jsonify({"ok": True})


@app.route("/api/tvs/<ip>/power-on", methods=["POST"])
def power(ip: str) -> object:
    store = _load_saved()
    tv = store.get(ip)
    if not tv:
        return jsonify({"error": "Unknown TV — discover or add it first"}), 404
    result = power_on(ip=ip, mac=tv.get("mac", ""), brand=tv.get("brand", "generic"))
    return jsonify({"ok": result.ok, "method": result.method, "detail": result.detail})


@app.route("/api/tvs/<ip>/key", methods=["POST"])
def key(ip: str) -> object:
    store = _load_saved()
    tv = store.get(ip)
    if not tv:
        return jsonify({"error": "Unknown TV"}), 404
    body = request.get_json(force=True) or {}
    key_name = body.get("key", "")
    if not key_name:
        return jsonify({"error": "key is required"}), 400
    result = send_key(
        brand=tv.get("brand", "generic"),
        ip=ip,
        key=key_name,
        token=tv.get("token", ""),
        client_key=tv.get("client_key", ""),
    )
    return jsonify({"ok": result.ok, "method": result.method, "detail": result.detail})


@app.route("/api/tvs/<ip>/ping", methods=["GET"])
def ping(ip: str) -> object:
    return jsonify({"online": reachable(ip)})


@app.route("/api/shutdown", methods=["POST"])
def shutdown() -> object:
    """Stop the server from the web UI so iOS users don't need Ctrl+C."""
    def _exit_soon() -> None:
        time.sleep(0.2)
        os._exit(0)
    threading.Thread(target=_exit_soon, daemon=True).start()
    return jsonify({"ok": True, "detail": "Server shutting down."})


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
