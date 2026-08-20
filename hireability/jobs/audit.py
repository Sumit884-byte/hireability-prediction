from hireability.jobs.dedup import job_fingerprint
from hireability.storage import _connect, init_db, job_counts_by_source, load_jobs


def _row_fingerprint(row) -> str:
    return job_fingerprint(row["title"], row["company"], row["description"])


def audit_jobs(verbose: bool = False) -> dict:
    init_db()
    jobs = load_jobs()

    desc_lengths = [len(job.description or "") for job in jobs]
    tag_counts = [len(job.tags) for job in jobs]
    avg_desc = sum(desc_lengths) / len(desc_lengths) if desc_lengths else 0
    short_desc = sum(1 for length in desc_lengths if length < 120)

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, company, source, url, description, tags, posted_date
            FROM job_posts
            ORDER BY id ASC
            """
        ).fetchall()

    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(_row_fingerprint(row), []).append(row)

    duplicate_groups = {fp: items for fp, items in groups.items() if len(items) > 1}
    duplicate_rows = sum(len(items) - 1 for items in duplicate_groups.values())

    cross_source = sum(
        1 for items in duplicate_groups.values() if len({item["source"] for item in items}) > 1
    )

    report = {
        "total": len(rows),
        "unique_fingerprints": len(groups),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_rows": duplicate_rows,
        "cross_source_groups": cross_source,
        "avg_description_chars": round(avg_desc, 1),
        "short_descriptions": short_desc,
        "avg_tags": round(sum(tag_counts) / len(tag_counts), 1) if tag_counts else 0,
        "by_source": job_counts_by_source(),
    }

    print("Job data quality report")
    print("=" * 56)
    print(f"Total stored jobs:          {report['total']}")
    print(f"Unique content fingerprints: {report['unique_fingerprints']}")
    print(f"Duplicate groups:           {report['duplicate_groups']}")
    print(f"Redundant rows:             {report['duplicate_rows']}")
    print(f"Cross-source dup groups:    {report['cross_source_groups']}")
    print(f"Avg description length:     {report['avg_description_chars']} chars")
    print(f"Short descriptions (<120):  {report['short_descriptions']}")
    print(f"Avg tags per job:           {report['avg_tags']}")
    print()
    print("Jobs by source:")
    for source, count in report["by_source"].items():
        print(f"  - {source}: {count}")

    if duplicate_groups:
        print()
        print("Duplicate groups:")
        print("-" * 56)
        for index, (fp, items) in enumerate(duplicate_groups.items(), start=1):
            print(f"[{index}] fingerprint={fp[:12]}…  copies={len(items)}")
            for item in items:
                print(
                    f"    id={item['id']}  source={item['source']}  "
                    f"company={item['company'][:28]}  title={item['title'][:42]}"
                )
                if verbose:
                    print(f"      url={item['url']}")
    else:
        print()
        print("No duplicate job postings found.")

    return report


def remove_duplicates(dry_run: bool = False) -> int:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, company, source, url, description FROM job_posts ORDER BY id ASC"
        ).fetchall()

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(_row_fingerprint(row), []).append(row)

        to_delete: list[int] = []
        for items in groups.values():
            if len(items) < 2:
                continue
            to_delete.extend(item["id"] for item in items[1:])

        if not to_delete:
            print("Nothing to remove.")
            return 0

        print(f"Keeping {len(rows) - len(to_delete)} jobs, removing {len(to_delete)} duplicates.")
        if dry_run:
            print("Dry run only — no rows deleted.")
            return len(to_delete)

        conn.executemany("DELETE FROM job_posts WHERE id = ?", [(job_id,) for job_id in to_delete])
        conn.commit()

    print("Duplicate rows removed.")
    return len(to_delete)
