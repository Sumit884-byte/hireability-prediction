#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from hireability.config import ROOT_DIR
from hireability.jobs.degree_field import field_label
from hireability.jobs.degree_requirements import degree_level_label
from hireability.jobs.work_mode import preference_label
from hireability.jobs.hiring_lag import load_hiring_lag_model
from hireability.scoring.verdict import VERDICT_LABELS
from hireability.normalizer.skills import SkillNormalizer
from hireability.profile.parser import load_profile
from hireability.scoring.engine import compute_hireability
from hireability.config import JOB_SOURCES
from hireability.scrapers.jobs import fetch_jobs_by_source
from hireability.scrapers.layoffs import fetch_layoffs
from hireability.market.daily import market_daily_stats, rebuild_market_daily
from hireability.storage import counts, init_db, job_counts_by_source, load_jobs, load_layoffs, save_jobs, save_layoffs


def _print_score(result) -> None:
    print()
    print("=" * 56)
    print(f"  HIREABILITY SCORE: {result.score}%")
    print(
        f"  MARKET OUTLOOK: {VERDICT_LABELS.get(result.market_verdict, result.market_verdict.upper())}"
        f"  |  Trend: {result.trend.upper()}  |  Window: {result.window_days} days"
    )
    if result.market_verdict_detail:
        print(f"  {result.market_verdict_detail}")
    print("=" * 56)
    print(result.summary)
    print()
    print("Score composition:")
    print("-" * 56)
    print(f"  Market fit (skills vs demand/supply): {result.market_score}%")
    if result.experience_label == "project-based (no work history)":
        print(
            f"  Experience: project/education only (no work history) "
            f"→ ×{result.experience_multiplier:.2f}"
        )
    elif result.experience_years > 0:
        print(
            f"  Experience: {result.experience_years:g} yrs ({result.experience_label}) "
            f"→ ×{result.experience_multiplier:.2f}"
        )
    else:
        print(f"  Experience: not detected → ×{result.experience_multiplier:.2f}")
    if result.employer_name:
        print(
            f"  Employer pedigree: {result.employer_name} (tier {result.employer_tier}) "
            f"→ ×{result.employer_multiplier:.2f}"
        )
    else:
        print(f"  Employer pedigree: none detected → ×{result.employer_multiplier:.2f}")
    print(
        f"  Work preference: {preference_label(result.work_preference)} "
        f"({result.matching_job_share:.0%} of jobs match)"
    )
    print(
        f"  Learning readiness: {result.readiness_label} "
        f"→ ×{result.readiness_multiplier:.2f}"
    )
    print(
        f"  Degree fit: {degree_level_label(result.degree_level)} "
        f"in {field_label(result.degree_field)} "
        f"({result.matching_degree_share:.0%} meet level, "
        f"{result.matching_field_share:.0%} match field)"
    )
    if result.salary_range_label:
        print(
            f"  Probable salary: {result.salary_range_label} "
            f"({result.salary_confidence} confidence; "
            f"{result.salary_comparable_jobs} comparable jobs with pay data)"
        )
    if result.market:
        market = result.market
        print()
        print("Market clock (30-day state vs 90-day baseline):")
        print("-" * 56)
        print(f"  Supply (30d layoffs):     {market.supply_30d:,.0f}")
        print(f"  Demand (30d job posts):   {market.demand_30d:,.0f}")
        print(f"  Relative supply shock:    {market.relative_supply_shock:.2f}× baseline")
        print(f"  Relative demand strength: {market.relative_demand_strength:.2f}× baseline")
        print(f"  Saturation ratio:         {market.saturation_ratio:.2f}  (lower is better)")
        print(
            f"  Outlook drivers:          market fit {result.market_score:.0f}%"
            f" + saturation {market.saturation_ratio:.1f}×"
            f" → {VERDICT_LABELS.get(result.market_verdict, result.market_verdict)}"
        )
        print(
            f"  Active recruitment:       {result.active_recruitment_roles} roles open "
            f"(avg {result.avg_recruitment_duration:.0f}d window, "
            f"{result.avg_recruitment_progress:.0%} through)"
        )
        if result.hiring_lag_note:
            print(f"  Hiring lag (true data):   {result.hiring_lag_note}")
        if market.future_saturation_t30 is not None:
            print(f"  Forecast saturation T+30: {market.future_saturation_t30:.2f}")
    print()
    print("Per-skill breakdown (30d demand / 30d supply / relative ratio):")
    print("-" * 56)
    for signal in result.skills:
        bar = "#" * int(min(signal.ratio, 5) * 4)
        print(
            f"  {signal.skill:<22} "
            f"D:{signal.demand_score:>6.2f}  S:{signal.supply_score:>8.1f}  "
            f"R:{signal.ratio:>5.2f}  {bar}"
        )
    print()


def cmd_ingest(args: argparse.Namespace) -> int:
    init_db()
    total_inserted = 0

    if args.source in ("layoffs", "all", "history"):
        events = fetch_layoffs(include_seed=not args.no_seed)
        inserted = save_layoffs(events)
        print(f"Layoffs: fetched {len(events)}, inserted {inserted} new events")
        total_inserted += inserted

    if args.source == "history":
        rows = rebuild_market_daily(history_days=args.history_days)
        stats = market_daily_stats()
        print(f"Market history: rebuilt {rows} daily rows")
        print(
            f"  Coverage: {stats['min_date']} → {stats['max_date']} "
            f"({stats['total_days']} days, {stats['seeded_days']} seeded, "
            f"{stats['scraped_days']} with live scrapes)"
        )
        return 0

    if args.source in ("jobs", "all"):
        sources = _parse_sources(args.sources)
        grouped = fetch_jobs_by_source(
            sources=sources,
            himalayas_max_pages=args.himalayas_pages,
            arbeitnow_max_pages=args.arbeitnow_pages,
        )
        posts = []
        for source, source_posts in grouped.items():
            if args.limit is not None:
                remaining = max(args.limit - len(posts), 0)
                source_posts = source_posts[:remaining]
            posts.extend(source_posts)
            inserted = save_jobs(source_posts)
            print(
                f"Jobs ({source}): fetched {len(source_posts)}, "
                f"inserted {inserted} new posts"
            )
            total_inserted += inserted
            if args.limit is not None and len(posts) >= args.limit:
                break

    if args.source == "all":
        rows = rebuild_market_daily(history_days=args.history_days)
        stats = market_daily_stats()
        print(
            f"Market history: {stats['total_days']} days "
            f"({stats['min_date']} → {stats['max_date']})"
        )

    if total_inserted == 0 and args.source != "all":
        print("No new records inserted (data may already be cached).")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    init_db()
    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}", file=sys.stderr)
        return 1

    normalizer = SkillNormalizer()
    try:
        profile = load_profile(profile_path, normalizer=normalizer)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Profile: {profile.name}")
    if profile.role:
        print(f"Role: {profile.role}")
    if profile.location:
        print(f"Location: {profile.location}")
    print(f"Work preference: {preference_label(profile.work_preference)}")
    student_label = "yes" if profile.is_student else "no"
    print(
        f"Student: {student_label} | Degree: {degree_level_label(profile.degree_level)}"
        f" in {field_label(profile.degree_field)}"
        f"{' (completed)' if profile.has_degree else ''}"
    )
    print(f"Skills detected: {len(profile.skills)}")
    if profile.has_work_experience and profile.experience_years > 0:
        print(f"Work experience: {profile.experience_years:g} years")
    elif not profile.has_work_experience:
        print("Work experience: none detected (project/education profile)")
    if profile.current_company:
        print(f"Current company: {profile.current_company}")
    elif profile.employers:
        print(f"Employers found: {', '.join(profile.employers[:3])}")

    jobs = load_jobs()
    layoffs = load_layoffs()

    if not jobs or not layoffs:
        print("Database is empty. Run: python main.py ingest all")
        return 1

    result = compute_hireability(
        profile=profile,
        jobs=jobs,
        layoffs=layoffs,
        normalizer=normalizer,
        window_days=args.window,
    )
    _print_score(result)
    return 0


def _parse_sources(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def cmd_dedupe_jobs(args: argparse.Namespace) -> int:
    from hireability.jobs.audit import audit_jobs, remove_duplicates

    if args.fix or args.dry_run:
        remove_duplicates(dry_run=args.dry_run)
        print()
    audit_jobs(verbose=args.verbose)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    init_db()
    totals = counts()
    by_source = job_counts_by_source()
    print(f"Stored layoff events:  {totals['layoff_events']}")
    print(f"Total layoff headcount: {totals['layoff_headcount']:,}")
    print(f"Stored job posts:      {totals['job_posts']}")
    if by_source:
        print("Job posts by source:")
        for source, count in by_source.items():
            print(f"  - {source}: {count}")
    market = market_daily_stats()
    if market["total_days"]:
        print(
            f"Market daily timeline: {market['total_days']} days "
            f"({market['min_date']} → {market['max_date']})"
        )
        print(
            f"  Indeed-seeded: {market['seeded_days']} days | "
            f"Live scrapes: {market['scraped_days']} days"
        )
    else:
        print("Market daily timeline: empty — run `python main.py ingest history`")

    lag_model = load_hiring_lag_model()
    print("Hiring lag (from job sightings):")
    g = lag_model.global_profile
    if g.data_driven:
        print(
            f"  All sources: median {g.median_days:.0f}d, p90 {g.p90_days:.0f}d "
            f"({g.sample_size} multi-day jobs)"
        )
        for source, profile in sorted(lag_model.by_source.items()):
            if not profile.data_driven:
                continue
            print(
                f"  - {source}: median {profile.median_days:.0f}d, "
                f"p90 {profile.p90_days:.0f}d ({profile.sample_size} multi-day jobs)"
            )
    else:
        print(
            f"  Using {g.median_days:.0f}d default — "
            f"{g.sample_size} jobs with 2+ sighting days (need 5 for empirical lag)."
        )
        print("  Daily login ingest records true open duration per job over time.")

    if totals["layoff_events"] == 0 or totals["job_posts"] == 0:
        print("\nRun `python main.py ingest all` to populate market data.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hireability",
        description="Dynamic hireability probability score from job demand and layoff supply.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Fetch and store market data")
    ingest_parser.add_argument(
        "source",
        choices=["layoffs", "jobs", "all", "history"],
        help="Which data source to ingest (history = seed 2yr demand from Indeed)",
    )
    ingest_parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip bundled seed layoff events",
    )
    ingest_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max job posts to fetch across all selected sources",
    )
    ingest_parser.add_argument(
        "--sources",
        default=None,
        help=f"Comma-separated job sources (default: all). Options: {', '.join(JOB_SOURCES)}",
    )
    ingest_parser.add_argument(
        "--himalayas-pages",
        type=int,
        default=5,
        help="Pages to fetch from Himalayas (20 jobs per page, default: 5)",
    )
    ingest_parser.add_argument(
        "--arbeitnow-pages",
        type=int,
        default=10,
        help="Pages to fetch from Arbeitnow (100 jobs per page, default: 10)",
    )
    ingest_parser.add_argument(
        "--history-days",
        type=int,
        default=730,
        help="Days of Indeed demand history to seed (default: 730)",
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    score_parser = subparsers.add_parser("score", help="Compute hireability for a profile")
    score_parser.add_argument(
        "--profile",
        default=str(ROOT_DIR / "profile.example.yaml"),
        help="Path to a YAML profile or PDF resume",
    )
    score_parser.add_argument(
        "--window",
        type=int,
        default=30,
        help="Days between current and prior trend comparison (default: 30)",
    )
    score_parser.set_defaults(func=cmd_score)

    status_parser = subparsers.add_parser("status", help="Show stored record counts")
    status_parser.set_defaults(func=cmd_status)

    dedupe_parser = subparsers.add_parser(
        "dedupe-jobs",
        help="Audit or remove duplicate job postings",
    )
    dedupe_parser.add_argument(
        "--fix",
        action="store_true",
        help="Delete redundant rows, keeping the oldest copy of each job",
    )
    dedupe_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what --fix would delete without changing the database",
    )
    dedupe_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print URLs for duplicate rows",
    )
    dedupe_parser.set_defaults(func=cmd_dedupe_jobs)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
