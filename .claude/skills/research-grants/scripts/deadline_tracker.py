#!/usr/bin/env python3
"""
Grant Deadline Tracker

Tracks submission deadlines for major funding agencies and generates
working-backwards timelines for proposal preparation.

Usage:
    python deadline_tracker.py --agency NIH --mechanism R01 --deadline 2025-06-05
    python deadline_tracker.py --list-agencies
    python deadline_tracker.py --list-mechanisms NIH
"""

import argparse
import json
import sys
# Fix Windows console encoding for emoji/non-ASCII characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from datetime import datetime, timedelta
from typing import Dict, List, Optional


# Standard deadline databases (these should be updated regularly)
DEADLINES = {
    "NIH": {
        "R01": {
            "deadlines": ["February 5", "June 5", "October 5"],
            "cycle": "Standard dates",
            "typical_review": "6-9 months",
            "typical_award": "9-12 months after submission"
        },
        "R21": {
            "deadlines": ["February 16", "June 16", "October 16"],
            "cycle": "Standard dates",
            "typical_review": "6-9 months",
            "typical_award": "9-12 months after submission"
        },
        "R03": {
            "deadlines": ["February 16", "June 16", "October 16"],
            "cycle": "Standard dates",
            "typical_review": "6-9 months",
            "typical_award": "9-12 months after submission"
        },
        "K99": {
            "deadlines": ["February 12", "June 12", "October 12"],
            "cycle": "Standard dates",
            "typical_review": "6-9 months",
            "typical_award": "9-12 months after submission"
        }
    },
    "NSF": {
        "Standard": {
            "deadlines": ["Varies by program"],
            "cycle": "Annual or biannual",
            "typical_review": "6-12 months",
            "typical_award": "12-18 months after submission"
        },
        "CAREER": {
            "deadlines": ["July (annual)"],
            "cycle": "Annual",
            "typical_review": "6-9 months",
            "typical_award": "October following submission"
        },
        "RAPID": {
            "deadlines": ["Anytime"],
            "cycle": "Rolling",
            "typical_review": "2-4 weeks",
            "typical_award": "1-2 months after submission"
        },
        "EAGER": {
            "deadlines": ["Anytime (contact PO first)"],
            "cycle": "Rolling",
            "typical_review": "2-4 months",
            "typical_award": "3-6 months after submission"
        }
    },
    "DOE": {
        "Office of Science": {
            "deadlines": ["Varies by program"],
            "cycle": "Annual or periodic",
            "typical_review": "4-8 months",
            "typical_award": "6-12 months after submission"
        },
        "ARPA-E": {
            "deadlines": ["Varies by FOA"],
            "cycle": "Periodic",
            "typical_review": "3-6 months",
            "typical_award": "6-12 months after submission"
        }
    },
    "DARPA": {
        "BAA": {
            "deadlines": ["Varies by program"],
            "cycle": "Program-specific",
            "typical_review": "3-6 months",
            "typical_award": "6-12 months after submission"
        },
        "YFA": {
            "deadlines": ["Varies (typically fall)"],
            "cycle": "Annual",
            "typical_review": "4-6 months",
            "typical_award": "6-12 months after submission"
        }
    },
    "NSFC": {
        "General Program": {
            "deadlines": ["March (annual)"],
            "cycle": "Annual",
            "typical_review": "6-8 months",
            "typical_award": "January following submission"
        },
        "Young Scientists": {
            "deadlines": ["March (annual)"],
            "cycle": "Annual",
            "typical_review": "6-8 months",
            "typical_award": "January following submission"
        }
    },
    "DOT": {
        "UTC": {
            "deadlines": ["Varies by competition"],
            "cycle": "5-year competitions",
            "typical_review": "6-12 months",
            "typical_award": "12-18 months after submission"
        },
        "SPR": {
            "deadlines": ["Varies by state"],
            "cycle": "Annual",
            "typical_review": "3-6 months",
            "typical_award": "6-12 months after submission"
        }
    }
}


def get_preparation_timeline(deadline_date: datetime) -> List[Dict]:
    """Generate a working-backwards preparation timeline."""

    timeline = [
        {
            "milestone": "Final submission",
            "date": deadline_date,
            "description": "Submit proposal through agency portal"
        },
        {
            "milestone": "Final review and formatting",
            "date": deadline_date - timedelta(days=3),
            "description": "Final proofreading, formatting check, PDF conversion"
        },
        {
            "milestone": "Internal review complete",
            "date": deadline_date - timedelta(days=14),
            "description": "Incorporate feedback from internal reviewers"
        },
        {
            "milestone": "Internal review submitted",
            "date": deadline_date - timedelta(days=21),
            "description": "Send draft to 2-3 colleagues for feedback"
        },
        {
            "milestone": "Budget finalized",
            "date": deadline_date - timedelta(days=28),
            "description": "Finalize budget with grants office"
        },
        {
            "milestone": "Full draft complete",
            "date": deadline_date - timedelta(days=35),
            "description": "Complete first full draft of all sections"
        },
        {
            "milestone": "Specific Aims/Project Summary drafted",
            "date": deadline_date - timedelta(days=49),
            "description": "Draft the 1-page summary/aims"
        },
        {
            "milestone": "Research plan outlined",
            "date": deadline_date - timedelta(days=63),
            "description": "Detailed outline of research approach"
        },
        {
            "milestone": "Literature review complete",
            "date": deadline_date - timedelta(days=77),
            "description": "Complete literature search and synthesis"
        },
        {
            "milestone": "Project initiated",
            "date": deadline_date - timedelta(days=90),
            "description": "Begin proposal preparation, identify collaborators"
        }
    ]

    return timeline


def check_upcoming_deadlines(agency: Optional[str] = None) -> List[Dict]:
    """Check for upcoming deadlines in the next 12 months."""
    upcoming = []
    today = datetime.now()
    cutoff = today + timedelta(days=365)

    for agency_name, mechanisms in DEADLINES.items():
        if agency and agency.upper() != agency_name.upper():
            continue

        for mechanism, info in mechanisms.items():
            for deadline_str in info["deadlines"]:
                try:
                    # Try to parse the deadline
                    if "varies" in deadline_str.lower() or "anytime" in deadline_str.lower():
                        continue

                    # Parse month names
                    for year in range(today.year, today.year + 2):
                        try:
                            deadline = datetime.strptime(f"{deadline_str} {year}", "%B %d %Y")
                            if today <= deadline <= cutoff:
                                days_until = (deadline - today).days
                                upcoming.append({
                                    "agency": agency_name,
                                    "mechanism": mechanism,
                                    "deadline": deadline.strftime("%Y-%m-%d"),
                                    "days_until": days_until,
                                    "status": "URGENT" if days_until <= 30 else "UPCOMING"
                                })
                        except ValueError:
                            continue
                except Exception:
                    continue

    # Sort by days until deadline
    upcoming.sort(key=lambda x: x["days_until"])
    return upcoming


def print_timeline(timeline: List[Dict], deadline_date: datetime):
    """Print preparation timeline."""
    print(f"\n{'='*60}")
    print(f"Proposal Preparation Timeline")
    print(f"Deadline: {deadline_date.strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")

    for item in timeline:
        days_before = (deadline_date - item["date"]).days
        print(f"[DATE] {item['date'].strftime('%Y-%m-%d')} ({days_before:3d} days before)")
        print(f"   {item['milestone']}")
        print(f"   {item['description']}")
        print()


def print_upcoming(upcoming: List[Dict]):
    """Print upcoming deadlines."""
    print(f"\n{'='*60}")
    print(f"Upcoming Deadlines (next 12 months)")
    print(f"{'='*60}\n")

    if not upcoming:
        print("No upcoming deadlines found.")
        return

    for item in upcoming:
        status_icon = "[URGENT]" if item["status"] == "URGENT" else "[SOON]"
        print(f"{status_icon} {item['agency']} {item['mechanism']}")
        print(f"   Deadline: {item['deadline']} ({item['days_until']} days)")
        print()


def list_agencies():
    """List all supported agencies."""
    print("\nSupported Agencies:")
    for agency in DEADLINES.keys():
        print(f"  - {agency}")


def list_mechanisms(agency: str):
    """List mechanisms for an agency."""
    mechanisms = DEADLINES.get(agency.upper())
    if not mechanisms:
        print(f"Unknown agency: {agency}")
        return

    print(f"\n{agency.upper()} Mechanisms:")
    for mechanism, info in mechanisms.items():
        deadlines = ", ".join(info["deadlines"])
        print(f"  - {mechanism}: {deadlines}")


def main():
    parser = argparse.ArgumentParser(description='Track grant deadlines')
    parser.add_argument('--agency', help='Funding agency')
    parser.add_argument('--mechanism', help='Funding mechanism')
    parser.add_argument('--deadline', help='Specific deadline date (YYYY-MM-DD)')
    parser.add_argument('--list-agencies', action='store_true', help='List all agencies')
    parser.add_argument('--list-mechanisms', help='List mechanisms for an agency')
    parser.add_argument('--upcoming', action='store_true', help='Show upcoming deadlines')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    if args.list_agencies:
        list_agencies()
        return

    if args.list_mechanisms:
        list_mechanisms(args.list_mechanisms)
        return

    if args.upcoming:
        upcoming = check_upcoming_deadlines(args.agency)
        if args.json:
            print(json.dumps(upcoming, indent=2))
        else:
            print_upcoming(upcoming)
        return

    if args.deadline:
        try:
            deadline_date = datetime.strptime(args.deadline, "%Y-%m-%d")
            timeline = get_preparation_timeline(deadline_date)

            if args.json:
                print(json.dumps([{
                    "milestone": t["milestone"],
                    "date": t["date"].strftime("%Y-%m-%d"),
                    "description": t["description"]
                } for t in timeline], indent=2))
            else:
                print_timeline(timeline, deadline_date)
        except ValueError:
            print(f"Error: Invalid date format. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
