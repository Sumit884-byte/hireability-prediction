#!/usr/bin/env python3
"""Audit and remove duplicate job postings from the hireability database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hireability.jobs.audit import audit_jobs, remove_duplicates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and deduplicate identical job postings in the hireability database.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Delete redundant rows, keeping the oldest copy of each job",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what --fix would delete without changing the database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print URLs for duplicate rows",
    )
    args = parser.parse_args()

    if args.fix or args.dry_run:
        remove_duplicates(dry_run=args.dry_run)
        print()

    audit_jobs(verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
