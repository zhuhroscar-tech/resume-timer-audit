"""resume-timer-audit CLI."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import collect_and_evaluate

LEVEL_EXIT = {"info": 0, "warn": 1, "fail": 2}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resume-timer-audit",
        description=(
            "Detect systemd timers that cluster/stall right after resume-from-"
            "suspend (systemd upstream issue #43350). Strictly read-only: never "
            "modifies timers, services, or systemd configuration."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--lookback-days", type=int, default=14,
        help="How many days of journalctl history to scan for resume events (default: 14).",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text.")
    return p


def _print_text(report) -> None:
    print(f"resume-timer-audit: {report.resume_events_seen} resume event(s), "
          f"{report.timers_inspected} timer(s) inspected\n")
    for f in report.findings:
        tag = {"info": "[info]", "warn": "[warn]", "fail": "[FAIL]"}[f.level]
        print(f"{tag} {f.message}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_and_evaluate(lookback_days=args.lookback_days)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_text(report)

    return LEVEL_EXIT.get(report.worst_level(), 0)


if __name__ == "__main__":
    sys.exit(main())
