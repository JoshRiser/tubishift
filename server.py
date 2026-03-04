"""
server.py — TubiShift local server
Run: python server.py
Then open: http://localhost:5000
"""

import io
import json
import os
import random
import sqlite3
import zipfile
from contextlib import contextmanager
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
from tubi_scraper import search_series, get_series_episodes, ensure_authenticated, SESSION

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
CORS(app)

# DATA_DIR is patched by tray.py to point to AppData when running as .exe
DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "tubishift.db"

# Extension folder — patched by tray.py for .exe; falls back to same dir as server.py for dev
EXTENSION_DIR = Path(__file__).resolve().parent / "tubishift-extension"

# ─── EXTENSION STATE ──────────────────────────────────────────────────────────
# Holds the active queue and position for the Chrome extension to consume.
_ext = {
    "active": False,     # whether auto-advance is enabled
    "queue": [],         # current episode queue
    "index": 0,         # current position
}


# ─── DATABASE ─────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS shows (
                series_id   TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                poster_url  TEXT DEFAULT '',
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id     TEXT NOT NULL REFERENCES shows(series_id) ON DELETE CASCADE,
                content_id    TEXT NOT NULL,
                title         TEXT NOT NULL,
                season        INTEGER,
                episode       INTEGER,
                duration_secs INTEGER,
                credits_secs  INTEGER,
                description   TEXT DEFAULT '',
                thumbnail     TEXT DEFAULT '',
                tubi_url      TEXT NOT NULL,
                UNIQUE(series_id, content_id)
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_series ON episodes(series_id);

            CREATE TABLE IF NOT EXISTS queue_state (
                id          INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
                queue_json  TEXT NOT NULL DEFAULT '[]',
                position    INTEGER NOT NULL DEFAULT 0,
                eps_per_show INTEGER NOT NULL DEFAULT 2,
                built_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            INSERT OR IGNORE INTO queue_state (id, queue_json, position, eps_per_show)
            VALUES (1, '[]', 0, 2);
        """)


# ─── DB HELPERS ───────────────────────────────────────────────────────────────

def db_get_all_shows() -> dict:
    with get_db() as db:
        rows = db.execute("""
            SELECT s.series_id, s.title, s.poster_url, s.added_at,
                   COUNT(e.id) as episode_count
            FROM shows s
            LEFT JOIN episodes e ON e.series_id = s.series_id
            GROUP BY s.series_id
            ORDER BY s.added_at
        """).fetchall()
    return {
        r["series_id"]: {
            "series_id": r["series_id"],
            "title": r["title"],
            "poster_url": r["poster_url"],
            "episode_count": r["episode_count"],
            "added_at": r["added_at"],
        }
        for r in rows
    }


def db_show_exists(series_id: str) -> bool:
    with get_db() as db:
        row = db.execute("SELECT 1 FROM shows WHERE series_id = ?", (series_id,)).fetchone()
    return row is not None


def db_add_show(series_id: str, title: str, poster_url: str, episodes: list):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO shows (series_id, title, poster_url) VALUES (?, ?, ?)",
            (series_id, title, poster_url)
        )
        db.execute("DELETE FROM episodes WHERE series_id = ?", (series_id,))
        db.executemany(
            """INSERT OR IGNORE INTO episodes
               (series_id, content_id, title, season, episode, duration_secs, credits_secs, description, thumbnail, tubi_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    series_id,
                    ep.get("content_id", ""),
                    ep.get("title", ""),
                    ep.get("season"),
                    ep.get("episode"),
                    ep.get("duration_secs"),
                    ep.get("credits_secs"),
                    ep.get("description", ""),
                    ep.get("thumbnail", ""),
                    ep.get("tubi_url", ""),
                )
                for ep in episodes
            ]
        )


def db_remove_show(series_id: str):
    with get_db() as db:
        db.execute("DELETE FROM shows WHERE series_id = ?", (series_id,))


def db_clear():
    with get_db() as db:
        db.execute("DELETE FROM episodes")
        db.execute("DELETE FROM shows")


def db_get_queue(eps_per_show: int = 1) -> list:
    """
    Build a channel queue: eps_per_show random episodes from each show,
    interleaved so shows rotate (e.g. S1E3, S2E7, S3E2, S1E9, S2E1, ...).
    """
    with get_db() as db:
        rows = db.execute("""
            SELECT e.content_id, e.title, e.season, e.episode,
                   e.duration_secs, e.credits_secs, e.description, e.thumbnail, e.tubi_url,
                   s.title as show_title, s.series_id as show_id
            FROM episodes e
            JOIN shows s ON s.series_id = e.series_id
        """).fetchall()

    # Group episodes by show
    by_show = {}
    for r in rows:
        d = dict(r)
        by_show.setdefault(d["show_id"], []).append(d)

    # Shuffle each show's episode pool
    for pool in by_show.values():
        random.shuffle(pool)

    # Build interleaved queue: take eps_per_show from each show in rotation
    # until all episodes are exhausted
    show_pools = list(by_show.values())
    random.shuffle(show_pools)   # randomise which show goes first each launch

    queue = []
    pointers = [0] * len(show_pools)

    while True:
        added_any = False
        for i, pool in enumerate(show_pools):
            start = pointers[i]
            chunk = pool[start:start + eps_per_show]
            if chunk:
                queue.extend(chunk)
                pointers[i] += len(chunk)
                added_any = True
        if not added_any:
            break

    return queue


def db_save_queue(queue: list, position: int, eps_per_show: int):
    """Persist the queue and current position to the DB."""
    with get_db() as db:
        db.execute(
            """UPDATE queue_state SET queue_json=?, position=?, eps_per_show=?, built_at=CURRENT_TIMESTAMP
               WHERE id=1""",
            (json.dumps(queue), position, eps_per_show)
        )


def db_load_queue() -> dict:
    """Load the saved queue state. Returns dict with queue, position, eps_per_show."""
    with get_db() as db:
        row = db.execute("SELECT queue_json, position, eps_per_show FROM queue_state WHERE id=1").fetchone()
    if row:
        return {
            "queue": json.loads(row["queue_json"]),
            "position": row["position"],
            "eps_per_show": row["eps_per_show"],
        }
    return {"queue": [], "position": 0, "eps_per_show": 2}


def db_save_position(position: int):
    """Update just the queue position (called when extension advances)."""
    with get_db() as db:
        db.execute("UPDATE queue_state SET position=? WHERE id=1", (position,))


def db_get_episode_count(series_id: str) -> int:
    with get_db() as db:
        row = db.execute(
            "SELECT COUNT(*) as n FROM episodes WHERE series_id = ?", (series_id,)
        ).fetchone()
    return row["n"] if row else 0


def db_get_episode(episode_id: str) -> bool:
    with get_db() as db:
        row = db.execute("SELECT credits_secs FROM episodes WHERE content_id = ?", (int(episode_id),)).fetchone()
    return row if row else None


# ─── AUTH ─────────────────────────────────────────────────────────────────────

@app.route("/api/auth/status")
def api_auth_status():
    cookie_names = [c.name for c in SESSION.cookies]
    has_at = "at" in cookie_names
    return jsonify({
        "authenticated": has_at,
        "has_at": has_at,
        "cookie_names": list(set(cookie_names)),
    })


@app.route("/api/auth/cookies", methods=["POST"])
def api_set_cookies():
    body = request.get_json()
    raw = body.get("cookies", "").strip()
    if not raw:
        return jsonify({"error": "No cookies provided"}), 400

    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()

    if not cookies:
        return jsonify({"error": "Could not parse cookies"}), 400

    SESSION.cookies.update(cookies)
    import tubi_scraper
    tubi_scraper.save_cookies_to_file()
    return jsonify({"status": "ok", "count": len(cookies), "names": list(cookies.keys())})


# ─── SEARCH ───────────────────────────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing query"}), 400
    results = search_series(query, limit=int(request.args.get("limit", 20)))
    return jsonify(results)


@app.route("/api/series/<series_id>/episodes")
def api_episodes(series_id):
    return jsonify(get_series_episodes(series_id))


# ─── CHANNEL ──────────────────────────────────────────────────────────────────

@app.route("/api/channel", methods=["GET"])
def api_get_channel():
    return jsonify(db_get_all_shows())


@app.route("/api/channel/add", methods=["POST"])
def api_add_show():
    body = request.get_json()
    series_id = str(body.get("id", "")).strip()
    title = body.get("title", series_id)
    poster_url = body.get("poster_url", "")
    if not series_id:
        return jsonify({"error": "Missing id"}), 400

    if db_show_exists(series_id):
        return jsonify({
            "status": "already_added",
            "id": series_id,
            "episode_count": db_get_episode_count(series_id),
        })

    print(f"Fetching episodes for: {title} ({series_id})")
    eps = get_series_episodes(series_id)
    db_add_show(series_id, title, poster_url, eps)
    episode_count = db_get_episode_count(series_id)
    print(f"  -> Saved {episode_count} episodes to DB")

    return jsonify({"status": "added", "id": series_id, "episode_count": episode_count})


@app.route("/api/channel/remove/<series_id>", methods=["DELETE"])
def api_remove_show(series_id):
    db_remove_show(series_id)
    return jsonify({"status": "removed"})


@app.route("/api/channel/queue")
def api_queue():
    rebuild = request.args.get("rebuild", "false").lower() == "true"
    saved = db_load_queue()

    # Return saved queue if it exists and rebuild not forced
    if saved["queue"] and not rebuild:
        _ext["queue"] = saved["queue"]
        _ext["index"] = saved["position"]
        _ext["active"] = True
        return jsonify({
            "queue": saved["queue"],
            "position": saved["position"],
            "eps_per_show": saved["eps_per_show"],
            "resumed": True,
        })

    # Build a fresh queue
    eps_per_show = max(1, min(20, int(request.args.get("eps_per_show", saved["eps_per_show"]))))
    queue = db_get_queue(eps_per_show)
    db_save_queue(queue, 0, eps_per_show)
    _ext["queue"] = queue
    _ext["index"] = 0
    _ext["active"] = True
    return jsonify({
        "queue": queue,
        "position": 0,
        "eps_per_show": eps_per_show,
        "resumed": False,
    })


@app.route("/api/channel/clear", methods=["DELETE"])
def api_clear():
    db_clear()
    db_save_queue([], 0, 2)
    _ext["queue"] = []
    _ext["index"] = 0
    return jsonify({"status": "cleared"})


@app.route("/api/channel/queue/reset", methods=["POST"])
def api_reset_queue():
    """Discard saved queue so next launch builds a fresh one."""
    db_save_queue([], 0, 2)
    _ext["queue"] = []
    _ext["index"] = 0
    return jsonify({"status": "reset"})


# ─── EXTENSION API ───────────────────────────────────────────────────────────

@app.route("/api/channel/extension/status")
def ext_status():
    """Popup polls this to show current queue position and active state."""
    # If in-memory queue is empty (server restarted), reload from DB
    if not _ext["queue"]:
        saved = db_load_queue()
        if saved["queue"]:
            _ext["queue"] = saved["queue"]
            _ext["index"] = saved["position"]
    current = _ext["queue"][_ext["index"]] if _ext["queue"] else None
    return jsonify({
        "active": _ext["active"],
        "queue_index": _ext["index"],
        "queue_length": len(_ext["queue"]),
        "current": current,
    })

@app.route("/api/channel/extension/get_credits_secs", methods=["POST"])
def ext_credits():
    """Popup gets the credits timestamp for the current video."""

    ep = None
    body = request.get_json() or {}
    current_video_id = str(body.get("current_video_id", ""))

    if current_video_id:
        ep = db_get_episode(current_video_id)

    return jsonify({
        "credits_secs": ep['credits_secs'] if ep else None,
    })


@app.route("/api/channel/extension/active", methods=["POST"])
def ext_set_active():
    """Popup toggles auto-advance on/off."""
    body = request.get_json()
    _ext["active"] = bool(body.get("active", False))
    current = _ext["queue"][_ext["index"]] if _ext["queue"] else None
    return jsonify({
        "active": _ext["active"],
        "queue_index": _ext["index"],
        "queue_length": len(_ext["queue"]),
        "current": current,
    })


@app.route("/api/channel/advance", methods=["POST"])
def ext_advance():
    """
    Called by content.js when a video ends.
    Advances the queue pointer and returns the next episode URL.
    """
    if not _ext["active"]:
        return jsonify({"status": "inactive"})

    if not _ext["queue"]:
        return jsonify({"status": "no_queue"})

    body = request.get_json() or {}
    current_video_id = str(body.get("current_video_id", ""))

    # Find the current episode by video id if possible, otherwise just advance
    if current_video_id:
        for i, ep in enumerate(_ext["queue"]):
            if str(ep.get("content_id", "")) == current_video_id:
                _ext["index"] = i
                break

    next_index = _ext["index"] + 1

    if next_index >= len(_ext["queue"]):
        return jsonify({"status": "queue_ended"})

    _ext["index"] = next_index
    db_save_position(next_index)   # persist so user can resume after restart
    next_ep = _ext["queue"][next_index]

    return jsonify({
        "status": "ok",
        "next_url": next_ep.get("tubi_url") or f"https://tubitv.com/video/{next_ep['content_id']}",
        "next_title": next_ep.get("title", ""),
        "next_show": next_ep.get("show_title", ""),
        "queue_index": next_index,
        "queue_length": len(_ext["queue"]),
    })


# ─── EXTENSION DOWNLOAD ──────────────────────────────────────────────────────

@app.route("/api/extension/download")
def ext_download():
    """Serve the TubiShift Chrome extension as a zip for in-browser download."""
    # Re-read at request time so tray.py patches always take effect.
    # Also try next to server.py itself as a fallback for direct python server.py usage.
    ext_dir = EXTENSION_DIR
    if not ext_dir.exists():
        ext_dir = Path(__file__).resolve().parent / "tubishift-extension"
    app.logger.info(f"Extension download: looking in {ext_dir}")
    if not ext_dir.exists():
        return jsonify({"error": f"Extension directory not found: {ext_dir}"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ext_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                zf.write(f, f"tubishift-extension/{f.relative_to(ext_dir)}")
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="tubishift-extension.zip",
    )


# ─── STATIC ───────────────────────────────────────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    static = app.static_folder
    if path and os.path.exists(os.path.join(static, path)):
        return send_from_directory(static, path)
    return send_from_directory(static, "index.html")


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    init_db()
    print("\n🟠 TubiShift starting...")
    print(f"💾 Database: {DB_PATH}")
    ensure_authenticated()
    print("📺 Open http://localhost:5000\n")
    app.run(debug=True, port=5000)