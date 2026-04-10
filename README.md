# binz

Waltham Forest bin collection day checker. Scrapes the council portal via Playwright and reports upcoming collection dates.

## Setup

```bash
pip install playwright
playwright install chromium
```

Edit `config.json` with your postcode and house number.

## Usage

```bash
python bin_checker.py              # Fetch and print next collections
python bin_checker.py --json       # JSON output
python bin_checker.py --save       # Save to last_check.json
python bin_checker.py --last       # Show last saved results (no fetch)
python bin_checker.py --visible -v # Debug: visible browser + progress
```

## Web interface

```bash
python web.py                # http://127.0.0.1:5000
python web.py --port 8080    # custom port
```

Shows cached results from `last_check.json` and has a **Refresh now** button that triggers a fresh scrape. JSON is also available at `/api/results`.

## Scheduling (Windows)

```bash
python schedule.py install                       # Weekly, Sunday 08:00
python schedule.py install --day MON --time 07:00
python schedule.py status
python schedule.py uninstall
```

Scheduled runs write results to `last_check.json` and logs to `scheduled_run.log`.

## Files

- `bin_checker.py` — portal scraper and CLI
- `web.py` — Flask web interface
- `schedule.py` — Windows Task Scheduler wrapper
- `config.json` — address configuration
- `last_check.json` — cached results from the most recent run
