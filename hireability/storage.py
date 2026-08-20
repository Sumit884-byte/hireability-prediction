import sqlite3
from datetime import date, datetime
from pathlib import Path

from hireability.config import DB_PATH
from hireability.jobs.dedup import dedupe_job_posts, job_fingerprint
from hireability.models import JobPost, LayoffEvent


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _migrate_job_posts(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "job_posts")
    if "content_hash" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN content_hash TEXT")
    if "first_seen" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN first_seen TEXT")
    if "last_seen" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN last_seen TEXT")
    if "title_original" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN title_original TEXT")
    if "description_original" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN description_original TEXT")
    if "salary_min" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN salary_min REAL")
    if "salary_max" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN salary_max REAL")
    if "salary_currency" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN salary_currency TEXT DEFAULT ''")
    if "salary_period" not in columns:
        conn.execute("ALTER TABLE job_posts ADD COLUMN salary_period TEXT DEFAULT ''")

    rows = conn.execute(
        "SELECT id, title, company, description, content_hash FROM job_posts ORDER BY id ASC"
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        fp = job_fingerprint(row["title"], row["company"], row["description"])
        if fp in seen:
            conn.execute("DELETE FROM job_posts WHERE id = ?", (row["id"],))
            continue
        seen.add(fp)
        if row["content_hash"] != fp:
            conn.execute(
                "UPDATE job_posts SET content_hash = ? WHERE id = ?",
                (fp, row["id"]),
            )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posts_content_hash
        ON job_posts(content_hash)
        """
    )

    conn.execute(
        """
        UPDATE job_posts
        SET first_seen = COALESCE(first_seen, posted_date),
            last_seen = COALESCE(last_seen, posted_date)
        WHERE first_seen IS NULL OR last_seen IS NULL
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO job_sightings (content_hash, sighting_date, source)
        SELECT content_hash, posted_date, source
        FROM job_posts
        WHERE content_hash IS NOT NULL
        """
    )


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS layoff_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                event_date TEXT NOT NULL,
                headcount INTEGER NOT NULL,
                industry TEXT DEFAULT 'Technology',
                country TEXT DEFAULT '',
                source TEXT DEFAULT '',
                ingested_at TEXT NOT NULL,
                UNIQUE(company, event_date, headcount, source)
            );

            CREATE TABLE IF NOT EXISTS job_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                posted_date TEXT NOT NULL,
                description TEXT NOT NULL,
                tags TEXT DEFAULT '',
                category TEXT DEFAULT '',
                location TEXT DEFAULT '',
                source TEXT DEFAULT '',
                url TEXT DEFAULT '',
                content_hash TEXT,
                ingested_at TEXT NOT NULL,
                UNIQUE(url, source)
            );

            CREATE TABLE IF NOT EXISTS market_daily (
                date TEXT PRIMARY KEY,
                layoff_headcount REAL NOT NULL DEFAULT 0,
                job_postings REAL NOT NULL DEFAULT 0,
                demand_index REAL,
                scraped_posts REAL NOT NULL DEFAULT 0,
                source TEXT DEFAULT '',
                ingested_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_layoffs_date ON layoff_events(event_date);
            CREATE INDEX IF NOT EXISTS idx_jobs_date ON job_posts(posted_date);

            CREATE TABLE IF NOT EXISTS job_sightings (
                content_hash TEXT NOT NULL,
                sighting_date TEXT NOT NULL,
                source TEXT DEFAULT '',
                PRIMARY KEY (content_hash, sighting_date)
            );
            CREATE INDEX IF NOT EXISTS idx_job_sightings_date ON job_sightings(sighting_date);
            """
        )
        _migrate_job_posts(conn)
        conn.commit()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def save_layoffs(events: list[LayoffEvent], db_path: Path = DB_PATH) -> int:
    init_db(db_path)
    ingested_at = _now_iso()
    inserted = 0
    with _connect(db_path) as conn:
        for event in events:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO layoff_events
                (company, event_date, headcount, industry, country, source, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.company,
                    event.event_date.isoformat(),
                    event.headcount,
                    event.industry,
                    event.country,
                    event.source,
                    ingested_at,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def save_jobs(posts: list[JobPost], db_path: Path = DB_PATH) -> int:
    from hireability.jobs.salary_parse import salary_from_job_text
    from hireability.jobs.translate import localize_job_text

    init_db(db_path)
    posts, batch_dupes = dedupe_job_posts(posts)
    if batch_dupes:
        print(f"Skipped {batch_dupes} duplicate jobs in ingest batch.")

    ingested_at = _now_iso()
    today = date.today().isoformat()
    inserted = 0
    updated = 0
    translated = 0

    with _connect(db_path) as conn:
        for post in posts:
            raw_title = post.title
            raw_description = post.description
            content_hash = job_fingerprint(raw_title, post.company, raw_description)

            title_en, desc_en, title_original, description_original = localize_job_text(
                title=raw_title,
                description=raw_description,
            )
            if title_original or description_original:
                translated += 1

            salary_min = post.salary_min
            salary_max = post.salary_max
            salary_currency = post.salary_currency or ""
            salary_period = post.salary_period or ""
            if salary_min is None or salary_max is None:
                parsed = salary_from_job_text(title_en, desc_en)
                if parsed:
                    salary_min = parsed.salary_min
                    salary_max = parsed.salary_max
                    salary_currency = parsed.currency
                    salary_period = parsed.period

            existing = conn.execute(
                "SELECT id FROM job_posts WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE job_posts
                    SET last_seen = ?, ingested_at = ?, posted_date = ?, url = ?,
                        title = ?, description = ?,
                        title_original = COALESCE(title_original, ?),
                        description_original = COALESCE(description_original, ?),
                        salary_min = COALESCE(?, salary_min),
                        salary_max = COALESCE(?, salary_max),
                        salary_currency = COALESCE(NULLIF(?, ''), salary_currency),
                        salary_period = COALESCE(NULLIF(?, ''), salary_period)
                    WHERE content_hash = ?
                    """,
                    (
                        today,
                        ingested_at,
                        post.posted_date.isoformat(),
                        post.url,
                        title_en,
                        desc_en,
                        title_original,
                        description_original,
                        salary_min,
                        salary_max,
                        salary_currency,
                        salary_period,
                        content_hash,
                    ),
                )
                updated += 1
            else:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO job_posts
                    (title, company, posted_date, description, tags, category,
                     location, source, url, content_hash, first_seen, last_seen,
                     title_original, description_original,
                     salary_min, salary_max, salary_currency, salary_period,
                     ingested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title_en,
                        post.company,
                        post.posted_date.isoformat(),
                        desc_en,
                        ",".join(post.tags),
                        post.category,
                        post.location,
                        post.source,
                        post.url,
                        content_hash,
                        today,
                        today,
                        title_original,
                        description_original,
                        salary_min,
                        salary_max,
                        salary_currency,
                        salary_period,
                        ingested_at,
                    ),
                )
                inserted += cursor.rowcount

            conn.execute(
                """
                INSERT OR IGNORE INTO job_sightings (content_hash, sighting_date, source)
                VALUES (?, ?, ?)
                """,
                (content_hash, today, post.source),
            )

    if inserted or updated:
        try:
            from hireability.jobs.hiring_lag import cached_hiring_lag_model

            cached_hiring_lag_model.cache_clear()
        except ImportError:
            pass

    if translated:
        print(f"Translated {translated} non-English job postings to English (free).")
    if updated:
        print(f"Updated {updated} existing jobs (last_seen + hiring lag sighting).")
    return inserted


def load_layoffs(since: date | None = None, db_path: Path = DB_PATH) -> list[LayoffEvent]:
    init_db(db_path)
    query = "SELECT * FROM layoff_events"
    params: tuple = ()
    if since:
        query += " WHERE event_date >= ?"
        params = (since.isoformat(),)
    query += " ORDER BY event_date DESC"

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        LayoffEvent(
            company=row["company"],
            event_date=date.fromisoformat(row["event_date"]),
            headcount=row["headcount"],
            industry=row["industry"] or "Technology",
            country=row["country"] or "",
            source=row["source"] or "",
        )
        for row in rows
    ]


def load_jobs(since: date | None = None, db_path: Path = DB_PATH) -> list[JobPost]:
    init_db(db_path)
    query = "SELECT * FROM job_posts"
    params: tuple = ()
    if since:
        query += " WHERE posted_date >= ?"
        params = (since.isoformat(),)
    query += " ORDER BY posted_date DESC"

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        sighting_rows = conn.execute(
            """
            SELECT content_hash, COUNT(DISTINCT sighting_date) AS sighting_days
            FROM job_sightings
            GROUP BY content_hash
            """
        ).fetchall()

    posts = []
    sighting_days = {row["content_hash"]: int(row["sighting_days"]) for row in sighting_rows}

    for row in rows:
        first_seen = row["first_seen"] if row["first_seen"] else None
        last_seen = row["last_seen"] if row["last_seen"] else None
        content_hash = row["content_hash"] or ""
        title_original = row["title_original"] if "title_original" in row.keys() else None
        description_original = (
            row["description_original"] if "description_original" in row.keys() else None
        )
        salary_min = row["salary_min"] if "salary_min" in row.keys() else None
        salary_max = row["salary_max"] if "salary_max" in row.keys() else None
        posts.append(
            JobPost(
                title=row["title"],
                company=row["company"],
                posted_date=date.fromisoformat(row["posted_date"]),
                description=row["description"],
                tags=[tag for tag in (row["tags"] or "").split(",") if tag],
                category=row["category"] or "",
                location=row["location"] or "",
                source=row["source"] or "",
                url=row["url"] or "",
                content_hash=content_hash,
                first_seen=date.fromisoformat(first_seen) if first_seen else None,
                last_seen=date.fromisoformat(last_seen) if last_seen else None,
                sighting_days=sighting_days.get(content_hash, 0),
                title_original=title_original,
                description_original=description_original,
                salary_min=float(salary_min) if salary_min is not None else None,
                salary_max=float(salary_max) if salary_max is not None else None,
                salary_currency=(row["salary_currency"] or "") if "salary_currency" in row.keys() else "",
                salary_period=(row["salary_period"] or "") if "salary_period" in row.keys() else "",
            )
        )
    unique_posts, _ = dedupe_job_posts(posts)
    return unique_posts


def counts(db_path: Path = DB_PATH) -> dict[str, int]:
    init_db(db_path)
    with _connect(db_path) as conn:
        layoff_row = conn.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(headcount), 0) AS headcount FROM layoff_events"
        ).fetchone()
        jobs = conn.execute("SELECT COUNT(*) AS c FROM job_posts").fetchone()["c"]
    return {
        "layoff_events": layoff_row["events"],
        "layoff_headcount": layoff_row["headcount"],
        "job_posts": jobs,
    }


def job_counts_by_source(db_path: Path = DB_PATH) -> dict[str, int]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT source, COUNT(*) AS c
            FROM job_posts
            GROUP BY source
            ORDER BY c DESC, source ASC
            """
        ).fetchall()
    return {row["source"] or "unknown": row["c"] for row in rows}
