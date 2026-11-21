import threading
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request, Response
from werkzeug.serving import make_server

import database
from config import PORT, DASHBOARD_USER, DASHBOARD_PASSWORD, BOT_NAME, FILEBEE_UPLOAD_URL

app = Flask(__name__)
STATE = {
    "started_at": time.time(),
    "connected": False,
    "last_update": None,
    "bot_username": None,
    "storage_mode": "api" if FILEBEE_UPLOAD_URL else "manual-link",
    "storage_error": None,
}


def set_connected(value: bool, username: str | None = None) -> None:
    STATE["connected"] = bool(value)
    if username:
        STATE["bot_username"] = username


def touch_update() -> None:
    STATE["last_update"] = time.time()


def _auth_ok() -> bool:
    if not DASHBOARD_PASSWORD:
        return True
    auth = request.authorization
    return bool(auth and auth.username == DASHBOARD_USER and auth.password == DASHBOARD_PASSWORD)


def _unauthorized() -> Response:
    return Response("Authentication required", 401,
                    {"WWW-Authenticate": 'Basic realm="FileBee Telegram Dashboard"'})


@app.get("/")
def home():
    if not _auth_ok():
        return _unauthorized()
    return render_template("index.html", bot_name=BOT_NAME)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "telegram_connected": STATE["connected"],
                    "storage_mode": STATE["storage_mode"]}), 200


@app.get("/api/status")
def api_status():
    if not _auth_ok():
        return _unauthorized()
    now = time.time()
    uptime = max(0, int(now - STATE["started_at"]))
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    return jsonify({
        "connected": STATE["connected"],
        "storage_mode": STATE["storage_mode"],
        "storage_error": STATE["storage_error"],
        "bot_username": STATE["bot_username"],
        "uptime_seconds": uptime,
        "uptime_text": f"{days}d {hours}h {mins}m {secs}s",
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "last_update_utc": datetime.fromtimestamp(STATE["last_update"], timezone.utc).isoformat()
            if STATE["last_update"] else None,
        **database.stats(),
    })


_SERVER = None


def _serve() -> None:
    _SERVER.serve_forever()


def start_dashboard_thread() -> threading.Thread:
    global _SERVER
    _SERVER = make_server("0.0.0.0", PORT, app, threaded=True)
    thread = threading.Thread(target=_serve, name="dashboard", daemon=True)
    thread.start()
    return thread
