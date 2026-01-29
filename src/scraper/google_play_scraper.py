"""
Google Play Review Scraper - Core scraping logic.

This module provides the main scraper class for fetching reviews
from Google Play Store using the google-play-scraper library.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Generator
from datetime import datetime

from google_play_scraper import app, reviews, Sort
from google_play_scraper.exceptions import NotFoundError

from src.models.review import Review, AppInfo
from src.scraper.rate_limiter import RateLimiter, ExponentialBackoff
from src.config.settings import (
    BATCH_SIZE,
    DEFAULT_REVIEW_COUNT,
    DEFAULT_LANGUAGE,
    DEFAULT_COUNTRY,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    SortOrder,
)
from src.utils.logger import get_logger, ProgressTracker


class GooglePlayReviewScraper:
    """
    Scraper for Google Play Store reviews.

    Handles fetching app information and reviews with rate limiting,
    retry logic, and progress tracking.
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the scraper.

        Args:
            rate_limiter: Rate limiter instance (creates default if None)
            logger: Logger instance (creates default if None)
        """
        self.rate_limiter = rate_limiter or RateLimiter()
        self.logger = logger or get_logger("scraper")
        self.progress = ProgressTracker(self.logger)

    def fetch_app_info(self, app_id: str) -> Optional[AppInfo]:
        """
        Fetch app metadata from Google Play.

        Args:
            app_id: App package name (e.g., 'com.whatsapp')

        Returns:
            AppInfo instance or None if not found
        """
        self.logger.info(f"Fetching app info for: {app_id}")
        backoff = ExponentialBackoff(
            base_delay=RETRY_BASE_DELAY,
            max_delay=RETRY_MAX_DELAY,
            max_retries=MAX_RETRIES
        )

        while True:
            try:
                self.rate_limiter.wait()
                raw_data = app(app_id)
                app_info = AppInfo.from_google_play(raw_data)
                self.logger.info(
                    f"App found: {app_info.title} by {app_info.developer} "
                    f"({app_info.reviews_count} reviews)"
                )
                return app_info

            except NotFoundError:
                self.logger.error(f"App not found: {app_id}")
                return None

            except Exception as e:
                self.logger.warning(f"Error fetching app info: {e}")
                if not backoff.wait():
                    self.logger.error(
                        f"Max retries exceeded for app info: {app_id}"
                    )
                    return None

    def fetch_reviews(
        self,
        app_id: str,
        count: int = DEFAULT_REVIEW_COUNT,
        lang: str = DEFAULT_LANGUAGE,
        country: str = DEFAULT_COUNTRY,
        sort: int = SortOrder.NEWEST
    ) -> List[Review]:
        """
        Fetch reviews for a specific app.

        Args:
            app_id: App package name
            count: Number of reviews to fetch
            lang: Language code (e.g., 'en')
            country: Country code (e.g., 'us')
            sort: Sort order (see SortOrder class)

        Returns:
            List of Review objects
        """
        self.logger.info(
            f"Starting to fetch {count} reviews for {app_id} "
            f"(lang={lang}, country={country})"
        )

        collected_reviews: List[Review] = []
        continuation_token = None

        # Map sort order to library enum
        sort_map = {
            SortOrder.MOST_RELEVANT: Sort.MOST_RELEVANT,
            SortOrder.NEWEST: Sort.NEWEST,
            SortOrder.RATING: Sort.RATING,
        }
        sort_enum = sort_map.get(sort, Sort.NEWEST)

        while len(collected_reviews) < count:
            batch_size = min(BATCH_SIZE, count - len(collected_reviews))

            result = self._fetch_reviews_batch(
                app_id=app_id,
                count=batch_size,
                lang=lang,
                country=country,
                sort=sort_enum,
                continuation_token=continuation_token
            )

            if result is None:
                self.logger.warning(
                    f"Failed to fetch batch for {app_id}, stopping"
                )
                break

            batch_reviews, continuation_token = result

            if not batch_reviews:
                self.logger.info(f"No more reviews available for {app_id}")
                break

            # Convert raw reviews to Review objects
            for raw_review in batch_reviews:
                review = Review.from_google_play(raw_review, app_id)
                collected_reviews.append(review)

            # Log progress
            self.progress.log_progress(app_id, len(collected_reviews), count)

            # If no continuation token, we've reached the end
            if continuation_token is None:
                self.logger.info(f"Reached end of reviews for {app_id}")
                break

        self.progress.log_completion(app_id, len(collected_reviews))
        return collected_reviews

    def _fetch_reviews_batch(
        self,
        app_id: str,
        count: int,
        lang: str,
        country: str,
        sort: Sort,
        continuation_token: Optional[str]
    ) -> Optional[Tuple[List[Dict[str, Any]], Optional[str]]]:
        """
        Fetch a single batch of reviews with retry logic.

        Args:
            app_id: App package name
            count: Number of reviews to fetch
            lang: Language code
            country: Country code
            sort: Sort order enum
            continuation_token: Token for pagination

        Returns:
            Tuple of (reviews list, next continuation token) or None on failure
        """
        backoff = ExponentialBackoff(
            base_delay=RETRY_BASE_DELAY,
            max_delay=RETRY_MAX_DELAY,
            max_retries=MAX_RETRIES
        )

        while True:
            try:
                self.rate_limiter.wait()

                result, token = reviews(
                    app_id,
                    lang=lang,
                    country=country,
                    sort=sort,
                    count=count,
                    continuation_token=continuation_token
                )

                return result, token

            except Exception as e:
                self.logger.warning(f"Error fetching reviews batch: {e}")
                self.progress.log_error(app_id, e)

                if not backoff.wait():
                    self.logger.error(
                        f"Max retries exceeded for batch fetch: {app_id}"
                    )
                    return None

    def fetch_reviews_generator(
        self,
        app_id: str,
        count: int = DEFAULT_REVIEW_COUNT,
        lang: str = DEFAULT_LANGUAGE,
        country: str = DEFAULT_COUNTRY,
        sort: int = SortOrder.NEWEST
    ) -> Generator[Review, None, None]:
        """
        Fetch reviews as a generator for memory efficiency.

        Yields reviews one at a time instead of collecting all in memory.

        Args:
            app_id: App package name
            count: Maximum number of reviews to fetch
            lang: Language code
            country: Country code
            sort: Sort order

        Yields:
            Review objects one at a time
        """
        self.logger.info(f"Starting generator fetch for {app_id}")

        continuation_token = None
        fetched = 0

        sort_map = {
            SortOrder.MOST_RELEVANT: Sort.MOST_RELEVANT,
            SortOrder.NEWEST: Sort.NEWEST,
            SortOrder.RATING: Sort.RATING,
        }
        sort_enum = sort_map.get(sort, Sort.NEWEST)

        while fetched < count:
            batch_size = min(BATCH_SIZE, count - fetched)

            result = self._fetch_reviews_batch(
                app_id=app_id,
                count=batch_size,
                lang=lang,
                country=country,
                sort=sort_enum,
                continuation_token=continuation_token
            )

            if result is None:
                break

            batch_reviews, continuation_token = result

            if not batch_reviews:
                break

            for raw_review in batch_reviews:
                review = Review.from_google_play(raw_review, app_id)
                yield review
                fetched += 1

                if fetched >= count:
                    break

            if continuation_token is None:
                break

    def fetch_reviews_batch(
        self,
        app_ids: List[str],
        count_per_app: int = DEFAULT_REVIEW_COUNT,
        lang: str = DEFAULT_LANGUAGE,
        country: str = DEFAULT_COUNTRY,
        sort: int = SortOrder.NEWEST
    ) -> Dict[str, List[Review]]:
        """
        Fetch reviews from multiple apps.

        Args:
            app_ids: List of app package names
            count_per_app: Number of reviews to fetch per app
            lang: Language code
            country: Country code
            sort: Sort order

        Returns:
            Dictionary mapping app_id to list of Reviews
        """
        self.logger.info(
            f"Starting batch fetch for {len(app_ids)} apps, "
            f"{count_per_app} reviews each"
        )

        results: Dict[str, List[Review]] = {}

        for app_id in app_ids:
            self.logger.info(f"Processing app: {app_id}")

            # Verify app exists first
            app_info = self.fetch_app_info(app_id)
            if app_info is None:
                self.logger.warning(f"Skipping {app_id} - app not found")
                results[app_id] = []
                continue

            # Fetch reviews
            reviews_list = self.fetch_reviews(
                app_id=app_id,
                count=count_per_app,
                lang=lang,
                country=country,
                sort=sort
            )

            results[app_id] = reviews_list

        self.progress.log_summary()
        return results
