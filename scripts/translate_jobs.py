#!/usr/bin/env python3
"""Backfill English translations for job posts already in the database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hireability.config import DB_PATH
from hireability.jobs.translate import localize_job_text, needs_translation
from hireability.storage import _connect, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate non-English jobs in hireability.db")
    parser.add_argument("--dry-run", action="store_true", help="Report only, do not update")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, description, title_original, description_original
            FROM job_posts
            ORDER BY id ASC
            """
        ).fetchall()

    candidates = []
    for row in rows:
        title = row["title_original"] or row["title"]
        description = row["description_original"] or row["description"]
        if needs_translation(title) or needs_translation(description):
            candidates.append(row)

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Found {len(candidates)} jobs needing translation (of {len(rows)} total).")
    if args.dry_run or not candidates:
        return 0

    updated = 0
    with _connect() as conn:
        for row in candidates:
            source_title = row["title_original"] or row["title"]
            source_description = row["description_original"] or row["description"]
            title_en, desc_en, title_original, description_original = localize_job_text(
                title=source_title,
                description=source_description,
            )
            conn.execute(
                """
                UPDATE job_posts
                SET title = ?, description = ?,
                    title_original = ?, description_original = ?
                WHERE id = ?
                """,
                (
                    title_en,
                    desc_en,
                    title_original or source_title,
                    description_original or source_description,
                    row["id"],
                ),
            )
            updated += 1
            print(f"  [{updated}] {source_title[:60]} → {title_en[:60]}")

    print(f"Updated {updated} jobs in {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
