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

    # Show latest health report
    python -m src.ingestion.cli --health

    # Show last N health reports summary
    python -m src.ingestion.cli --health-history 5

    # Backfill metrics for historical runs
    python -m src.ingestion.cli --backfill-metrics
"""

import argparse
import sys
from typing import Dict, List, Any

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
    parser.add_argument(
        "--health", action="store_true",
        help="Show latest health report and exit",
    )
    parser.add_argument(
        "--health-history", type=int, metavar="N", default=None,
        help="Show last N health reports summary and exit",
    )
    parser.add_argument(
        "--backfill-metrics", action="store_true",
        help="Backfill health metrics for historical runs and exit",
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

    # Health report modes
    if args.health:
        from src.ingestion.monitor import IngestionMonitor

        db = DatabaseManager(args.database)
        db.init_schema()
        monitor = IngestionMonitor(db=db)
        reports = monitor.get_recent_health_reports(limit=1)
        if reports:
            _print_health_report(reports[0])
        else:
            print("\n  No health reports available yet.\n")
        db.close()
        return 0

    if args.health_history is not None:
        from src.ingestion.monitor import IngestionMonitor

        db = DatabaseManager(args.database)
        db.init_schema()
        monitor = IngestionMonitor(db=db)
        reports = monitor.get_recent_health_reports(limit=args.health_history)
        _print_health_summary(reports)
        db.close()
        return 0

    if args.backfill_metrics:
        from src.ingestion.monitor import IngestionMonitor

        db = DatabaseManager(args.database)
        db.init_schema()
        monitor = IngestionMonitor(db=db)
        print("\n  Backfilling health metrics for historical runs...\n")
        backfilled = monitor.backfill_metrics()
        print(f"\n  Backfilled {backfilled} runs.\n")
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


# -------------------------------------------------------------------------
# Display helpers
# -------------------------------------------------------------------------

def _print_health_report(report: Dict[str, Any]) -> None:
    """Pretty-print a single health report."""
    m = report["metrics"]
    dq = report["data_quality"]
    deltas = report["deltas"]

    div = "=" * 70
    print(f"\n{div}")
    print(
        f"  HEALTH REPORT - Run #{report['run_id']}  |  "
        f"{report['timestamp'][:19]}"
    )
    print(f"  Status: {report['status']}")
    print(div)

    print(f"\n  Performance:")
    print(f"    Reviews inserted     : {m['reviews_inserted']:,}")
    print(f"    Reviews fetched      : {m['reviews_fetched']:,}")
    print(f"    Dedup rate           : {m['dedup_rate']*100:.1f}%")
    print(f"    Error rate           : {m['error_rate']*100:.1f}%")
    print(f"    Duration             : {m['duration_seconds']:.0f}s")
    print(
        f"    Ingestion rate       : "
        f"{m['ingestion_rate_per_min']:.0f} reviews/min"
    )
    print(
        f"    Apps                 : "
        f"{m['apps_processed']} ok, {m['apps_failed']} failed"
    )

    print(f"\n  Data Quality:")
    print(
        f"    app_version null     : {dq['app_version_null_rate']*100:.1f}%  "
        f"(baseline {dq['app_version_null_rate_baseline']*100:.1f}%, "
        f"shift {dq['app_version_null_rate_shift_pct']:+.1f}pp)"
    )
    print(
        f"    reply_content null   : {dq['reply_content_null_rate']*100:.1f}%  "
        f"(baseline {dq['reply_content_null_rate_baseline']*100:.1f}%, "
        f"shift {dq['reply_content_null_rate_shift_pct']:+.1f}pp)"
    )
    print(
        f"    empty content        : {dq['empty_content_rate']*100:.1f}%"
    )
    print(
        f"    avg content length   : {dq['avg_content_length']:.0f} chars  "
        f"(baseline {dq['avg_content_length_baseline']:.0f})"
    )

    if deltas.get("vs_previous"):
        print(f"\n  Delta vs Previous Run:")
        for metric, d in deltas["vs_previous"].items():
            print(
                f"    {metric:<22}: {d['current']:>8.0f}  "
                f"(was {d['previous']:.0f}, "
                f"{d['change_pct']:+.1f}%)"
            )

    if deltas.get("vs_avg_last_5"):
        print(f"\n  Delta vs Last-5 Average:")
        for metric, d in deltas["vs_avg_last_5"].items():
            z_str = f", z={d['z_score']:.1f}" if d.get("z_score") else ""
            print(
                f"    {metric:<22}: {d['current']:>8.0f}  "
                f"(avg {d['baseline']:.0f}, "
                f"{d['deviation_pct']:+.1f}%{z_str})"
            )

    alerts = report.get("alerts", [])
    if alerts:
        print(f"\n  Alerts ({len(alerts)}):")
        for a in alerts:
            prefix = (
                "[WARNING]" if a["level"] == "WARNING" else "[INFO   ]"
            )
            print(f"    {prefix} {a['message']}")
    else:
        print(f"\n  Alerts: None")

    print(f"\n{div}\n")


def _print_health_summary(reports: List[Dict[str, Any]]) -> None:
    """Print tabular summary of multiple health reports."""
    if not reports:
        print("\n  No health reports available.\n")
        return

    div = "=" * 100
    print(f"\n{div}")
    print(f"  Health Summary - Last {len(reports)} Runs")
    print(div)
    print(
        f"  {'Run':>4}  {'Timestamp':<20} {'Status':<10} "
        f"{'Inserted':>8} {'Dedup%':>7} {'Err%':>5} "
        f"{'Dur(s)':>7} {'Alerts':>7}"
    )
    print("  " + "-" * 94)

    for r in reports:
        m = r["metrics"]
        print(
            f"  {r['run_id']:>4}  "
            f"{r['timestamp'][:19]:<20} "
            f"{r['status']:<10} "
            f"{m['reviews_inserted']:>8} "
            f"{m['dedup_rate']*100:>6.1f}% "
            f"{m['error_rate']*100:>4.1f}% "
            f"{m['duration_seconds']:>7.0f} "
            f"{len(r.get('alerts', [])):>7}"
        )

    print(f"{div}\n")


if __name__ == "__main__":
    sys.exit(main())
