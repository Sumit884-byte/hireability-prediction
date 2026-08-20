# Hireability Index

A personalized **Hireability Probability Score** that fuses three signals no single consumer tool combines today:

1. **Job demand** — live remote job postings (skills, titles, descriptions)
2. **Layoff supply** — macro layoff headcounts and company-level events
3. **Your profile** — weighted skill vector from YAML or resume text

The score combines three layers:

```
final score = market_fit × experience_multiplier × employer_multiplier × readiness_multiplier
```

### The 30/90 rule (time-lag paradox)

Supply (layoffs) and demand (job posts) move on different clocks. The engine avoids treating them as simultaneous point-in-time equals:

| Window | Purpose |
|---|---|
| **30-day rolling sum** | Current market state (dampens single-day spikes) |
| **90-day baseline** | Historical normalizer from the prior 90 days (shifted back 30d) |

```
relative_supply_shock    = supply_30d / (baseline_daily_supply × 30)
relative_demand_strength = demand_30d / (baseline_daily_demand × 30)
skill_ratio              = relative_demand / relative_supply
```

Monthly layoffs.fyi history is spread into daily rates so macro supply does not spike on a single calendar day.

### Solving the data depth problem

Job APIs only return recent postings (~16 days). Demand history is seeded from **Indeed Hiring Lab** (US Software Development index, daily since 2020) and stored in `market_daily`:

```bash
# Seed 2 years of demand history + rebuild daily timeline
python main.py ingest history

# Full pipeline (jobs + layoffs + history rebuild)
python main.py ingest all
```

This gives the 90-day baseline real seasonal context (winter hiring freezes vs January spikes) instead of dividing by near-zero.

Export the training matrix (with forward-shifted T+30 targets):

```bash
python scripts/engineer_market_features.py
```

- **Experience** — years of experience adjust the score (early career 0.88×, senior 1.06–1.10×)
- **Employer pedigree** — tier-1 employers like Google/Meta boost hireability (1.15×)
- **Learning readiness** — students have less bandwidth to upskill (0.90–0.96×); degree holders with jobs can pivot faster (up to 1.06×)

## Database browser

Browse all SQLite tables in your browser (read-only):

```bash
pip install -r requirements.txt   # includes Flask
python scripts/db_browser.py
# open http://127.0.0.1:5050
```

Tabs: **Overview**, **Job posts**, **Layoff events**, **Market daily**, **Job sightings** (hiring lag). Search and pagination included.

### Job description translation

Non-English postings (common on Arbeitnow, etc.) are **auto-translated to English** on ingest using free Google Translate (`deep-translator`). Original text is kept in `description_original` / `title_original`.

```bash
# Backfill existing DB rows
python scripts/translate_jobs.py --dry-run
python scripts/translate_jobs.py

# Disable translation
export HIREABILITY_TRANSLATE=0
```

## Quick start

```bash
cd "hirebility prediction"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Seed 2yr Indeed demand history (first-time setup)
python main.py ingest history

# Fetch live layoffs + jobs and rebuild market_daily
python main.py ingest all

# Optional: auto-ingest once per day on desktop login
bash scripts/install_login.sh

# Score the example profile
python main.py score --profile profile.example.yaml

# Score directly from a PDF resume
python main.py score --profile /path/to/resume.pdf
```

## Daily ingest on login

Runs automatically when you log in (once per day). Good for laptops that shut down often — no missed fixed-time cron windows.

```bash
# One-time install (writes ~/.config/autostart/hireability-ingest.desktop)
bash scripts/install_login.sh

# Manual run (forces ingest even if already ran today)
python scripts/daily_ingest.py

# Login-style run (skip if today's ingest already succeeded)
python scripts/daily_ingest.py --if-due

# Check thresholds without fetching
python scripts/daily_ingest.py --dry-run
```

| Behavior | Detail |
|---|---|
| Trigger | Desktop login via `scripts/login_ingest.sh` (background, non-blocking) |
| Once per day | `--if-due` skips if `data/cron_state.json` shows a successful run today |
| Retry on failure | Failed runs do not count — next login retries |
| Uninstall | Delete `~/.config/autostart/hireability-ingest.desktop` |

**Sufficiency checks** (all must pass; thresholds in `hireability/config.py`):

| Check | Threshold | Config key |
|---|---|---|
| Job posts | ≥ 200 unique | `MIN_JOB_POSTS` |
| Layoff events | ≥ 30 | `MIN_LAYOFF_EVENTS` |
| Market timeline | ≥ 120 days (30 + 90 windows) | `BASELINE_WINDOW_DAYS` + `CURRENT_WINDOW_DAYS` |
| Live scrape depth | ≥ 30 days with daily job scrapes | `MIN_SCRAPED_DAYS` |

When all checks pass, you get a one-time **“data sufficient”** desktop notification. Weekly progress popups run until then. Failures always notify.

**Logs & state**

| Path | Purpose |
|---|---|
| `data/daily_ingest.log` | Structured run log |
| `data/login.log` | Autostart stdout/stderr |
| `data/cron_state.json` | Last run time, sufficiency milestone, metrics |

**Optional env vars**

```bash
export HIREABILITY_NOTIFY_DESKTOP=0              # log only, no notify-send
export HIREABILITY_NOTIFY_WEBHOOK="https://..."  # Discord/Slack webhook URL
```

**Alternative:** `scripts/install_cron.sh` installs a fixed 06:30 cron job for always-on machines. `install_login.sh` removes it if present.

## CLI

| Command | Description |
|---|---|
| `python main.py ingest all` | Fetch layoffs + jobs, rebuild `market_daily` |
| `python main.py ingest history` | Seed ~2yr Indeed demand history only |
| `python main.py ingest layoffs` | Layoffs only |
| `python main.py ingest jobs` | Jobs only (all 5 sources) |
| `python main.py ingest jobs --sources remotive,remoteok` | Selected job sources |
| `python main.py ingest jobs --himalayas-pages 10` | More Himalayas pages (20 jobs/page) |
| `python main.py ingest jobs --arbeitnow-pages 10` | More Arbeitnow pages (100 jobs/page) |
| `python main.py score --profile profile.yaml` | Compute hireability |
| `python main.py score --profile resume.pdf` | Score from PDF resume |
| `python main.py score --window 30` | Trend comparison window (days) |
| `python main.py status` | Layoff events/headcount, job counts by source, market timeline |
| `python main.py dedupe-jobs` | Audit content-hash duplicate jobs |
| `python main.py dedupe-jobs --fix` | Remove duplicates (keep oldest) |
| `python main.py dedupe-jobs --dry-run` | Preview `--fix` without deleting |

## Scripts

| Script | Description |
|---|---|
| `scripts/daily_ingest.py` | Full ingest + sufficiency checks + notifications |
| `scripts/login_ingest.sh` | Background wrapper for autostart (`--if-due`) |
| `scripts/install_login.sh` | Install desktop autostart (recommended) |
| `scripts/install_cron.sh` | Install fixed-time cron (always-on servers) |
| `scripts/engineer_market_features.py` | Export `data/market_features.csv` training matrix |
| `scripts/check_job_duplicates.py` | Standalone duplicate audit/`--fix` utility |
| `scripts/db_browser.py` | Local web UI to browse `hireability.db` |
| `scripts/translate_jobs.py` | Backfill English translations for non-English jobs |

## How scoring works

```
demand(skill) = Σ job_post_matches(skill) × work_mode_fit × degree_fit × time_decay
supply(skill) = Σ layoff_headcount(skill) × time_decay
ratio(skill)  = relative_demand_30d / relative_supply_30d  (30/90 baseline)
score         = weighted_avg(ratio) → logistic map → 0–100%
final         = market_fit × experience × employer_pedigree × readiness
```

- **Demand** is extracted from job tags, titles, and descriptions across all 5 sources.
- **Work mode fit** weights each job by how well it matches your `work_preference` (remote / on-site / hybrid / any). On-site jobs count fully for on-site seekers; remote board posts count lightly. Hybrid profiles get partial credit for both.
- **Degree fit** parses education requirements from job text (BSc, MSc, PhD, “degree required”) and weights demand by whether your `degree_level` meets the bar. Pursuing the required degree counts, but below holding it; not pursuing at all counts far less.
- **Degree field fit** weights each job by how well your specialization (`degree_field`) matches the job domain. A Master's in AI boosts AI/ML roles more than unrelated fields; related fields (e.g. AI ↔ data science) get partial credit.
- **Probable salary** blends role/location benchmarks with pay data scraped from Glassdoor, Internshala stipends, RemoteOK, and salary text in descriptions.
- **Supply** distributes layoff headcount across skills inferred from industry (e.g. fintech → Python, Java, security).
- **Profile weights** control which skills matter most for your score.

### Market outlook (GOOD / BAD / WORSE)

Every score includes a plain three-way verdict from **market fit** (your skills vs demand/supply) and **saturation ratio** (layoffs ÷ job posts — lower is better):

| Signal | GOOD | BAD | WORSE |
|---|---|---|---|
| Market fit | ≥ 58% | 42–58% | < 42% |
| Saturation ratio | < 6× | 6–18× | ≥ 18× |

**Both** signals must be healthy for **GOOD**. If either is weak → **BAD**. If either is **WORSE** → overall **WORSE**.

### Recruitment window (empirical hiring lag)

Job posts are not one-day events. Each ingest records a **sighting** in `job_sightings`; `first_seen` / `last_seen` on each job build true open duration:

| Data | Source |
|---|---|
| `first_seen` / `last_seen` | Updated every ingest when the same job reappears |
| `job_sightings` | One row per job per calendar day observed live |
| Per-source median / p90 lag | Computed from observed open days (falls back to 45d until enough data) |

Scoring uses **per-job windows** from empirical lag when available:

- Window starts at `first_seen` (true observation), not just API `posted_date`
- Duration = source **p90 hiring lag** from sightings (min 14d, max 90d)
- Jobs seen on 2+ days use their **observed open span** as a floor
- Demand spreads across the window; weight fades as employers screen more candidates

```
Hiring lag (true data): empirical median 32d (p90 48d, n=414)
Active recruitment: 414 roles (avg 38d window, 12% through cycle)
```

**Build true lag:** run daily login ingest — each day adds sightings. `python main.py status` shows per-source median/p90 once ≥5 jobs have multi-day sightings.

Config fallback: `RECRUITMENT_DURATION_DAYS`, `RECRUITMENT_COMPETITION_RAMP` in `hireability/config.py`.

```
========================================================
  HIREABILITY SCORE: 77.2%
  MARKET OUTLOOK: WORSE  |  Trend: IMPROVING
  Weak fit or heavy layoff saturation… (market fit 65%, saturation 43.3×).
========================================================
```

| Preference | Remote job | Hybrid job | On-site job |
|---|---|---|---|
| `remote` | 100% | 60% | 15% |
| `hybrid` | 60% | 100% | 50% |
| `on_site` | 15% | 50% | 100% |
| `any` | 100% | 100% | 100% |

Most ingested boards skew remote — on-site seekers will see lower demand scores and a lower “% of jobs match” in the output. That reflects the current data pool, not a penalty on the candidate.

**Learning readiness** reflects how quickly someone can close skill gaps:

| Profile | Multiplier | Rationale |
|---|---|---|
| Student | 0.90× | Less time to learn new skills while studying |
| Student + prior degree | 0.93× | Post-grad student with completed undergrad |
| Student + work experience | 0.94× | Intern/part-time while studying |
| Degree + employed | 1.06× | Can upskill in weeks/months; credential + job signal |
| Degree holder | 1.04× | Completed degree, not currently studying |
| Working professional | 1.02× | Employed, no completed degree detected |
| Default | 1.00× | No student/degree/work signals |

Set explicitly in YAML (`is_student`, `has_degree`) or auto-detected from PDF education sections.

**Degree fit** (demand weight per job vs your education):

| Situation | Demand weight |
|---|---|
| Job has no stated requirement | 100% |
| Completed degree meets bar | 100% |
| **Pursuing the exact required degree** (e.g. B.Tech student for BSc role) | **82%** |
| Pursuing one level below (e.g. bachelor's student for master's role) | 72% |
| One level below, not pursuing | 40% |
| Student, no clear degree path on profile | 50% |
| Not pursuing, far below bar | 15% |

Detected from job title/description: `BSc`, `B.Tech`, `Bachelor's`, `MSc`, `MBA`, `PhD`, `degree required`, etc.

**Degree field fit** (demand weight per job vs your specialization):

Set `degree_field` in YAML or let it infer from education text / role. Supported values: `ai`, `data_science`, `computer_science`, `software_engineering`, `business`, `design`, `cybersecurity`, `general`.

| Match | Master's | Bachelor's | PhD |
|---|---|---|---|
| Exact field (e.g. AI degree → ML job) | **112%** | 106% | 115% |
| Related field (e.g. AI → data science job) | 105% | 105% | 105% |
| Unrelated field | 86% | 86% | 86% |
| Job or profile is `general` | 100% | 100% | 100% |

Job domain is inferred from title/description (e.g. “machine learning”, “data scientist”, “software engineer”). Score output shows your field and `% of jobs match field`.

Example: same skills and `degree_level: master`, but `degree_field: ai` vs `business` — AI specialization matches ~89% of jobs in the pool vs ~21% for business, and the overall score reflects that boost.

## Data sources

### Job demand (8 sources)

| Source | Method | Typical volume | Notes |
|---|---|---|---|
| Remotive | Public API | ~30 posts | Remote-first |
| Arbeitnow | Public API | ~100 posts | EU / multilingual |
| RemoteOK | Public API | ~100 posts | Includes salary when listed |
| Jobicy | Public API | ~100 posts | Remote |
| Himalayas | Public API | 100 posts | 5 pages × 20 |
| **LinkedIn** | Guest jobs API + detail fetch | ~75 posts | India/US keyword search; descriptions from detail API |
| **Internshala** | HTML listing parse | ~180 posts | Internships + stipends (India) |
| **Glassdoor** | HTML + embedded salary JSON | ~30–90 posts | Salary ranges when present; may block without browser headers |

```bash
# All sources (default) — includes LinkedIn, Internshala, Glassdoor
python main.py ingest jobs

# API-only (faster, no HTML scraping)
python main.py ingest jobs --sources remotive,remoteok,jobicy

# India-focused boards
python main.py ingest jobs --sources linkedin,internshala

# Fetch more Himalayas pages (20 jobs each)
python main.py ingest jobs --himalayas-pages 10
```

**Scraping notes:** LinkedIn/Internshala/Glassdoor use polite delays (`SCRAPE_REQUEST_DELAY_SEC` in `config.py`). Glassdoor can return 403 in some environments — ingest logs a warning and continues. Tune `LINKEDIN_SEARCH_KEYWORDS`, `LINKEDIN_SEARCH_LOCATION`, and `INTERNSHALA_SEARCH_SLUGS` in config for your market.

### Probable salary range

`python main.py score` estimates a pay band from your profile and scraped salary data:

| Signal | Effect |
|---|---|
| Location | India (LPA / monthly stipend) vs US vs global remote |
| Role + `degree_field` | Software, AI, data science, design, business benchmarks |
| Experience / student | Seniority bracket; students → stipend range in India |
| Degree level | Master's/PhD nudge toward upper band |
| Employer tier | Tier-1 pedigree widens range upward |
| Comparable job salaries | Glassdoor, Internshala stipends, RemoteOK, parsed description ranges |

Output example: `Probable salary: ₹12.0–18.5 LPA (medium confidence; 8 comparable jobs with pay data)`.

Benchmark tables live in `data/salary_benchmarks.json`; salary text is parsed on ingest into `salary_min` / `salary_max` columns (visible in `scripts/db_browser.py`).

### Layoff supply

| Source | Endpoint | Signal |
|---|---|---|
| Layoffs.fyi | `layoffsfyi-production.up.railway.app/api/chart-data` | Monthly layoff headcounts |
| Seed data | `data/seed_layoffs.json` | Recent named company events |

### Demand history (baseline depth)

| Source | Endpoint | Signal |
|---|---|---|
| Indeed Hiring Lab | `hiring-lab/data` US Software Development CSV | Daily demand index since 2020, seeded into `market_daily` |

Live job scrapes overlay recent days; Indeed seed fills the 90-day baseline when APIs only return ~2 weeks of posts.

## Project structure

```
hireability/
├── config.py       # URLs, windows, sufficiency thresholds
├── storage.py      # SQLite persistence (content-hash dedup)
├── cron/           # login ingest state, sufficiency checks, notifications
├── scrapers/       # jobs, layoffs, Indeed demand history
├── market/         # market_daily rebuild + supply spreading
├── jobs/           # work-mode + degree-requirement classification, dedup
├── normalizer/     # canonical skills + fuzzy matching
├── profile/        # YAML + PDF resume parsing
└── scoring/        # timeseries 30/90 engine, pedigree multipliers

scripts/            # daily_ingest, login install, feature export
data/
├── hireability.db          # SQLite (gitignored)
├── canonical_skills.json   # skill taxonomy
├── company_tiers.json      # employer pedigree tiers
├── seed_layoffs.json       # bundled layoff events
├── cron_state.json         # ingest run state (gitignored)
├── daily_ingest.log        # run log (gitignored)
└── login.log               # autostart log (gitignored)
```

## Dependencies

```
requests, rapidfuzz, PyYAML, python-dateutil, pypdf, pandas, flask, deep-translator, langdetect
```

Desktop notifications use `notify-send` (Linux) when available; no extra Python package required.

## Profile format

### PDF resume (auto-parsed)

Pass any text-based PDF resume directly:

```bash
python main.py score --profile ~/Documents/Sumit_Mishra.pdf
```

The parser extracts:
- Name, role, and location from the header
- Skills from the full document, with extra weight on the Technical Skills section
- Work preference from location (`Remote` → remote) or summary phrases (“seeking remote role”)
- Student status and completed degree from the Education section (“pursuing”, “expected graduation”, degree titles)

### YAML profile (manual)

```yaml
name: Alex Developer
role: Backend Engineer
location: Remote
work_preference: remote  # remote | on_site | hybrid | any
is_student: false
has_degree: true
degree_level: bachelor  # none | associate | bachelor | master | doctorate
experience_years: 4
current_company: Google
employers:
  - Google
  - Stripe
skills:
  - name: Python
    weight: 1.0
  - name: FastAPI
    weight: 0.9
```

`work_preference` controls which jobs count toward demand. `degree_level` + `is_student` control degree-fit weighting on each job. `is_student` / `has_degree` control the learning readiness multiplier. All can be inferred from a PDF if omitted.

## What makes this different

- **Not** a static ATS matcher (resume vs one JD)
- **Not** an enterprise B2B skills index
- **Not** a macro layoff tracker alone

It is a **dynamic, individual-facing market saturation dashboard** — the open gap between those three categories.
