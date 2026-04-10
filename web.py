"""
Web interface for the bin checker with optional user accounts.

Usage:
    python web.py              # http://127.0.0.1:5000
    python web.py --port 8080

Environment:
    PORT           Bind port (Railway sets this)
    HOST           Bind host (default 0.0.0.0)
    SECRET_KEY     Flask session secret. Set a stable value in production,
                   otherwise sessions are invalidated on every restart.
    DB_PATH        SQLite database path (default ./binz.db). On Railway,
                   point this at a mounted volume for persistence.
"""

import argparse
import json
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, flash, g, jsonify, redirect, render_template_string,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from bin_checker import fetch_bin_collections, load_config

APP_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", APP_DIR / "binz.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    db = g.get("_db")
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("_db", None)
    if db is not None:
        db.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY,
                email           TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                postcode        TEXT,
                house_number    TEXT,
                last_check_json TEXT,
                created_at      TEXT NOT NULL
            )
            """
        )


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (uid,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

STYLE = """
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
    max-width: 560px; margin: 2rem auto; padding: 0 1rem;
  }
  h1 { margin-bottom: 0.25rem; }
  nav { margin-bottom: 1.5rem; font-size: 0.9rem; }
  nav a, nav span { margin-right: 0.75rem; }
  .meta { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  ul.bins { list-style: none; padding: 0; }
  ul.bins li {
    display: flex; justify-content: space-between;
    padding: 0.75rem 1rem; margin-bottom: 0.5rem;
    border: 1px solid #ccc3; border-radius: 8px;
  }
  .bin { font-weight: 600; }
  .date { color: #0a7; }
  .soon .date { color: #e60; font-weight: 600; }
  form.stack { display: flex; flex-direction: column; gap: 0.75rem; margin: 1rem 0; }
  form.stack label { display: flex; flex-direction: column; font-size: 0.9rem; }
  input[type=text], input[type=email], input[type=password] {
    padding: 0.5rem; font-size: 1rem; border-radius: 6px;
    border: 1px solid #888; background: transparent; color: inherit;
  }
  button {
    padding: 0.6rem 1.2rem; font-size: 1rem; cursor: pointer;
    border-radius: 6px; border: 1px solid #888;
    background: #0a7; color: white;
  }
  .error { color: #c00; }
  .flash { padding: 0.5rem 1rem; background: #0a71; border-radius: 6px; margin-bottom: 1rem; }
  .empty { color: #888; font-style: italic; }
  .row { display: flex; gap: 0.5rem; align-items: center; }
</style>
"""

NAV = """
<nav>
  <a href="{{ url_for('index') }}">Home</a>
  {% if user %}
    <span>{{ user['email'] }}</span>
    <a href="{{ url_for('logout') }}">Sign out</a>
  {% else %}
    <a href="{{ url_for('login') }}">Sign in</a>
    <a href="{{ url_for('register') }}">Create account</a>
  {% endif %}
</nav>
{% with messages = get_flashed_messages() %}
  {% if messages %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endif %}
{% endwith %}
"""

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>When is binz?</title>""" + STYLE + """</head>
<body>
""" + NAV + """
<h1>When is binz?</h1>
<p class="meta">Waltham Forest council portal lookup.</p>

<form class="stack" method="post" action="{{ url_for('check') }}">
  <label>Postcode
    <input type="text" name="postcode" value="{{ postcode or '' }}" required placeholder="E17 3BT">
  </label>
  <label>House number or name
    <input type="text" name="house_number" value="{{ house_number or '' }}" required placeholder="12">
  </label>
  {% if user %}
    <label class="row">
      <input type="checkbox" name="save_details" value="1" checked>
      Save as my default
    </label>
  {% endif %}
  <button type="submit">Check collections</button>
</form>

{% if data %}
  <div class="meta">
    {% if data.address %}{{ data.address }}<br>{% endif %}
    Last checked: {{ data.checked_at }}
  </div>
  {% if data.collections %}
    <ul class="bins">
      {% for c in data.collections %}
        <li class="{% if c.soon %}soon{% endif %}">
          <span class="bin">{{ c.bin_type }}</span>
          <span class="date">{{ c.friendly or c.date_raw }}</span>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="empty">No collections found.</p>
  {% endif %}
{% endif %}

{% if not user %}
  <p class="meta"><a href="{{ url_for('register') }}">Create an account</a> to save your address.</p>
{% endif %}
</body></html>
"""

AUTH_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ title }} &mdash; When is binz?</title>""" + STYLE + """</head>
<body>
""" + NAV + """
<h1>{{ title }}</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form class="stack" method="post">
  <label>Email
    <input type="email" name="email" value="{{ email or '' }}" required autofocus>
  </label>
  <label>Password
    <input type="password" name="password" required>
  </label>
  <button type="submit">{{ title }}</button>
</form>
</body></html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def enrich(data):
    """Add friendly date strings and 'soon' flag in-place; sort by date."""
    today = datetime.now().date()
    for c in data.get("collections", []):
        c["friendly"] = None
        c["soon"] = False
        if c.get("date"):
            try:
                dt = datetime.strptime(c["date"], "%Y-%m-%d").date()
                c["friendly"] = dt.strftime("%A %d %B %Y")
                c["soon"] = (dt - today).days <= 2
            except ValueError:
                pass
    data.get("collections", []).sort(
        key=lambda c: c.get("date") or "9999-12-31"
    )


def run_check(postcode, house_number):
    base = load_config()
    cfg = {
        "portal_url": base["portal_url"],
        "postcode": postcode,
        "address_search": house_number,
    }
    collections = fetch_bin_collections(cfg, headless=True, verbose=False)
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "address": f"{house_number} {postcode}".strip(),
        "collections": collections,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    user = current_user()
    postcode = user["postcode"] if user else None
    house_number = user["house_number"] if user else None

    data = None
    if user and user["last_check_json"]:
        try:
            data = json.loads(user["last_check_json"])
        except json.JSONDecodeError:
            data = None
    elif not user:
        data = session.get("last_check")

    if data:
        enrich(data)

    return render_template_string(
        INDEX_HTML, user=user, data=data,
        postcode=postcode, house_number=house_number,
    )


@app.route("/check", methods=["POST"])
def check():
    postcode = (request.form.get("postcode") or "").strip()
    house_number = (request.form.get("house_number") or "").strip()
    if not postcode or not house_number:
        flash("Postcode and house number are required.")
        return redirect(url_for("index"))

    try:
        result = run_check(postcode, house_number)
    except SystemExit:
        flash("Scrape failed — the council site may be down.")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Error: {e}")
        return redirect(url_for("index"))

    user = current_user()
    if user:
        updates = {"last_check_json": json.dumps(result)}
        if request.form.get("save_details"):
            updates["postcode"] = postcode
            updates["house_number"] = house_number
        sets = ", ".join(f"{k} = ?" for k in updates)
        db = get_db()
        db.execute(
            f"UPDATE users SET {sets} WHERE id = ?",
            (*updates.values(), user["id"]),
        )
        db.commit()
    else:
        session["last_check"] = result

    return redirect(url_for("index"))


@app.route("/api/results")
def api_results():
    user = current_user()
    if user and user["last_check_json"]:
        return jsonify(json.loads(user["last_check_json"]))
    cached = session.get("last_check")
    if cached:
        return jsonify(cached)
    return jsonify({"error": "no results yet"}), 404


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            error = "Email and password are required."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        else:
            try:
                db = get_db()
                cur = db.execute(
                    "INSERT INTO users (email, password_hash, created_at) "
                    "VALUES (?, ?, ?)",
                    (
                        email,
                        generate_password_hash(password),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
                session["user_id"] = cur.lastrowid
                flash("Account created.")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "That email is already registered."
    return render_template_string(
        AUTH_HTML, title="Create account", user=current_user(),
        error=error, email=email,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        row = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session["user_id"] = row["id"]
            flash("Signed in.")
            return redirect(url_for("index"))
        error = "Invalid email or password."
    return render_template_string(
        AUTH_HTML, title="Sign in", user=current_user(),
        error=error, email=email,
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Init + main
# ---------------------------------------------------------------------------

init_db()


def main():
    parser = argparse.ArgumentParser(description="Bin checker web UI")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "5000"))
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
