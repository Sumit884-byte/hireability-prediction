from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "hireability.db"
SKILLS_PATH = DATA_DIR / "canonical_skills.json"
SEED_LAYOFFS_PATH = DATA_DIR / "seed_layoffs.json"

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
ARBEITNOW_API_URL = "https://arbeitnow.com/api/job-board-api"
REMOTEOK_API_URL = "https://remoteok.com/api"
JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
HIMALAYAS_API_URL = "https://himalayas.app/jobs/api"

JOB_SOURCES = (
    "remotive",
    "arbeitnow",
    "remoteok",
    "jobicy",
    "himalayas",
    "linkedin",
    "internshala",
    "glassdoor",
)
HIMALAYAS_PAGE_SIZE = 20
HIMALAYAS_MAX_PAGES = 5

LAYOFFS_CHART_API = "https://layoffsfyi-production.up.railway.app/api/chart-data"
LAYOFFS_ANNUAL_API = "https://layoffsfyi-production.up.railway.app/api/annual-stats"
INDEED_SOFTWARE_CSV = (
    "https://raw.githubusercontent.com/hiring-lab/data/master/US/"
    "job_postings_by_sector_US.csv"
)

ARBEITNOW_MAX_PAGES = 10
MARKET_HISTORY_DAYS = 730

# Time-lag paradox windows (see scoring/timeseries.py).
CURRENT_WINDOW_DAYS = 30       # rolling sum: immediate market state
BASELINE_WINDOW_DAYS = 90      # historical daily average for normalization
HISTORY_DAYS = 180             # minimum lookback for baseline context
FORECAST_HORIZON_DAYS = 30     # target shift for training (T -> T+30)
SUPPLY_EPSILON = 1.0
MAX_RELATIVE_RATIO = 5.0       # cap when baseline history is sparse
MIN_RELATIVE_RATIO = 0.2

# Legacy alias used by CLI --window flag.
LOOKBACK_DAYS = CURRENT_WINDOW_DAYS

# Typical days a role stays open while employers screen candidates.
RECRUITMENT_DURATION_DAYS = 45
# How much demand weight fades by end of cycle (0.55 → day-45 posting ≈ 45% of day-0).
RECRUITMENT_COMPETITION_RAMP = 0.55

USER_AGENT = (
    "HireabilityIndex/0.1 (+https://github.com; personal market research tool)"
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LINKEDIN_JOBS_API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"
LINKEDIN_SEARCH_KEYWORDS = "software engineer"
LINKEDIN_SEARCH_LOCATION = "India"
LINKEDIN_MAX_RESULTS = 75
LINKEDIN_MAX_DETAILS = 30

INTERNSHALA_BASE_URL = "https://internshala.com"
INTERNSHALA_SEARCH_SLUGS = (
    "python-internship",
    "data-science-internship",
    "software-development-internship",
    "machine-learning-internship",
)
INTERNSHALA_MAX_PAGES = 2

GLASSDOOR_SEARCH_TERMS = ("software engineer", "data scientist", "machine learning engineer")
GLASSDOOR_MAX_PAGES = 1

SCRAPE_REQUEST_DELAY_SEC = 0.6

# Daily cron sufficiency thresholds (see hireability/cron/sufficiency.py).
MIN_JOB_POSTS = 200
MIN_LAYOFF_EVENTS = 30
MIN_SCRAPED_DAYS = 30

CRON_STATE_PATH = DATA_DIR / "cron_state.json"
CRON_LOG_PATH = DATA_DIR / "daily_ingest.log"
