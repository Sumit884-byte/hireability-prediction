#!/usr/bin/env python3
"""Export the 30/90-day market feature matrix for model training."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hireability.config import HISTORY_DAYS
from hireability.scoring.timeseries import build_training_matrix
from hireability.storage import init_db, load_jobs, load_layoffs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build 30/90-day market features with forward-shifted targets.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "data" / "market_features.csv"),
        help="CSV path for the training matrix",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=HISTORY_DAYS,
        help="Days of history to include",
    )
    args = parser.parse_args()

    init_db()
    jobs = load_jobs()
    layoffs = load_layoffs()
    if not jobs or not layoffs:
        print("Database empty. Run: python main.py ingest all")
        return 1

    matrix = build_training_matrix(jobs, layoffs, history_days=args.history_days)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(output, index=False)

    print(f"Wrote {len(matrix)} rows to {output}")
    print()
    print("Columns:")
    for column in matrix.columns:
        print(f"  - {column}")
    print()
    if not matrix.empty:
        latest = matrix.iloc[-1]
        print("Latest snapshot:")
        print(f"  supply_30d:               {latest['supply_30d']:.1f}")
        print(f"  demand_30d:               {latest['demand_30d']:.1f}")
        print(f"  relative_supply_shock:    {latest['relative_supply_shock']:.2f}")
        print(f"  relative_demand_strength: {latest['relative_demand_strength']:.2f}")
        if "target_future_saturation" in latest:
            print(f"  target_future_saturation: {latest['target_future_saturation']:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
