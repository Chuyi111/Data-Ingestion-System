"""
Ingestion scheduler: runs the pipeline at configurable intervals.

Uses a simple sleep loop with graceful signal handling.
"""

import signal
import time
import threading
import logging
from typing import List, Optional

from src.ingestion.pipeline import IngestionPipeline, RunResult
from src.ingestion.reporter import IngestionReporter
from src.database.db_manager import DatabaseManager
from src.config.settings import (
    INGESTION_INTERVAL_SECONDS,
    INGESTION_REVIEWS_PER_APP,
    INGESTION_DB_PATH,
    DEFAULT_TARGET_APPS,
)
from src.utils.logger import setup_logger


class IngestionScheduler:
    """
    Timed scheduler for the ingestion pipeline.

    Runs ingestion cycles at a configurable interval. Supports one-shot
    mode for testing. Handles SIGINT/SIGTERM for graceful shutdown.
    """

    def __init__(
        self,
        target_apps: Optional[List[str]] = None,
        interval_seconds: int = INGESTION_INTERVAL_SECONDS,
        db_path: str = INGESTION_DB_PATH,
        reviews_per_app: int = INGESTION_REVIEWS_PER_APP,
        one_shot: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self.target_apps = target_apps or DEFAULT_TARGET_APPS
        self.interval_seconds = interval_seconds
        self.db_path = db_path
        self.reviews_per_app = reviews_per_app
        self.one_shot = one_shot
        self.logger = logger or setup_logger(
            "ingestion.scheduler", log_file="ingestion.log"
        )
        self._stop_event = threading.Event()
        self._run_count = 0

    def start(self) -> None:
        """Start the scheduler loop. Blocks until stopped or one-shot completes."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self.logger.info(
            f"Scheduler starting | interval={self.interval_seconds}s | "
            f"apps={len(self.target_apps)} | "
            f"reviews_per_app={self.reviews_per_app} | "
            f"one_shot={self.one_shot}"
        )

        while not self._stop_event.is_set():
            self._run_count += 1
            self.logger.info(f"--- Ingestion run #{self._run_count} ---")

            try:
                result = self._execute_run()
                self._report(result)
            except Exception as e:
                self.logger.error(
                    f"Run #{self._run_count} failed with exception: {e}",
                    exc_info=True,
                )

            if self.one_shot:
                self.logger.info("One-shot mode: exiting after first run.")
                break

            self.logger.info(
                f"Next run in {self.interval_seconds}s. Press Ctrl+C to stop."
            )
            self._interruptible_sleep(self.interval_seconds)

        self.logger.info("Scheduler stopped.")

    def stop(self) -> None:
        """Signal the scheduler to stop after the current run completes."""
        self._stop_event.set()

    def _execute_run(self) -> RunResult:
        """Create a pipeline instance and execute one ingestion cycle."""
        pipeline = IngestionPipeline(
            db_path=self.db_path,
            reviews_per_app=self.reviews_per_app,
            logger=self.logger,
        )
        return pipeline.run(self.target_apps)

    def _report(self, result: RunResult) -> None:
        """Report run results, DB stats, and health metrics."""
        reporter = IngestionReporter(logger=self.logger)
        reporter.report_run(result)

        db = DatabaseManager(self.db_path)
        db.init_schema()  # ensures ingestion_metrics table exists
        reporter.report_db_growth(db)

        # Health monitoring
        from src.ingestion.monitor import IngestionMonitor

        monitor = IngestionMonitor(db=db, logger=self.logger)
        health_report = monitor.evaluate_run(result)
        monitor.store_report(health_report)
        monitor.print_alerts(health_report)

        db.close()

    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep in 1-second increments so Ctrl+C is responsive."""
        for _ in range(seconds):
            if self._stop_event.is_set():
                break
            time.sleep(1)

    def _handle_signal(self, signum, frame):
        """Handle SIGINT/SIGTERM by setting the stop event."""
        self.logger.info(
            "Interrupt received. Will stop after current operation completes."
        )
        self._stop_event.set()
