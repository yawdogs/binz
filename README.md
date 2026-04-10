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
- `schedule.py` — Windows Task Scheduler wrapper
- `config.json` — address configuration
- `last_check.json` — cached results from the most recent run
