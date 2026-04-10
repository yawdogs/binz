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

HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b9e6e" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0a1512" media="(prefers-color-scheme: dark)">
<style>
  :root {
    color-scheme: light dark;
    --bg: #f7f8f7;
    --surface: #ffffff;
    --surface-2: #f1f3f2;
    --border: #e2e5e3;
    --text: #10201a;
    --muted: #64726b;
    --accent: #0b9e6e;
    --accent-contrast: #ffffff;
    --accent-soft: #0b9e6e14;
    --danger: #c0392b;
    --warn: #e67e22;
    --radius: 14px;
    --radius-sm: 10px;
    --shadow: 0 1px 2px rgba(16, 32, 26, 0.04), 0 8px 24px rgba(16, 32, 26, 0.06);
    --focus: 0 0 0 3px #0b9e6e40;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0a1512;
      --surface: #121e1a;
      --surface-2: #18262114;
      --border: #1f2e28;
      --text: #e7efe9;
      --muted: #8a9992;
      --accent: #2dd4a0;
      --accent-contrast: #05201a;
      --accent-soft: #2dd4a022;
      --danger: #ff7a6b;
      --warn: #ffb366;
      --shadow: 0 1px 2px rgba(0,0,0,0.4), 0 12px 32px rgba(0,0,0,0.35);
      --focus: 0 0 0 3px #2dd4a060;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.5;
    color: var(--text);
    background: var(--bg);
    -webkit-font-smoothing: antialiased;
    padding: max(1rem, env(safe-area-inset-top))
             max(1rem, env(safe-area-inset-right))
             max(1.5rem, env(safe-area-inset-bottom))
             max(1rem, env(safe-area-inset-left));
  }
  .wrap { max-width: 36rem; margin: 0 auto; }

  nav {
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem 1rem;
    padding: 0.75rem 0; margin-bottom: 1rem;
    font-size: 0.925rem;
    border-bottom: 1px solid var(--border);
  }
  nav a { color: var(--accent); text-decoration: none; font-weight: 500; }
  nav a:hover { text-decoration: underline; }
  nav .spacer { flex: 1; }
  nav .user { color: var(--muted); font-size: 0.875rem; }

  h1 {
    font-size: clamp(1.5rem, 4vw + 1rem, 2.25rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    margin: 0.5rem 0 0.25rem;
  }
  .meta { color: var(--muted); font-size: 0.9rem; margin: 0 0 1.25rem; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 1.25rem;
    margin-bottom: 1.25rem;
  }
  @media (min-width: 480px) {
    .card { padding: 1.5rem; }
  }

  form.stack { display: flex; flex-direction: column; gap: 1rem; margin: 0; }
  form.stack label {
    display: flex; flex-direction: column; gap: 0.375rem;
    font-size: 0.825rem; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  input[type=text], input[type=email], input[type=password] {
    width: 100%;
    font: inherit; font-size: 1rem;
    padding: 0.75rem 0.875rem;
    min-height: 44px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: var(--focus);
  }
  input::placeholder { color: var(--muted); opacity: 0.7; }

  .row {
    display: flex; align-items: center; gap: 0.625rem;
    font-size: 0.9rem; font-weight: 400; color: var(--text);
    text-transform: none; letter-spacing: 0;
  }
  .row input[type=checkbox] {
    width: 1.15rem; height: 1.15rem; accent-color: var(--accent);
  }

  button {
    width: 100%;
    font: inherit; font-size: 1rem; font-weight: 600;
    padding: 0.875rem 1.25rem;
    min-height: 48px;
    cursor: pointer;
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    background: var(--accent); color: var(--accent-contrast);
    transition: transform 0.05s, filter 0.15s, box-shadow 0.15s;
  }
  button:hover { filter: brightness(1.05); }
  button:active { transform: translateY(1px); }
  button:focus-visible { box-shadow: var(--focus); outline: none; }

  ul.bins { list-style: none; padding: 0; margin: 0; }
  ul.bins li {
    display: flex; align-items: center; justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.125rem;
    margin-bottom: 0.625rem;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  ul.bins li:last-child { margin-bottom: 0; }
  .bin { font-weight: 600; font-size: 1rem; }
  .date {
    font-variant-numeric: tabular-nums;
    color: var(--muted); font-size: 0.925rem; text-align: right;
  }
  .soon { border-color: var(--warn); background: color-mix(in srgb, var(--warn) 10%, var(--surface)); }
  .soon .date { color: var(--warn); font-weight: 700; }
  .soon .bin::before { content: "• "; color: var(--warn); }

  .error { color: var(--danger); margin: 0 0 1rem; font-size: 0.925rem; }
  .flash {
    padding: 0.75rem 1rem;
    background: var(--accent-soft);
    border: 1px solid var(--accent);
    color: var(--text);
    border-radius: var(--radius-sm);
    margin-bottom: 1rem;
    font-size: 0.925rem;
  }
  .empty { color: var(--muted); font-style: italic; margin: 0; }

  @media (min-width: 480px) {
    button.inline { width: auto; }
  }
</style>
"""

NAV = """
<nav>
  <a href="{{ url_for('index') }}">Home</a>
  <span class="spacer"></span>
  {% if user %}
    <span class="user">{{ user['email'] }}</span>
    <a href="{{ url_for('logout') }}">Sign out</a>
  {% else %}
    <a href="{{ url_for('login') }}">Sign in</a>
    <a href="{{ url_for('register') }}">Register</a>
  {% endif %}
</nav>
{% with messages = get_flashed_messages() %}
  {% if messages %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endif %}
{% endwith %}
"""

INDEX_HTML = """<!doctype html>
<html lang="en"><head><title>When is binz?</title>""" + HEAD + """</head>
<body>
<div class="wrap">
""" + NAV + """
<h1>When is binz?</h1>
<p class="meta">Waltham Forest council portal lookup.</p>

<div class="card">
  <form class="stack" method="post" action="{{ url_for('check') }}">
    <label>Postcode
      <input type="text" name="postcode" value="{{ postcode or '' }}"
             required placeholder="E17 3BT"
             autocomplete="postal-code" autocapitalize="characters"
             inputmode="text" spellcheck="false">
    </label>
    <label>House number or name
      <input type="text" name="house_number" value="{{ house_number or '' }}"
             required placeholder="12"
             autocomplete="street-address">
    </label>
    {% if user %}
      <label class="row">
        <input type="checkbox" name="save_details" value="1" checked>
        Save as my default
      </label>
    {% endif %}
    <button type="submit">Check collections</button>
  </form>
</div>

{% if data %}
  <div class="card">
    <p class="meta">
      {% if data.address %}<strong style="color: var(--text);">{{ data.address }}</strong><br>{% endif %}
      Checked {{ data.checked_at }}
    </p>
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
  </div>
{% endif %}

{% if not user %}
  <p class="meta"><a href="{{ url_for('register') }}" style="color: var(--accent);">Create an account</a> to save your address.</p>
{% endif %}
</div>
</body></html>
"""

AUTH_HTML = """<!doctype html>
<html lang="en"><head><title>{{ title }} &mdash; When is binz?</title>""" + HEAD + """</head>
<body>
<div class="wrap">
""" + NAV + """
<h1>{{ title }}</h1>
<div class="card">
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form class="stack" method="post">
    <label>Email
      <input type="email" name="email" value="{{ email or '' }}"
             required autofocus autocomplete="email" inputmode="email"
             spellcheck="false">
    </label>
    <label>Password
      <input type="password" name="password" required
             autocomplete="{% if title == 'Sign in' %}current-password{% else %}new-password{% endif %}">
    </label>
    <button type="submit">{{ title }}</button>
  </form>
</div>
</div>
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
