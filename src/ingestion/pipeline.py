"""
Ingestion pipeline: scrapes Google Play reviews directly into the database.

Bridges GooglePlayReviewScraper and DatabaseManager without intermediate
JSON/CSV files. Populates scrape_runs and review_scrape_log tables for
full audit trail.
"""

import time
import logging
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field

from src.scraper.google_play_scraper import GooglePlayReviewScraper
from src.scraper.rate_limiter import RateLimiter
from src.database.db_manager import DatabaseManager
from src.config.settings import (
    INGESTION_REVIEWS_PER_APP,
    DEFAULT_LANGUAGE,
    DEFAULT_COUNTRY,
    SortOrder,
)
from src.utils.logger import setup_logger


@dataclass
class AppRunResult:
    """Result of ingesting reviews for a single app."""
    app_id: str
    reviews_fetched: int = 0
    reviews_inserted: int = 0
    reviews_skipped: int = 0
    app_title: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class RunResult:
    """Result of a full ingestion run across all apps."""
    run_id: int
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "running"
    app_results: List[AppRunResult] = field(default_factory=list)
    total_reviews_fetched: int = 0
    total_reviews_inserted: int = 0
    total_reviews_skipped: int = 0
    total_apps_processed: int = 0
    total_apps_failed: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class IngestionPipeline:
    """
    Core ingestion pipeline: scrape → deduplicate → insert → log.

    Reuses the existing GooglePlayReviewScraper for fetching and
    DatabaseManager for persistence, wiring them together directly.
    """

    def __init__(
        self,
        db_path: str = "data/reviews.db",
        reviews_per_app: int = INGESTION_REVIEWS_PER_APP,
        language: str = DEFAULT_LANGUAGE,
        country: str = DEFAULT_COUNTRY,
        sort_order: int = SortOrder.NEWEST,
        logger: Optional[logging.Logger] = None,
    ):
        self.db_path = db_path
        self.reviews_per_app = reviews_per_app
        self.language = language
        self.country = country
        self.sort_order = sort_order
        self.logger = logger or setup_logger(
            "ingestion", log_file="ingestion.log"
        )

    def run(self, target_apps: List[str]) -> RunResult:
        """
        Execute a full ingestion run for the given apps.

        For each app: fetch app info, fetch reviews, deduplicate against
        existing DB contents, insert new reviews, and log the linkage
        in review_scrape_log.
        """
        db = DatabaseManager(self.db_path)
        db.init_schema()

        scraper = GooglePlayReviewScraper(
            rate_limiter=RateLimiter(),
            logger=self.logger,
        )

        # Start a scrape run record
        run_id = db.start_scrape_run(
            target_apps=target_apps,
            reviews_per_app=self.reviews_per_app,
            language=self.language,
            country=self.country,
            sort_order="newest",
        )

        result = RunResult(run_id=run_id, started_at=datetime.now())
        run_start = time.time()

        self.logger.info(
            f"Run #{run_id} started: {len(target_apps)} apps, "
            f"{self.reviews_per_app} reviews each"
        )

        for app_id in target_apps:
            app_result = self._process_app(app_id, scraper, db, run_id)
            result.app_results.append(app_result)

            result.total_reviews_fetched += app_result.reviews_fetched
            result.total_reviews_inserted += app_result.reviews_inserted
            result.total_reviews_skipped += app_result.reviews_skipped

            if app_result.error:
                result.total_apps_failed += 1
            else:
                result.total_apps_processed += 1

        # Determine final status
        if result.total_apps_failed == 0:
            result.status = "completed"
        elif result.total_apps_processed == 0:
            result.status = "failed"
        else:
            result.status = "partial"

        # Build error summary if any apps failed
        failed_apps = [
            r.app_id for r in result.app_results if r.error
        ]
        if failed_apps:
            result.error_message = (
                f"{len(failed_apps)} apps failed: "
                + ", ".join(failed_apps)
            )

        # Finalize the scrape run record
        db.complete_scrape_run(
            run_id=run_id,
            total_reviews=result.total_reviews_inserted,
            total_apps=result.total_apps_processed,
            status=result.status,
            error_message=result.error_message,
        )

        result.completed_at = datetime.now()
        result.duration_seconds = time.time() - run_start

        db.close()
        return result

    def _process_app(
        self,
        app_id: str,
        scraper: GooglePlayReviewScraper,
        db: DatabaseManager,
        run_id: int,
    ) -> AppRunResult:
        """Process a single app: fetch info, fetch reviews, insert new ones."""
        app_result = AppRunResult(app_id=app_id)
        app_start = time.time()

        try:
            # 1. Fetch and store app metadata (real data, not stubs)
            app_info = scraper.fetch_app_info(app_id)
            if app_info is None:
                app_result.error = "app_not_found"
                app_result.duration_seconds = time.time() - app_start
                self.logger.warning(f"  {app_id}: app not found, skipping")
                return app_result

            app_result.app_title = app_info.title
            db.insert_app(app_info)

            # 2. Fetch newest reviews
            reviews = scraper.fetch_reviews(
                app_id=app_id,
                count=self.reviews_per_app,
                lang=self.language,
                country=self.country,
                sort=self.sort_order,
            )
            app_result.reviews_fetched = len(reviews)

            if not reviews:
                app_result.duration_seconds = time.time() - app_start
                self.logger.info(
                    f"  {app_id}: 0 reviews fetched"
                )
                return app_result

            # 3. Deduplicate: find which fetched reviews already exist
            fetched_ids = {r.review_id for r in reviews}
            existing_ids = db.get_existing_review_ids(fetched_ids)
            new_reviews = [
                r for r in reviews if r.review_id not in existing_ids
            ]
            app_result.reviews_skipped = len(reviews) - len(new_reviews)

            # 4. Insert only new reviews
            if new_reviews:
                inserted, _ = db.insert_reviews_bulk(new_reviews)
                app_result.reviews_inserted = inserted

                # 5. Log the linkage in review_scrape_log
                new_ids = [r.review_id for r in new_reviews]
                db.log_review_scrape_bulk(new_ids, run_id)
            else:
                app_result.reviews_inserted = 0

        except Exception as e:
            app_result.error = str(e)
            self.logger.error(f"  {app_id}: error - {e}")

        app_result.duration_seconds = time.time() - app_start

        self.logger.info(
            f"  {app_id:<45} "
            f"fetched={app_result.reviews_fetched:<4} "
            f"new={app_result.reviews_inserted:<4} "
            f"skipped={app_result.reviews_skipped:<4} "
            f"{app_result.duration_seconds:.1f}s"
            + (f"  ERROR: {app_result.error}" if app_result.error else "")
        )

        return app_result
