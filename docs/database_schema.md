# Database Schema Documentation

## Overview

This document describes the SQL database schema for the Google Play Reviews Data Ingestion System. The schema is designed for SQLite (primary) with PostgreSQL compatibility in mind.

**Design principles:**
1. Normalize where it aids consistency (apps table), denormalize where it aids query simplicity
2. Use appropriate types for each field
3. Index on common query patterns
4. Allow NULLs only where data is genuinely optional
5. Keep schema simple enough to extend without migration pain

---

## Entity-Relationship Diagram

```
+-------------------+          +---------------------+
|       apps        |          |    scrape_runs      |
+-------------------+          +---------------------+
| app_id (PK)       |          | run_id (PK)         |
| title             |          | started_at          |
| developer         |          | completed_at        |
| genre             |          | status              |
| play_store_rating |          | target_apps         |
| play_store_reviews|          | reviews_per_app     |
| installs          |          | language            |
| first_scraped_at  |          | country             |
| last_scraped_at   |          | total_reviews       |
+--------+----------+          +----------+----------+
         |                                |
         | 1:N                            | 1:N
         |                                |
+--------v----------+          +----------v----------+
|      reviews      |          | review_scrape_log   |
+-------------------+          +---------------------+
| review_id (PK)    |<---------| review_id (FK)      |
| app_id (FK)       |          | run_id (FK)         |
| author            |          +---------------------+
| rating            |               (junction table)
| content           |
| review_timestamp  |
| scraped_at        |
| thumbs_up         |
| app_version       |
| reply_content     |
| reply_timestamp   |
+-------------------+
```

**Relationships:**
- `apps` → `reviews`: One-to-many (one app has many reviews)
- `scrape_runs` → `review_scrape_log`: One-to-many (one run collects many reviews)
- `reviews` → `review_scrape_log`: One-to-many (one review can appear in multiple runs)

---

## Tables

### `apps`

Stores metadata about each app. One row per unique `app_id`.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `app_id` | TEXT | PRIMARY KEY | Package name (e.g., `com.whatsapp`) |
| `title` | TEXT | NOT NULL | App display name |
| `developer` | TEXT | | Developer/publisher name |
| `genre` | TEXT | | App category (e.g., "Communication") |
| `play_store_rating` | REAL | | Current store rating (e.g., 4.5) |
| `play_store_reviews` | INTEGER | | Total review count on Play Store |
| `installs` | TEXT | | Install range string (e.g., "10,000,000+") |
| `first_scraped_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | When app was first scraped |
| `last_scraped_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | When app was last scraped |

**Rationale:** Separating app metadata avoids repeating it across thousands of review rows (each app has ~4000 reviews in our dataset).

---

### `reviews`

Core table containing all review data. One row per review.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `review_id` | TEXT | PRIMARY KEY | Google Play's unique review ID (UUID format) |
| `app_id` | TEXT | NOT NULL, FK → apps | Package name of the reviewed app |
| `author` | TEXT | NOT NULL | Reviewer's display name |
| `rating` | INTEGER | NOT NULL, CHECK (1-5) | Star rating |
| `content` | TEXT | NOT NULL, DEFAULT '' | Review text |
| `review_timestamp` | TIMESTAMP | NOT NULL | When user posted the review |
| `scraped_at` | TIMESTAMP | NOT NULL | When we collected the review |
| `thumbs_up` | INTEGER | NOT NULL, DEFAULT 0 | "Helpful" votes count |
| `app_version` | TEXT | | App version at review time (~14% NULL) |
| `reply_content` | TEXT | | Developer's reply text (~86% NULL) |
| `reply_timestamp` | TIMESTAMP | | When developer replied |

**NULL policy:**
- Core fields (`review_id`, `app_id`, `author`, `rating`, `content`, `review_timestamp`, `scraped_at`, `thumbs_up`) are never NULL
- `app_version` is NULL in ~14% of reviews (Google Play doesn't always provide it)
- `reply_content` and `reply_timestamp` are NULL for ~86% of reviews (most reviews don't receive developer replies)

---

### `scrape_runs`

Tracks each scraping session for auditability and debugging.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `run_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique run identifier |
| `started_at` | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Run start time |
| `completed_at` | TIMESTAMP | | Run completion time |
| `status` | TEXT | NOT NULL, DEFAULT 'running', CHECK | Run status |
| `target_apps` | TEXT | | JSON array of target app_ids |
| `reviews_per_app` | INTEGER | | Configured reviews per app |
| `language` | TEXT | DEFAULT 'en' | Language filter |
| `country` | TEXT | DEFAULT 'us' | Country filter |
| `sort_order` | TEXT | DEFAULT 'newest' | Sort order used |
| `total_reviews_collected` | INTEGER | DEFAULT 0 | Total reviews collected |
| `total_apps_processed` | INTEGER | DEFAULT 0 | Apps successfully processed |
| `error_message` | TEXT | | Error details if failed |

**Status values:** `running`, `completed`, `failed`, `partial`

---

### `review_scrape_log`

Junction table linking reviews to scrape runs. Enables tracking which run collected which reviews.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `review_id` | TEXT | NOT NULL, FK → reviews | Review identifier |
| `run_id` | INTEGER | NOT NULL, FK → scrape_runs | Scrape run identifier |

**Primary key:** Composite (`review_id`, `run_id`)

---

## Indexes

Indexes are designed for common query patterns identified during data analysis:

| Index | Table | Columns | Purpose |
|-------|-------|---------|---------|
| `idx_reviews_app_id` | reviews | `app_id` | Filter by app |
| `idx_reviews_rating` | reviews | `rating` | Filter by rating/sentiment |
| `idx_reviews_app_rating` | reviews | `app_id, rating` | "All 1-star WhatsApp reviews" |
| `idx_reviews_timestamp` | reviews | `review_timestamp` | Time range queries |
| `idx_reviews_scraped_at` | reviews | `scraped_at` | Incremental updates |
| `idx_reviews_app_timestamp` | reviews | `app_id, review_timestamp` | "WhatsApp reviews from last week" |
| `idx_reviews_has_reply` | reviews | `app_id, reply_content IS NOT NULL` | Filter replied/unreplied |
| `idx_reviews_thumbs_up` | reviews | `thumbs_up DESC` | Find "helpful" reviews |
| `idx_scrape_runs_status` | scrape_runs | `status` | Filter runs by status |
| `idx_review_scrape_log_run` | review_scrape_log | `run_id` | Lookup reviews by run |

---

## Views

Pre-built views for common analysis queries:

### `v_reviews_with_app`

Reviews joined with app metadata.

```sql
SELECT
    r.*,
    a.title AS app_title,
    a.developer AS app_developer,
    a.genre AS app_genre
FROM reviews r
JOIN apps a ON r.app_id = a.app_id;
```

### `v_reviews_sentiment`

Reviews with computed sentiment and length buckets.

```sql
SELECT
    *,
    CASE
        WHEN rating >= 4 THEN 'positive'
        WHEN rating = 3 THEN 'neutral'
        ELSE 'negative'
    END AS sentiment_bucket,
    CASE
        WHEN LENGTH(content) <= 10 THEN 'very_short'
        WHEN LENGTH(content) <= 50 THEN 'short'
        WHEN LENGTH(content) <= 200 THEN 'medium'
        ELSE 'long'
    END AS length_bucket
FROM reviews;
```

### `v_app_stats`

Per-app aggregated statistics.

```sql
SELECT
    app_id,
    COUNT(*) AS review_count,
    ROUND(AVG(rating), 2) AS avg_rating,
    SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS positive_count,
    SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative_count,
    SUM(CASE WHEN reply_content IS NOT NULL THEN 1 ELSE 0 END) AS replied_count,
    ROUND(AVG(LENGTH(content)), 1) AS avg_content_length,
    ROUND(AVG(thumbs_up), 2) AS avg_thumbs_up,
    MIN(review_timestamp) AS earliest_review,
    MAX(review_timestamp) AS latest_review
FROM reviews
GROUP BY app_id;
```

### `v_daily_stats`

Daily review volume and rating trends.

```sql
SELECT
    DATE(review_timestamp) AS review_date,
    COUNT(*) AS review_count,
    ROUND(AVG(rating), 2) AS avg_rating,
    SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) AS five_star,
    SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS one_star
FROM reviews
GROUP BY DATE(review_timestamp)
ORDER BY review_date;
```

---

## CLI Usage

The database CLI provides common operations:

```bash
# Initialize database schema
python -m src.database.cli init

# Reset database (drops all data)
python -m src.database.cli init --reset

# Load reviews from JSON file
python -m src.database.cli load data/google_play_reviews.json

# Show database statistics
python -m src.database.cli stats

# Query reviews with filters
python -m src.database.cli query --app com.whatsapp --rating 1 --min-length 100 --limit 10

# Search reviews by content
python -m src.database.cli search "crash" --limit 20

# Output as JSON
python -m src.database.cli query --app com.spotify.music --format json
```

### Query Options

| Option | Description |
|--------|-------------|
| `--app` | Filter by app_id |
| `--rating` | Exact rating match (1-5) |
| `--min-rating` | Minimum rating (inclusive) |
| `--max-rating` | Maximum rating (inclusive) |
| `--has-reply` | Filter by developer reply presence |
| `--min-length` | Minimum content character length |
| `--limit` | Maximum results (default: 10) |
| `--offset` | Pagination offset |
| `--format` | Output format: `text` or `json` |

---

## Python API

```python
from src.database import DatabaseManager

# Initialize
db = DatabaseManager("data/reviews.db")
db.init_schema()

# Load data
db.load_from_json(Path("data/google_play_reviews.json"))

# Query reviews
reviews = db.get_reviews(
    app_id="com.whatsapp",
    min_rating=4,
    min_length=50,
    limit=100
)

# Get statistics
stats = db.get_stats()
print(f"Total reviews: {stats['total_reviews']}")

# Get sentiment distribution
sentiment = db.get_sentiment_distribution(app_id="com.spotify.music")
print(f"Positive: {sentiment['positive']}, Negative: {sentiment['negative']}")

# Search
results = db.search_reviews("battery drain", app_id="com.whatsapp")

# Clean up
db.close()
```

---

## Design Choices for Downstream Analysis

This schema was designed with specific downstream use cases in mind: sentiment labeling, model training, and business analytics. Here's how each design choice supports these goals.

### 1. Sentiment Analysis & Labeling

**Rating as INTEGER with CHECK constraint**
- Enforces valid 1-5 range, preventing data quality issues in training data
- Enables simple sentiment bucketing: `rating >= 4` (positive), `rating = 3` (neutral), `rating <= 2` (negative)
- The `v_reviews_sentiment` view pre-computes these buckets for labeling workflows

**Content stored as TEXT (not truncated)**
- Preserves full review text up to Google Play's 500-char limit
- Allows length-based filtering (`min_length` parameter) to exclude low-signal reviews
- Analysis showed 39% of reviews are very short (≤3 words) — having full text lets labelers decide inclusion criteria

**Thumbs-up count preserved**
- Serves as a proxy for review quality/informativeness
- Negative reviews receive 19x more thumbs-up on average — useful for prioritizing which reviews to label first
- Enables "helpful review" sampling strategies

### 2. Model Training Data Preparation

**Normalized apps table**
- Allows stratified sampling by app (e.g., equal samples per app for balanced training)
- Supports app-aware train/test splits to prevent data leakage
- Enables filtering by app category (`genre`) for domain-specific models

**Timestamps on both review and scrape time**
- `review_timestamp`: Enables temporal train/test splits (train on older, test on newer)
- `scraped_at`: Supports incremental data updates without re-processing

**Developer reply fields**
- Reply presence correlates with negative sentiment (replied reviews avg 2.93 stars vs 3.84 unreplied)
- Can be used as a weak supervision signal or excluded to avoid bias
- Reply text itself could be training data for response generation models

### 3. Efficient Querying for Analysis

**Composite indexes match common query patterns**
- `idx_reviews_app_rating`: Fast retrieval of "all 1-star WhatsApp reviews"
- `idx_reviews_app_timestamp`: Efficient time-range queries per app
- `idx_reviews_has_reply`: Quick filtering for reply-based analysis

**Pre-built views reduce query complexity**
- `v_app_stats`: One query for per-app summary statistics
- `v_daily_stats`: Time series analysis without GROUP BY boilerplate
- `v_reviews_sentiment`: Ready-to-use sentiment labels

**Why denormalized reviews (not separate content/metadata tables)**
- Most queries need content + rating + timestamp together
- Avoids JOINs for the most common access pattern
- Trade-off: ~45MB for 80k reviews is acceptable; would reconsider at 10M+ scale

### 4. Data Quality & Provenance

**Scrape run tracking**
- `scrape_runs` table records parameters used for each collection
- Enables reproducibility: "which reviews came from the Jan 15 scrape?"
- Supports debugging: correlate data quality issues with specific runs

**NULL policy aligned with data reality**
- `app_version` allows NULL (14% missing in source data)
- `reply_content` allows NULL (86% of reviews have no reply — this is expected, not an error)
- Core fields (`rating`, `content`, `author`) are NOT NULL — missing values indicate scraper bugs

### 5. Extensibility for Future Phases

**Schema supports common extensions without migration**

| Future Need | How Schema Supports It |
|-------------|------------------------|
| Language detection | `ALTER TABLE reviews ADD COLUMN detected_language TEXT` |
| Sentiment labels | `ALTER TABLE reviews ADD COLUMN sentiment_label TEXT` |
| Label confidence | `ALTER TABLE reviews ADD COLUMN label_confidence REAL` |
| Multiple labelers | New `labels` table with FK to reviews |
| Model predictions | New `predictions` table with FK to reviews |
| Embeddings | New `embeddings` table or vector DB integration |

**Junction table pattern established**
- `review_scrape_log` demonstrates the many-to-many pattern
- Same pattern applies for `review_labels` (multiple labelers per review)

---

## Data Characteristics

Based on analysis of 80,000 reviews:

| Metric | Value |
|--------|-------|
| Total reviews | 79,995 |
| Total apps | 20 |
| Average rating | 3.71 |
| Median rating | 5.0 |
| Date range | 100 days |
| DB file size | 45.88 MB |

### Sentiment Distribution

| Bucket | Count | Percentage |
|--------|-------|------------|
| Positive (4-5 stars) | 52,882 | 66.1% |
| Neutral (3 stars) | 3,924 | 4.9% |
| Negative (1-2 stars) | 23,189 | 29.0% |

### Field Completeness

| Field | Fill Rate |
|-------|-----------|
| Core fields | 100% |
| `app_version` | 85.9% |
| `reply_content` | 13.9% |

---

## Schema Migration Notes

### Adding new columns

```sql
-- Example: adding a language detection field
ALTER TABLE reviews ADD COLUMN detected_language TEXT;
```

### PostgreSQL compatibility

For PostgreSQL deployment, adjust:
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
- `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` → `TIMESTAMP DEFAULT NOW()`

### Full-text search

For production search, consider adding FTS5:

```sql
CREATE VIRTUAL TABLE reviews_fts USING fts5(
    content,
    content='reviews',
    content_rowid='rowid'
);
```

---

## File Locations

| File | Description |
|------|-------------|
| `src/database/schema.sql` | SQL schema definition |
| `src/database/db_manager.py` | Python database manager |
| `src/database/cli.py` | Command-line interface |
| `data/reviews.db` | SQLite database file (default location) |
