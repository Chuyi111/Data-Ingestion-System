# Google Play Review Scraper Documentation

## Overview

A modular, maintainable Python scraper for collecting app reviews from Google Play Store at scale. Built as part of the Sciencia AI Data Ingestion System (Phase I).

---

## Project Structure

```
Data-Ingestion-System/
├── src/
│   ├── config/
│   │   └── settings.py              # Configuration constants and defaults
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── google_play_scraper.py   # Core scraping logic
│   │   └── rate_limiter.py          # Rate limiting utilities
│   ├── models/
│   │   ├── __init__.py
│   │   └── review.py                # Review and AppInfo data models
│   ├── storage/
│   │   ├── __init__.py
│   │   └── file_storage.py          # JSON/CSV export functionality
│   ├── utils/
│   │   ├── __init__.py
│   │   └── logger.py                # Logging configuration
│   └── main.py                      # CLI entry point
├── data/                            # Output directory (created automatically)
├── logs/                            # Log files (created automatically)
├── requirements.txt                 # Python dependencies
└── docs/
    └── scraper_documentation.md     # This file
```

---

## Installation

### Prerequisites
- Python 3.7+

### Setup

```bash
# Navigate to project directory
cd Data-Ingestion-System

# Install dependencies
pip install -r requirements.txt
```

### Dependencies
- `google-play-scraper>=1.2.4` - Core scraping library
- `tqdm>=4.65.0` - Progress bar display

---

## Usage

### Basic Commands

```bash
# Single app - fetch 1000 reviews
python -m src.main --app com.whatsapp --count 1000

# Multiple apps - fetch 500 reviews each
python -m src.main --apps com.whatsapp,com.instagram.android,com.spotify.music --count 500

# Use default target apps (WhatsApp, Instagram, Spotify)
python -m src.main --default-apps --count 1000
```

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--app` | Single app package name (e.g., `com.whatsapp`) | - |
| `--apps` | Comma-separated list of app package names | - |
| `--default-apps` | Use default target apps | False |
| `--count` | Number of reviews to fetch per app | 1000 |
| `--lang` | Language code for reviews | `en` |
| `--country` | Country code for reviews | `us` |
| `--sort` | Sort order: `newest`, `relevant`, `rating` | `newest` |
| `--delay` | Delay between requests (seconds) | 1.5 |
| `--output` | Output filename prefix (without extension) | Auto-generated |
| `--output-dir` | Output directory | `data` |
| `--format` | Output format: `json`, `csv`, `both` | `both` |
| `--no-progress` | Disable progress bar | False |
| `--verbose`, `-v` | Enable verbose logging | False |

### Examples

```bash
# Fetch 5000 reviews from WhatsApp in English (US)
python -m src.main --app com.whatsapp --count 5000 --lang en --country us

# Fetch reviews sorted by rating, output to custom file
python -m src.main --app com.spotify.music --count 2000 --sort rating --output spotify_reviews

# Fetch only JSON output with verbose logging
python -m src.main --app com.instagram.android --count 1000 --format json --verbose

# Slower scraping (3 second delay) to avoid rate limits
python -m src.main --app com.whatsapp --count 10000 --delay 3
```

---

## Output Data Structure

### JSON Format

Reviews are saved as a JSON array with the following structure:

```json
[
  {
    "review_id": "45ec1dd0-2dde-4a0f-a362-48d56b93bb42",
    "app_id": "com.whatsapp",
    "author": "John Doe",
    "rating": 5,
    "content": "Great app! Love the new features.",
    "timestamp": "2026-01-28T15:47:37",
    "thumbs_up": 12,
    "app_version": "2.26.2.72",
    "reply_content": "Thanks for your feedback!",
    "reply_timestamp": "2026-01-29T10:00:00",
    "scraped_at": "2026-01-29T15:47:50.123456"
  }
]
```

### CSV Format

The CSV file contains the same fields as headers:

```csv
review_id,app_id,author,rating,content,timestamp,thumbs_up,app_version,reply_content,reply_timestamp,scraped_at
45ec1dd0-2dde-4a0f-a362-48d56b93bb42,com.whatsapp,John Doe,5,"Great app! Love the new features.",2026-01-28T15:47:37,12,2.26.2.72,"Thanks for your feedback!",2026-01-29T10:00:00,2026-01-29T15:47:50.123456
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `review_id` | string | Unique identifier for the review (UUID format) |
| `app_id` | string | App package name (e.g., `com.whatsapp`) |
| `author` | string | Reviewer's display name |
| `rating` | integer | Star rating (1-5) |
| `content` | string | Review text content |
| `timestamp` | ISO 8601 datetime | When the review was posted |
| `thumbs_up` | integer | Number of "helpful" votes the review received |
| `app_version` | string | App version at time of review (may be null) |
| `reply_content` | string | Developer's reply text (null if no reply) |
| `reply_timestamp` | ISO 8601 datetime | When developer replied (null if no reply) |
| `scraped_at` | ISO 8601 datetime | When this review was scraped |

---

## Configuration

Default settings can be modified in `src/config/settings.py`:

### Target Apps
```python
DEFAULT_TARGET_APPS = [
    "com.whatsapp",
    "com.instagram.android",
    "com.spotify.music",
]
```

### Rate Limiting
```python
MIN_DELAY = 1.0      # Minimum delay between requests (seconds)
MAX_DELAY = 3.0      # Maximum delay between requests (seconds)
DEFAULT_DELAY = 1.5  # Default delay
```

### Retry Settings
```python
MAX_RETRIES = 3           # Max retry attempts for failed requests
RETRY_BASE_DELAY = 2.0    # Base delay for exponential backoff
RETRY_MAX_DELAY = 30.0    # Maximum retry delay
```

### Output Settings
```python
DATA_DIR = Path("data")           # Output directory
CHECKPOINT_INTERVAL = 500         # Save checkpoint every N reviews
```

---

## Features

### Rate Limiting
- Configurable delays between requests (default: 1-3 seconds with jitter)
- Randomized delays to avoid detection patterns
- Respects Google Play rate limits

### Retry Logic
- Automatic retries with exponential backoff
- Handles temporary failures gracefully
- Configurable max retries (default: 3)

### Checkpoint Saving
- Automatically saves progress every 500 reviews
- Enables recovery from interrupted scrapes
- Checkpoint files saved as `checkpoint_{app_id}_{n}.json`

### Graceful Shutdown
- Handles Ctrl+C interrupt signal
- Saves all collected data before exit
- No data loss on interruption

### Deduplication
- Removes duplicate reviews based on `review_id`
- Works for both append mode and merged files

---

## Logging

Logs are written to both console and `logs/scraper.log`:

```
2026-01-29 15:47:34,204 - main - INFO - Target apps: ['com.whatsapp']
2026-01-29 15:47:34,204 - main - INFO - Reviews per app: 500
2026-01-29 15:47:40,583 - main - INFO - App found: WhatsApp Messenger by WhatsApp LLC (1976072 reviews)
2026-01-29 15:47:43,430 - main - INFO - [com.whatsapp] Progress: 200/500 (40.0%)
```

Use `--verbose` flag for DEBUG level logging.

---

## Programmatic Usage

The scraper can also be used as a library:

```python
from src.scraper import GooglePlayReviewScraper, RateLimiter
from src.storage import FileStorage

# Initialize components
rate_limiter = RateLimiter(min_delay=1.0, max_delay=3.0)
scraper = GooglePlayReviewScraper(rate_limiter=rate_limiter)
storage = FileStorage(output_dir="data")

# Fetch app info
app_info = scraper.fetch_app_info("com.whatsapp")
print(f"App: {app_info.title}, Reviews: {app_info.reviews_count}")

# Fetch reviews
reviews = scraper.fetch_reviews(
    app_id="com.whatsapp",
    count=1000,
    lang="en",
    country="us"
)

# Save to files
storage.save_reviews(reviews, formats=["json", "csv"])
```

---

## Troubleshooting

### Common Issues

**Empty results / 0 reviews collected**
- Cause: Rate limiting by Google Play
- Solution: Increase delay with `--delay 3` or wait a few minutes before retrying

**Connection errors**
- Cause: Network issues or temporary blocks
- Solution: Script will auto-retry with exponential backoff (up to 3 times)

**Unicode errors in console**
- Cause: Windows console encoding issues
- Solution: Reviews are saved correctly to files; this is a display-only issue

### Best Practices

1. Start with smaller counts (100-500) to verify connectivity
2. Use delays of 2-3 seconds for large scrapes (10k+)
3. Run during off-peak hours for better success rates
4. Monitor logs for rate limiting warnings

---

## License

Internal use - Sciencia AI Data Ingestion System
