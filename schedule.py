"""
Schedule the bin checker to run weekly using Windows Task Scheduler.

Usage:
    python schedule.py install          # Create weekly scheduled task (Sunday 8am)
    python schedule.py install --day MON --time 07:00  # Custom day/time
    python schedule.py uninstall        # Remove the scheduled task
    python schedule.py status           # Check if task exists and last run
"""

import argparse
import subprocess
import sys
from pathlib import Path


TASK_NAME = "WalthamForestBinChecker"
SCRIPT_DIR = Path(__file__).parent.resolve()
CHECKER_SCRIPT = SCRIPT_DIR / "bin_checker.py"


def install_task(day="SUN", time="08:00"):
    """Create a Windows scheduled task to run the bin checker weekly."""
    python_exe = sys.executable
    command = f'"{python_exe}" "{CHECKER_SCRIPT}" --save --verbose'
    log_file = SCRIPT_DIR / "scheduled_run.log"

    # Build schtasks command
    # /SC WEEKLY = run weekly, /D = day of week, /ST = start time
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'cmd /c {command} > "{log_file}" 2>&1',
        "/SC", "WEEKLY",
        "/D", day.upper(),
        "/ST", time,
        "/F",  # Force overwrite if exists
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Scheduled task '{TASK_NAME}' created successfully.")
            print(f"  Runs every {day.upper()} at {time}")
            print(f"  Results saved to: {SCRIPT_DIR / 'last_check.json'}")
            print(f"  Log file: {log_file}")
            print(f"\nTo run it now:  schtasks /Run /TN {TASK_NAME}")
            print(f"To remove it:   python schedule.py uninstall")
        else:
            print(f"Failed to create task:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print("ERROR: schtasks not found. Are you on Windows?", file=sys.stderr)
        sys.exit(1)


def uninstall_task():
    """Remove the scheduled task."""
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Scheduled task '{TASK_NAME}' removed.")
    else:
        print(f"Could not remove task (may not exist):\n{result.stderr}")


def show_status():
    """Show the current status of the scheduled task."""
    cmd = ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # Show relevant lines
        for line in result.stdout.splitlines():
            line = line.strip()
            if any(k in line for k in [
                "Task Name", "Status", "Next Run", "Last Run",
                "Last Result", "Schedule Type", "Start Time", "Days"
            ]):
                print(line)
    else:
        print(f"Task '{TASK_NAME}' not found. Run 'python schedule.py install' first.")

    # Also show last check results if available
    results_file = SCRIPT_DIR / "last_check.json"
    if results_file.exists():
        import json
        with open(results_file) as f:
            data = json.load(f)
        print(f"\nLast check: {data.get('checked_at', 'unknown')}")
        for c in data.get("collections", []):
            print(f"  {c['bin_type']}: {c.get('date', c['date_raw'])}")


def main():
    parser = argparse.ArgumentParser(
        description="Manage scheduled bin collection checks"
    )
    sub = parser.add_subparsers(dest="command")

    install_p = sub.add_parser("install", help="Create weekly scheduled task")
    install_p.add_argument(
        "--day", default="SUN",
        help="Day of week: MON,TUE,WED,THU,FRI,SAT,SUN (default: SUN)"
    )
    install_p.add_argument(
        "--time", default="08:00",
        help="Time to run, HH:MM format (default: 08:00)"
    )

    sub.add_parser("uninstall", help="Remove the scheduled task")
    sub.add_parser("status", help="Show task status and last results")

    args = parser.parse_args()

    if args.command == "install":
        install_task(args.day, args.time)
    elif args.command == "uninstall":
        uninstall_task()
    elif args.command == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
