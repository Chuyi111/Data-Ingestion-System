"""
Google Play Review Scraper - CLI Entry Point

Main script for running the Google Play review scraper with command-line arguments.

Usage:
    # Single app - fetch 5000 reviews
    python -m src.main --app com.whatsapp --count 5000

    # Multiple apps - fetch 3000 each
    python -m src.main --apps com.whatsapp,com.instagram.android --count 3000

    # With custom settings
    python -m src.main --app com.spotify.music --count 10000 --lang en --country us
"""

import argparse
import signal
import sys
from pathlib import Path
from typing import List, Optional

from tqdm import tqdm

from src.scraper.google_play_scraper import GooglePlayReviewScraper
from src.scraper.rate_limiter import RateLimiter
from src.storage.file_storage import FileStorage
from src.models.review import Review
from src.config.settings import (
    DEFAULT_TARGET_APPS,
    DEFAULT_REVIEW_COUNT,
    DEFAULT_LANGUAGE,
    DEFAULT_COUNTRY,
    DEFAULT_DELAY,
    MIN_DELAY,
    MAX_DELAY,
    CHECKPOINT_INTERVAL,
    SortOrder,
)
from src.utils.logger import setup_logger


# Global storage for graceful shutdown
_collected_reviews: List[Review] = []
_storage: Optional[FileStorage] = None


def signal_handler(signum, frame):
    """Handle interrupt signal for graceful shutdown."""
    print("\n\nInterrupt received. Saving collected data...")
    if _storage and _collected_reviews:
        _storage.save_reviews(_collected_reviews)
        print(f"Saved {len(_collected_reviews)} reviews before exit.")
    sys.exit(0)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Google Play Review Scraper - Collect app reviews at scale",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --app com.whatsapp --count 5000
  %(prog)s --apps com.whatsapp,com.instagram.android --count 3000
  %(prog)s --app com.spotify.music --count 10000 --lang en --country us
        """
    )

    # App selection (mutually exclusive)
    app_group = parser.add_mutually_exclusive_group()
    app_group.add_argument(
        "--app",
        type=str,
        help="Single app package name (e.g., com.whatsapp)"
    )
    app_group.add_argument(
        "--apps",
        type=str,
        help="Comma-separated list of app package names"
    )
    app_group.add_argument(
        "--default-apps",
        action="store_true",
        help="Use default target apps (WhatsApp, Instagram, Spotify)"
    )

    # Scraping options
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_REVIEW_COUNT,
        help=f"Number of reviews to fetch per app (default: {DEFAULT_REVIEW_COUNT})"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=DEFAULT_LANGUAGE,
        help=f"Language code for reviews (default: {DEFAULT_LANGUAGE})"
    )
    parser.add_argument(
        "--country",
        type=str,
        default=DEFAULT_COUNTRY,
        help=f"Country code for reviews (default: {DEFAULT_COUNTRY})"
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=["newest", "relevant", "rating"],
        default="newest",
        help="Sort order for reviews (default: newest)"
    )

    # Rate limiting
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})"
    )

    # Output options
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (without extension)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data",
        help="Output directory (default: data)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "csv", "both"],
        default="both",
        help="Output format (default: both)"
    )

    # Other options
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    return parser.parse_args()


def get_sort_order(sort_str: str) -> int:
    """Convert sort string to SortOrder constant."""
    sort_map = {
        "newest": SortOrder.NEWEST,
        "relevant": SortOrder.MOST_RELEVANT,
        "rating": SortOrder.RATING,
    }
    return sort_map.get(sort_str, SortOrder.NEWEST)


def get_app_list(args: argparse.Namespace) -> List[str]:
    """Get list of apps to scrape from arguments."""
    if args.app:
        return [args.app]
    elif args.apps:
        return [app.strip() for app in args.apps.split(",")]
    elif args.default_apps:
        return DEFAULT_TARGET_APPS
    else:
        # Default to popular apps if nothing specified
        print("No apps specified. Using default target apps.")
        return DEFAULT_TARGET_APPS


def main():
    """Main entry point for the scraper."""
    global _collected_reviews, _storage

    # Parse arguments
    args = parse_args()

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    # Set up logging
    log_level = "DEBUG" if args.verbose else "INFO"
    logger = setup_logger("main", log_level=log_level)

    # Get list of apps to scrape
    app_list = get_app_list(args)
    logger.info(f"Target apps: {app_list}")
    logger.info(f"Reviews per app: {args.count}")

    # Initialize components
    rate_limiter = RateLimiter(
        min_delay=MIN_DELAY,
        max_delay=MAX_DELAY,
        default_delay=args.delay
    )
    scraper = GooglePlayReviewScraper(rate_limiter=rate_limiter, logger=logger)

    output_dir = Path(args.output_dir)
    _storage = FileStorage(output_dir=output_dir)

    # Determine output formats
    if args.format == "both":
        formats = ["json", "csv"]
    else:
        formats = [args.format]

    # Get sort order
    sort_order = get_sort_order(args.sort)

    # Scrape reviews
    total_target = args.count * len(app_list)
    print(f"\nStarting to collect {args.count} reviews from {len(app_list)} app(s)")
    print(f"Total target: {total_target} reviews\n")

    all_reviews: List[Review] = []

    for app_id in app_list:
        print(f"\n{'='*50}")
        print(f"Scraping: {app_id}")
        print(f"{'='*50}")

        # Fetch app info first
        app_info = scraper.fetch_app_info(app_id)
        if app_info:
            print(f"App: {app_info.title}")
            print(f"Developer: {app_info.developer}")
            print(f"Total reviews available: {app_info.reviews_count:,}")
            print()

        # Fetch reviews (use standard method - handles pagination internally)
        app_reviews = scraper.fetch_reviews(
            app_id=app_id,
            count=args.count,
            lang=args.lang,
            country=args.country,
            sort=sort_order
        )
        _collected_reviews.extend(app_reviews)

        # Save checkpoint if we have enough reviews
        if len(app_reviews) >= CHECKPOINT_INTERVAL:
            _storage.checkpoint_save(
                app_reviews,
                len(app_reviews) // CHECKPOINT_INTERVAL,
                app_id
            )

        all_reviews.extend(app_reviews)
        print(f"\nCollected {len(app_reviews)} reviews from {app_id}")

    # Save all reviews
    print(f"\n{'='*50}")
    print("SAVING RESULTS")
    print(f"{'='*50}")

    if args.output:
        saved_files = _storage.save_reviews(
            all_reviews,
            formats=formats,
            filename_prefix=args.output
        )
    else:
        saved_files = _storage.save_reviews(all_reviews, formats=formats)

    # Print summary
    print(f"\nTotal reviews collected: {len(all_reviews)}")
    print("\nSaved files:")
    for fmt, path in saved_files.items():
        print(f"  {fmt.upper()}: {path}")

    # Print statistics
    if all_reviews:
        ratings = [r.rating for r in all_reviews]
        print(f"\nStatistics:")
        print(f"  Average rating: {sum(ratings)/len(ratings):.2f}")
        print(f"  Rating distribution:")
        for i in range(5, 0, -1):
            count = ratings.count(i)
            pct = count / len(ratings) * 100
            bar = "█" * int(pct / 2)
            print(f"    {i} stars: {count:5d} ({pct:5.1f}%) {bar}")

    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
