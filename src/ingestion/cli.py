"""
Ingestion CLI entry point.

Usage:
    # Run once immediately (test mode)
    python -m src.ingestion.cli --once

    # Start scheduler (every 4 hours, default apps)
    python -m src.ingestion.cli

    # Custom interval and apps
    python -m src.ingestion.cli --interval 7200 --apps com.whatsapp,com.spotify.music

    # Fewer reviews per app
    python -m src.ingestion.cli --once --count 100

    # Show run history
    python -m src.ingestion.cli --history

    # Show current DB stats
    python -m src.ingestion.cli --stats
"""

import argparse
import sys

from src.ingestion.scheduler import IngestionScheduler
from src.ingestion.reporter import IngestionReporter
from src.database.db_manager import DatabaseManager
from src.config.settings import (
    DEFAULT_TARGET_APPS,
    INGESTION_INTERVAL_SECONDS,
    INGESTION_DB_PATH,
    INGESTION_REVIEWS_PER_APP,
)


def main():
    parser = argparse.ArgumentParser(
        description="Automated Google Play review ingestion scheduler"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single ingestion cycle and exit",
    )
    parser.add_argument(
        "--interval", type=int, default=INGESTION_INTERVAL_SECONDS,
        help=f"Seconds between runs (default: {INGESTION_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--apps", type=str, default=None,
        help="Comma-separated app IDs (default: all 20 target apps)",
    )
    parser.add_argument(
        "--count", type=int, default=INGESTION_REVIEWS_PER_APP,
        help=f"Reviews per app per run (default: {INGESTION_REVIEWS_PER_APP})",
    )
    parser.add_argument(
        "--database", default=INGESTION_DB_PATH,
        help=f"Path to SQLite database (default: {INGESTION_DB_PATH})",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="Show last 10 scrape runs and exit",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show current DB stats and exit",
    )

    args = parser.parse_args()

    target_apps = (
        [a.strip() for a in args.apps.split(",")]
        if args.apps else DEFAULT_TARGET_APPS
    )

    # Report-only modes
    if args.history:
        db = DatabaseManager(args.database)
        reporter = IngestionReporter()
        reporter.report_run_history(db)
        db.close()
        return 0

    if args.stats:
        db = DatabaseManager(args.database)
        reporter = IngestionReporter()
        reporter.report_db_growth(db)
        db.close()
        return 0

    # Ingestion mode
    scheduler = IngestionScheduler(
        target_apps=target_apps,
        interval_seconds=args.interval,
        db_path=args.database,
        reviews_per_app=args.count,
        one_shot=args.once,
    )
    scheduler.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
