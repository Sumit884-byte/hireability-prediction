#!/usr/bin/env python3
"""Local web UI to browse the hireability SQLite database."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, abort, render_template_string, request, url_for

from hireability.config import DB_PATH
from hireability.jobs.hiring_lag import load_hiring_lag_model
from hireability.market.daily import market_daily_stats
from hireability.storage import _connect, counts, init_db, job_counts_by_source

app = Flask(__name__)

TABLES = {
    "jobs": {
        "title": "Job posts",
        "query": """
            SELECT id, title, company, source, posted_date, first_seen, last_seen,
                   location, url,
                   salary_min, salary_max, salary_currency, salary_period,
                   CASE WHEN description_original IS NOT NULL THEN 'translated' ELSE 'en' END AS lang,
                   substr(description, 1, 160) AS description_preview,
                   substr(description_original, 1, 80) AS original_preview
            FROM job_posts
            ORDER BY last_seen DESC, posted_date DESC
        """,
        "search_columns": ("title", "company", "source", "location"),
    },
    "layoffs": {
        "title": "Layoff events",
        "query": """
            SELECT id, company, event_date, headcount, industry, country, source
            FROM layoff_events
            ORDER BY event_date DESC
        """,
        "search_columns": ("company", "industry", "source"),
    },
    "market": {
        "title": "Market daily",
        "query": """
            SELECT date, layoff_headcount, job_postings, demand_index,
                   scraped_posts, source
            FROM market_daily
            ORDER BY date DESC
        """,
        "search_columns": ("date", "source"),
    },
    "sightings": {
        "title": "Job sightings (hiring lag)",
        "query": """
            SELECT s.content_hash, s.sighting_date, s.source,
                   j.title, j.company, j.first_seen, j.last_seen
            FROM job_sightings s
            LEFT JOIN job_posts j ON j.content_hash = s.content_hash
            ORDER BY s.sighting_date DESC, j.company ASC
        """,
        "search_columns": ("title", "company", "source", "content_hash"),
    },
}

BASE_STYLE = """
:root {
  --bg: #0f1419;
  --card: #1a2332;
  --text: #e7ecf3;
  --muted: #8b9cb3;
  --accent: #5b9fd4;
  --border: #2a3544;
}
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0;
  padding: 1.5rem;
  line-height: 1.45;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header { margin-bottom: 1.5rem; }
h1 { font-size: 1.5rem; margin: 0 0 0.25rem; }
.sub { color: var(--muted); font-size: 0.9rem; }
nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 1rem 0 1.25rem;
}
nav a {
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  background: var(--card);
  border: 1px solid var(--border);
}
nav a.active { border-color: var(--accent); color: var(--text); }
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem 1rem;
}
.card .label { color: var(--muted); font-size: 0.8rem; }
.card .value { font-size: 1.35rem; font-weight: 600; }
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 1rem;
}
input[type="search"] {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 0.45rem 0.65rem;
  border-radius: 6px;
  min-width: 220px;
}
button, .btn {
  background: var(--accent);
  color: #0b1118;
  border: none;
  padding: 0.45rem 0.85rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}
.table-wrap {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
th, td {
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
th {
  position: sticky;
  top: 0;
  background: #223044;
  color: var(--muted);
  font-weight: 600;
}
tr:hover td { background: rgba(91, 159, 212, 0.06); }
.pager {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-top: 1rem;
  color: var(--muted);
  font-size: 0.9rem;
}
.note { color: var(--muted); font-size: 0.85rem; margin-top: 0.5rem; }
"""

LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · Hireability DB</title>
  <style>{{ style }}</style>
</head>
<body>
  <header>
    <h1>Hireability database</h1>
    <div class="sub">{{ db_path }}</div>
  </header>
  <nav>
    <a href="{{ url_for('index') }}" class="{{ 'active' if page == 'home' else '' }}">Overview</a>
    {% for key, meta in tables.items() %}
    <a href="{{ url_for('browse_table', table=key) }}"
       class="{{ 'active' if page == key else '' }}">{{ meta.title }}</a>
    {% endfor %}
  </nav>
  {% block body %}{% endblock %}
</body>
</html>
"""

INDEX_TEMPLATE = LAYOUT.replace(
    "{% block body %}{% endblock %}",
    """
{% block body %}
<div class="cards">
  <div class="card"><div class="label">Job posts</div><div class="value">{{ stats.job_posts }}</div></div>
  <div class="card"><div class="label">Layoff events</div><div class="value">{{ stats.layoff_events }}</div></div>
  <div class="card"><div class="label">Layoff headcount</div><div class="value">{{ stats.layoff_headcount }}</div></div>
  <div class="card"><div class="label">Market days</div><div class="value">{{ market.total_days or 0 }}</div></div>
  <div class="card"><div class="label">Live scrape days</div><div class="value">{{ market.scraped_days or 0 }}</div></div>
  <div class="card"><div class="label">Multi-day sightings</div><div class="value">{{ lag_samples }}</div></div>
</div>
{% if by_source %}
<h2>Jobs by source</h2>
<div class="cards">
  {% for source, count in by_source.items() %}
  <div class="card"><div class="label">{{ source }}</div><div class="value">{{ count }}</div></div>
  {% endfor %}
</div>
{% endif %}
<p class="note">Read-only local viewer. Data updates when you run ingest or login autostart.</p>
{% endblock %}
""",
)

TABLE_TEMPLATE = LAYOUT.replace(
    "{% block body %}{% endblock %}",
    """
{% block body %}
<h2>{{ table_title }}</h2>
<form class="toolbar" method="get">
  <input type="search" name="q" value="{{ query }}" placeholder="Filter rows…">
  <button type="submit">Search</button>
  {% if query %}<a class="btn" href="{{ url_for('browse_table', table=table_key) }}">Clear</a>{% endif %}
  <span class="note">{{ total }} rows{% if query %} (filtered){% endif %}</span>
</form>
<div class="table-wrap">
  <table>
    <thead><tr>{% for col in columns %}<th>{{ col }}</th>{% endfor %}</tr></thead>
    <tbody>
      {% for row in rows %}
      <tr>{% for col in columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>
      {% else %}
      <tr><td colspan="{{ columns|length }}">No rows.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
<div class="pager">
  {% if page_num > 1 %}
  <a href="{{ prev_url }}">← Prev</a>
  {% endif %}
  <span>Page {{ page_num }} / {{ page_total }}</span>
  {% if page_num < page_total %}
  <a href="{{ next_url }}">Next →</a>
  {% endif %}
</div>
{% endblock %}
""",
)


def _fetch_rows(table_key: str, *, query_filter: str = "", limit: int = 50, offset: int = 0):
    meta = TABLES[table_key]
    base_sql = meta["query"].strip()
    params: list = []

    if query_filter:
        clauses = [f"CAST({col} AS TEXT) LIKE ?" for col in meta["search_columns"]]
        wrapped = f"SELECT * FROM ({base_sql}) AS t WHERE " + " OR ".join(clauses)
        params = [f"%{query_filter}%"] * len(meta["search_columns"])
        count_sql = f"SELECT COUNT(*) AS c FROM ({wrapped})"
        data_sql = wrapped + " LIMIT ? OFFSET ?"
    else:
        count_sql = f"SELECT COUNT(*) AS c FROM ({base_sql})"
        data_sql = base_sql + " LIMIT ? OFFSET ?"

    init_db()
    with _connect() as conn:
        total = conn.execute(count_sql, params).fetchone()["c"]
        rows = conn.execute(data_sql, params + [limit, offset]).fetchall()

    columns = rows[0].keys() if rows else []
    if not columns and query_filter:
        with _connect() as conn:
            probe = conn.execute(base_sql + " LIMIT 1").fetchone()
            columns = probe.keys() if probe else []

    formatted = []
    for row in rows:
        formatted.append(
            {
                key: html.escape(str(row[key] if row[key] is not None else ""))
                for key in row.keys()
            }
        )
    return list(columns), formatted, int(total)


def _page_url(table_key: str, page_num: int, query_filter: str) -> str:
    return url_for("browse_table", table=table_key, page=page_num, q=query_filter or None)


@app.route("/")
def index():
    stats = counts()
    market = market_daily_stats()
    lag = load_hiring_lag_model()
    return render_template_string(
        INDEX_TEMPLATE,
        title="Overview",
        style=BASE_STYLE,
        page="home",
        tables=TABLES,
        db_path=str(DB_PATH),
        stats=stats,
        market=market,
        by_source=job_counts_by_source(),
        lag_samples=lag.global_profile.sample_size,
    )


@app.route("/table/<table>")
def browse_table(table: str):
    if table not in TABLES:
        abort(404)

    query_filter = request.args.get("q", "").strip()
    page_num = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page_num - 1) * per_page

    columns, rows, total = _fetch_rows(
        table,
        query_filter=query_filter,
        limit=per_page,
        offset=offset,
    )
    page_total = max(1, (total + per_page - 1) // per_page)
    page_num = min(page_num, page_total)

    return render_template_string(
        TABLE_TEMPLATE,
        title=TABLES[table]["title"],
        style=BASE_STYLE,
        page=table,
        tables=TABLES,
        db_path=str(DB_PATH),
        table_key=table,
        table_title=TABLES[table]["title"],
        columns=columns,
        rows=rows,
        total=total,
        query=html.escape(query_filter),
        page_num=page_num,
        page_total=page_total,
        prev_url=_page_url(table, page_num - 1, query_filter),
        next_url=_page_url(table, page_num + 1, query_filter),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Browse hireability.db in the browser")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run: python main.py ingest all")
        return 1

    print(f"Database viewer: http://{args.host}:{args.port}")
    print(f"Reading: {DB_PATH}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
