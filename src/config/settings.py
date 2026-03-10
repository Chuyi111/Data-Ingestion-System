"""
Configuration settings for Google Play Review Scraper.

This module contains all configurable parameters for the scraper including
target apps, rate limiting, output paths, and retry logic settings.
"""

from pathlib import Path
from typing import Dict, List

# =============================================================================
# TARGET APPS
# =============================================================================
# Popular apps with high review volumes for testing
DEFAULT_TARGET_APPS: List[str] = [
    "com.whatsapp",
    "com.instagram.android",
    "com.zhiliaoapp.musically",
    "com.android.chrome",
    "com.google.android.gm",
    "com.google.android.youtube",
    "com.google.android.apps.maps",
    "com.facebook.katana",
    "com.facebook.orca",
    "com.spotify.music",
    "com.snapchat.android",
    "com.discord",
    "com.amazon.mShop.android.shopping",
    "org.telegram.messenger",
    "com.reddit.frontpage",
    "com.google.android.apps.photos",
    "com.google.android.apps.docs",
    "com.squareup.cash",
    "com.ubercab",
    "com.supercell.clashroyale"
]

# =============================================================================
# SCRAPING SETTINGS
# =============================================================================
# Number of reviews to fetch per request batch (max supported by API)
BATCH_SIZE: int = 200

# Default number of reviews to fetch per app
DEFAULT_REVIEW_COUNT: int = 1000

# Default language for reviews
DEFAULT_LANGUAGE: str = "en"

# Default country code
DEFAULT_COUNTRY: str = "us"

# =============================================================================
# RATE LIMITING
# =============================================================================
# Minimum delay between requests (seconds)
MIN_DELAY: float = 1.0

# Maximum delay between requests (seconds)
MAX_DELAY: float = 3.0

# Default delay between requests (seconds)
DEFAULT_DELAY: float = 1.5

# =============================================================================
# RETRY SETTINGS
# =============================================================================
# Maximum number of retry attempts for failed requests
MAX_RETRIES: int = 3

# Base delay for exponential backoff (seconds)
RETRY_BASE_DELAY: float = 2.0

# Maximum delay for exponential backoff (seconds)
RETRY_MAX_DELAY: float = 30.0

# =============================================================================
# OUTPUT SETTINGS
# =============================================================================
# Base directory for data output (relative to project root)
DATA_DIR: Path = Path("data")

# Default output filename prefix
DEFAULT_OUTPUT_PREFIX: str = "google_play_reviews"

# Supported output formats
SUPPORTED_FORMATS: List[str] = ["json", "csv"]

# Save progress every N reviews
CHECKPOINT_INTERVAL: int = 500

# =============================================================================
# LOGGING SETTINGS
# =============================================================================
# Log directory (relative to project root)
LOG_DIR: Path = Path("logs")

# Log file name
LOG_FILE: str = "scraper.log"

# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL: str = "INFO"

# Log format
LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# =============================================================================
# SORTING OPTIONS
# =============================================================================
# Available sort options for reviews
class SortOrder:
    """Sort order options for Google Play reviews."""
    MOST_RELEVANT = 0  # Default - most relevant reviews
    NEWEST = 1         # Newest reviews first
    RATING = 2         # Sorted by rating


# =============================================================================
# INGESTION SETTINGS
# =============================================================================
# Reviews to fetch per app per ingestion run (smaller than bulk scrape)
INGESTION_REVIEWS_PER_APP: int = 300

# Interval between scheduled runs (seconds). 4 hours = 14400
INGESTION_INTERVAL_SECONDS: int = 14400

# Database path for ingestion (reuses same DB)
INGESTION_DB_PATH: str = "data/reviews.db"

# Separate log file for ingestion runs
INGESTION_LOG_FILE: str = "ingestion.log"

# =============================================================================
# LABELING SETTINGS
# =============================================================================
# Database path for labeling (same DB as ingestion)
LABELING_DB_PATH: str = "data/reviews.db"

# Reviews per labeling session batch
LABELING_DEFAULT_BATCH_SIZE: int = 20

# Default sampling strategy
LABELING_DEFAULT_STRATEGY: str = "balanced"

# Target total reviews in labeling queue
LABELING_TARGET_QUEUE_SIZE: int = 3000

# Per-tier allocation for queue population
LABELING_TIER_ALLOCATION: Dict[int, int] = {
    1: 800,   # Long negative (1-2 star, 200+ chars)
    2: 700,   # Long positive (4-5 star, 200+ chars)
    3: 500,   # Ambiguous middle (3-star, any length)
    4: 400,   # Short meaningful
}

# Reserve for cross-app balancing (min 30 per app)
LABELING_CROSS_APP_RESERVE: int = 600

# Fraction of reviews labeled by multiple annotators (for agreement)
LABELING_OVERLAP_PCT: float = 0.10

# Separate log file for labeling
LABELING_LOG_FILE: str = "labeling.log"

# Training data export directory
LABELING_EXPORT_DIR: str = "data/training"
