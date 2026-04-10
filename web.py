"""
Simple web interface for the bin checker.

Usage:
    python web.py              # Run on http://127.0.0.1:5000
    python web.py --port 8080  # Custom port
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

from bin_checker import fetch_bin_collections, load_config

APP_DIR = Path(__file__).parent
RESULTS_PATH = Path(os.environ.get("RESULTS_PATH", APP_DIR / "last_check.json"))

app = Flask(__name__)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bin Collections</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
    max-width: 560px; margin: 2rem auto; padding: 0 1rem;
  }
  h1 { margin-bottom: 0.25rem; }
  .meta { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  ul { list-style: none; padding: 0; }
  li {
    display: flex; justify-content: space-between;
    padding: 0.75rem 1rem; margin-bottom: 0.5rem;
    border: 1px solid #ccc3; border-radius: 8px;
  }
  .bin { font-weight: 600; }
  .date { color: #0a7; }
  .soon .date { color: #e60; font-weight: 600; }
  button {
    padding: 0.6rem 1.2rem; font-size: 1rem; cursor: pointer;
    border-radius: 6px; border: 1px solid #888;
    background: #0a7; color: white;
  }
  button:disabled { opacity: 0.5; cursor: wait; }
  .error { color: #c00; margin-top: 1rem; }
  .empty { color: #888; font-style: italic; }
</style>
</head>
<body>
  <h1>Bin Collections</h1>
  <div class="meta">
    {% if data %}
      {{ data.address }}<br>
      Last checked: {{ data.checked_at }}
    {% else %}
      No data yet &mdash; click Refresh to fetch.
    {% endif %}
  </div>

  {% if data and data.collections %}
  <ul>
    {% for c in data.collections %}
      <li class="{% if c.soon %}soon{% endif %}">
        <span class="bin">{{ c.bin_type }}</span>
        <span class="date">{{ c.friendly or c.date_raw }}</span>
      </li>
    {% endfor %}
  </ul>
  {% elif data %}
    <p class="empty">No collections found.</p>
  {% endif %}

  <button id="refresh">Refresh now</button>
  <p class="error" id="err"></p>

<script>
  const btn = document.getElementById('refresh');
  const err = document.getElementById('err');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = 'Checking (this can take 30-60s)...';
    err.textContent = '';
    try {
      const r = await fetch('/api/refresh', { method: 'POST' });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || 'Request failed');
      location.reload();
    } catch (e) {
      err.textContent = 'Error: ' + e.message;
      btn.disabled = false;
      btn.textContent = 'Refresh now';
    }
  });
</script>
</body>
</html>
"""


def load_results():
    if not RESULTS_PATH.exists():
        return None
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    enrich(data)
    return data


def enrich(data):
    """Add friendly date strings and 'soon' flag to each collection."""
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
    # Sort by date where possible
    data["collections"].sort(
        key=lambda c: c.get("date") or "9999-12-31"
    )


@app.route("/")
def index():
    return render_template_string(PAGE, data=load_results())


@app.route("/api/results")
def api_results():
    data = load_results()
    if data is None:
        return jsonify({"error": "no results yet"}), 404
    return jsonify(data)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        config = load_config()
        collections = fetch_bin_collections(config, headless=True, verbose=False)
    except SystemExit as e:
        return jsonify({"error": f"scrape failed (exit {e.code})"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "address": f"{config.get('house_number', '')} {config.get('postcode', '')}".strip(),
        "collections": collections,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2)
    enrich(result)
    return jsonify(result)


def main():
    parser = argparse.ArgumentParser(description="Bin checker web UI")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Bind host (default: 0.0.0.0, override with $HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "5000")),
        help="Bind port (default: $PORT or 5000)",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
