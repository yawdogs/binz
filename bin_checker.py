"""
Waltham Forest Bin Collection Day Checker

Scrapes the council portal to find upcoming bin collection dates.
Uses Playwright for browser automation to handle dynamic content.

Usage:
    python bin_checker.py           # Run once, print results
    python bin_checker.py --json    # Output as JSON
    python bin_checker.py --save    # Save results to last_check.json
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


CONFIG_PATH = Path(__file__).parent / "config.json"
RESULTS_PATH = Path(__file__).parent / "last_check.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_bin_collections(config, headless=True, verbose=False):
    """Navigate the council portal and extract bin collection dates."""
    url = config["portal_url"]
    postcode = config["postcode"]
    house_number = config["address_search"]

    collections = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(60000)  # 60s default for slow council site

        try:
            if verbose:
                print(f"Loading portal...")
            page.goto(url, wait_until="domcontentloaded", timeout=90000)

            # Wait for and switch into the AchieveForms iframe
            if verbose:
                print("Waiting for form iframe...")
            iframe_el = page.wait_for_selector(
                'iframe#fillform-frame-1', timeout=60000
            )
            frame = iframe_el.content_frame()
            if not frame:
                raise RuntimeError("Could not access form iframe")

            # Enter postcode
            if verbose:
                print(f"Entering postcode: {postcode}")
            postcode_input = frame.wait_for_selector(
                'input[name="postcode_search"]', state="visible", timeout=60000
            )
            postcode_input.click()
            postcode_input.fill(postcode)

            # Click "Find Address"
            if verbose:
                print("Clicking Find Address...")
            find_btn = frame.wait_for_selector(
                '#lookupPostcode', state="visible", timeout=30000
            )
            find_btn.click()

            # Wait for address dropdown to populate, then open it
            if verbose:
                print("Waiting for address dropdown...")
            page.wait_for_timeout(2000)  # Let Select2 widget fully render

            dropdown_trigger = frame.wait_for_selector(
                '.select2-choice', state="visible", timeout=30000
            )
            dropdown_trigger.click()

            # Type house number into the search box to filter
            if verbose:
                print(f"Searching for house number: {house_number}")
            search_input = frame.wait_for_selector(
                '.select2-input', state="visible", timeout=15000
            )
            search_input.click()
            search_input.fill(house_number)
            page.wait_for_timeout(1500)  # Let search results filter

            # Select the first matching result
            search_input.press("Enter")
            page.wait_for_timeout(1000)

            # Confirm the address
            if verbose:
                print("Confirming address...")
            confirm_btn = frame.wait_for_selector(
                '#confirmSearchUPRN', state="visible", timeout=30000
            )
            confirm_btn.click()

            # Wait for collection results to load
            if verbose:
                print("Waiting for collection results...")
            frame.wait_for_selector(
                'h4:has-text("Next Collections")', timeout=60000
            )
            page.wait_for_timeout(3000)  # Let all results render

            # Extract collection data from the page
            content = frame.content()
            collections = parse_collections(content)

            if verbose:
                print(f"Found {len(collections)} collection types")

        except PlaywrightTimeout as e:
            print(f"ERROR: Timeout waiting for page element - the council "
                  f"site may be down or slow.\n{e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            browser.close()

    return collections


def parse_collections(html_content):
    """Parse bin collection dates from the page HTML."""
    collections = []

    # Find all center-aligned divs that contain collection info
    # Pattern: <h5>Bin Type</h5> ... <p><b>date</b></p>
    # Using regex since we already have the HTML string
    blocks = re.findall(
        r'<div[^>]*style="text-align:\s*center[^"]*"[^>]*>(.*?)</div>',
        html_content,
        re.DOTALL | re.IGNORECASE,
    )

    for block in blocks:
        # Extract bin type from h5
        type_match = re.search(r'<h5[^>]*>(.*?)</h5>', block, re.DOTALL)
        if not type_match:
            continue
        bin_type = re.sub(r'<[^>]+>', '', type_match.group(1)).strip()
        if not bin_type:
            continue

        # Extract date from the block - look for day+date patterns
        block_text = re.sub(r'<[^>]+>', ' ', block)
        block_text = re.sub(r'\s+', ' ', block_text).strip()

        # Look for date pattern like "Friday 10 April" or "10 April"
        raw_date = re.search(
            r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*(\d+\s+\w+)',
            block_text
        )
        if not raw_date:
            continue

        date_text = raw_date.group(1).strip()
        collection_date = None
        try:
            year = datetime.now().year
            parsed = datetime.strptime(f"{date_text} {year}", "%d %B %Y")
            # If the date is in the past, it's probably next year
            if parsed.date() < datetime.now().date():
                parsed = parsed.replace(year=year + 1)
            collection_date = parsed.strftime("%Y-%m-%d")
        except ValueError:
            collection_date = date_text

        # Get the full date string including day name
        full_match = re.search(
            r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d+\s+\w+)',
            block_text
        )
        date_display = full_match.group(1) if full_match else date_text

        collections.append({
            "bin_type": bin_type,
            "date_raw": date_display,
            "date": collection_date,
        })

    return collections


def format_output(collections, checked_at):
    """Format collections for human-readable display."""
    lines = []
    lines.append(f"=== Bin Collection Days ===")
    lines.append(f"Address: 12 Seaford Road, E17 3BT")
    lines.append(f"Checked: {checked_at}")
    lines.append("")

    if not collections:
        lines.append("No collection dates found. The site may be "
                      "experiencing issues.")
        return "\n".join(lines)

    # Sort by date
    dated = [c for c in collections if c.get("date")]
    undated = [c for c in collections if not c.get("date")]
    dated.sort(key=lambda c: c["date"])

    for c in dated:
        try:
            dt = datetime.strptime(c["date"], "%Y-%m-%d")
            friendly = dt.strftime("%A %d %B %Y")
        except ValueError:
            friendly = c["date_raw"]
        lines.append(f"  {c['bin_type']:.<30} {friendly}")

    for c in undated:
        lines.append(f"  {c['bin_type']:.<30} {c['date_raw']}")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check Waltham Forest bin collection dates"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save results to last_check.json"
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Run browser visibly (not headless) for debugging"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show progress messages"
    )
    parser.add_argument(
        "--last", action="store_true",
        help="Show last saved results without fetching"
    )
    args = parser.parse_args()

    # Show cached results
    if args.last:
        if RESULTS_PATH.exists():
            with open(RESULTS_PATH) as f:
                data = json.load(f)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(format_output(data["collections"], data["checked_at"]))
        else:
            print("No saved results found. Run without --last first.")
        return

    config = load_config()
    collections = fetch_bin_collections(
        config, headless=not args.visible, verbose=args.verbose
    )

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "checked_at": checked_at,
        "address": "12 Seaford Road, E17 3BT",
        "collections": collections,
    }

    if args.save or not args.json:
        # Always save when running
        with open(RESULTS_PATH, "w") as f:
            json.dump(result, f, indent=2)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_output(collections, checked_at))


if __name__ == "__main__":
    main()
