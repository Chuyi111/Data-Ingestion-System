"""
Logging configuration for Google Play Review Scraper.

Provides centralized logging setup with both file and console handlers.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from src.config.settings import LOG_DIR, LOG_FILE, LOG_LEVEL, LOG_FORMAT


def setup_logger(
    name: str = "scraper",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_to_console: bool = True,
    log_to_file: bool = True
) -> logging.Logger:
    """
    Set up and configure a logger instance.

    Args:
        name: Logger name (default: "scraper")
        log_level: Logging level (default: from settings)
        log_file: Log file path (default: from settings)
        log_to_console: Whether to output logs to console
        log_to_file: Whether to output logs to file

    Returns:
        Configured logger instance
    """
    # Use defaults from settings if not provided
    log_level = log_level or LOG_LEVEL
    log_file = log_file or LOG_FILE

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT)

    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler
    if log_to_file:
        # Ensure log directory exists
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / log_file
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "scraper") -> logging.Logger:
    """
    Get an existing logger or create a new one.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)

    # If logger has no handlers, set it up with defaults
    if not logger.handlers:
        return setup_logger(name)

    return logger


class ProgressTracker:
    """
    Track and log scraping progress.

    Provides methods to log progress at regular intervals and
    track statistics like total reviews, errors, and time elapsed.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize progress tracker.

        Args:
            logger: Logger instance (default: creates new one)
        """
        self.logger = logger or get_logger("progress")
        self.total_reviews = 0
        self.total_errors = 0
        self.apps_processed = 0

    def log_progress(self, app_id: str, reviews_fetched: int, total_target: int):
        """
        Log progress for a specific app.

        Args:
            app_id: App package name
            reviews_fetched: Number of reviews fetched so far
            total_target: Target number of reviews
        """
        percentage = (reviews_fetched / total_target * 100) if total_target > 0 else 0
        self.logger.info(
            f"[{app_id}] Progress: {reviews_fetched}/{total_target} "
            f"({percentage:.1f}%)"
        )

    def log_error(self, app_id: str, error: Exception):
        """
        Log an error that occurred during scraping.

        Args:
            app_id: App package name
            error: Exception that occurred
        """
        self.total_errors += 1
        self.logger.error(f"[{app_id}] Error: {str(error)}")

    def log_completion(self, app_id: str, reviews_collected: int):
        """
        Log completion of scraping for an app.

        Args:
            app_id: App package name
            reviews_collected: Total reviews collected
        """
        self.total_reviews += reviews_collected
        self.apps_processed += 1
        self.logger.info(
            f"[{app_id}] Completed: {reviews_collected} reviews collected"
        )

    def log_summary(self):
        """Log summary statistics at the end of scraping."""
        self.logger.info("=" * 50)
        self.logger.info("SCRAPING SUMMARY")
        self.logger.info(f"Apps processed: {self.apps_processed}")
        self.logger.info(f"Total reviews collected: {self.total_reviews}")
        self.logger.info(f"Total errors: {self.total_errors}")
        self.logger.info("=" * 50)
