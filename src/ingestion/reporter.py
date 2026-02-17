"""
Ingestion reporter: formats and displays run metrics and DB growth stats.
"""

import logging
from typing import Optional

from src.ingestion.pipeline import RunResult
from src.database.db_manager import DatabaseManager
from src.utils.logger import setup_logger


class IngestionReporter:
    """Formats ingestion run results for console and log output."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or setup_logger(
            "ingestion.reporter", log_file="ingestion.log"
        )

    def report_run(self, result: RunResult) -> None:
        """Print a formatted summary of a completed ingestion run."""
        divider = "=" * 66
        lines = [
            "",
            divider,
            f"  INGESTION RUN #{result.run_id}  |  "
            f"{result.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            divider,
            f"  Status   : {result.status}",
            f"  Duration : {self._fmt_duration(result.duration_seconds)}",
            f"  Apps     : {result.total_apps_processed} processed"
            + (f", {result.total_apps_failed} failed"
               if result.total_apps_failed else ""),
            "",
            "  Per-app breakdown:",
            f"  {'App':<45} {'Fetched':>7} {'New':>5} {'Skip':>6} {'Time':>7}",
            "  " + "-" * 72,
        ]

        for ar in result.app_results:
            label = ar.app_title or ar.app_id
            if len(label) > 43:
                label = label[:40] + "..."
            status = f"  ERR: {ar.error}" if ar.error else ""
            lines.append(
                f"  {label:<45} {ar.reviews_fetched:>7} "
                f"{ar.reviews_inserted:>5} {ar.reviews_skipped:>6} "
                f"{ar.duration_seconds:>6.1f}s{status}"
            )

        dedup_rate = (
            result.total_reviews_skipped / result.total_reviews_fetched * 100
            if result.total_reviews_fetched > 0 else 0
        )

        lines.extend([
            "",
            f"  Totals:",
            f"    Reviews fetched    : {result.total_reviews_fetched:,}",
            f"    New (inserted)     : {result.total_reviews_inserted:,}",
            f"    Duplicates skipped : {result.total_reviews_skipped:,}",
            f"    Dedup rate         : {dedup_rate:.1f}%",
            divider,
            "",
        ])

        output = "\n".join(lines)
        print(output)
        self.logger.info(output)

    def report_db_growth(self, db: DatabaseManager) -> None:
        """Print current cumulative database statistics."""
        stats = db.get_stats()
        lines = [
            "",
            "  Database snapshot:",
            f"    Total reviews  : {stats['total_reviews']:,}",
            f"    Total apps     : {stats['total_apps']}",
            f"    Avg rating     : {stats['avg_rating']}",
            f"    Date range     : {stats['earliest_review']} .. "
            f"{stats['latest_review']}",
            f"    DB file size   : {stats['db_file_size_mb']} MB",
            "",
        ]
        output = "\n".join(lines)
        print(output)
        self.logger.info(output)

    def report_run_history(self, db: DatabaseManager, last_n: int = 10) -> None:
        """Show the last N scrape runs from the scrape_runs table."""
        conn = db.connect()
        rows = conn.execute("""
            SELECT run_id, started_at, completed_at, status,
                   total_reviews_collected, total_apps_processed,
                   reviews_per_app, error_message
            FROM scrape_runs
            ORDER BY run_id DESC
            LIMIT ?
        """, (last_n,)).fetchall()

        if not rows:
            print("\n  No ingestion runs recorded yet.\n")
            return

        divider = "=" * 90
        print(f"\n{divider}")
        print(f"  Last {min(last_n, len(rows))} ingestion runs")
        print(divider)
        print(
            f"  {'Run':>4}  {'Started':<20} {'Status':<10} "
            f"{'Reviews':>8} {'Apps':>5} {'Per App':>8}  Error"
        )
        print("  " + "-" * 84)

        for row in rows:
            started = row["started_at"] or "?"
            if len(str(started)) > 19:
                started = str(started)[:19]
            error = row["error_message"] or ""
            if len(error) > 30:
                error = error[:27] + "..."
            print(
                f"  {row['run_id']:>4}  {started:<20} "
                f"{row['status']:<10} "
                f"{row['total_reviews_collected'] or 0:>8} "
                f"{row['total_apps_processed'] or 0:>5} "
                f"{row['reviews_per_app'] or 0:>8}  {error}"
            )

        print(f"{divider}\n")

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """Format seconds as 'Xm Ys' or 'Ys'."""
        if seconds >= 60:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"{m}m {s}s"
        return f"{seconds:.1f}s"
