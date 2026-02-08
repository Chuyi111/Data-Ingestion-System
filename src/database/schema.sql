-- ============================================================================
-- Google Play Reviews Database Schema
-- Data Ingestion System - Phase I
-- ============================================================================
--
-- Design principles:
--   1. Normalize where it aids consistency (apps table), denormalize where it
--      aids query simplicity (reviews contain all fields needed for analysis)
--   2. Use appropriate types: TEXT for unbounded strings, INTEGER for counts,
--      REAL for ratings (though 1-5 integers), TIMESTAMP for dates
--   3. Index on common query patterns: app lookups, time ranges, ratings
--   4. Allow NULLs only where data is genuinely optional (replies, app_version)
--   5. Keep schema simple enough to extend without migrations pain
--
-- Compatible with: SQLite (primary), PostgreSQL (with minor type adjustments)
-- ============================================================================

-- ============================================================================
-- APPS TABLE
-- ============================================================================
-- Stores metadata about each app. One row per app_id.
-- Separating this avoids repeating app metadata across 4000+ review rows.

CREATE TABLE IF NOT EXISTS apps (
    -- Primary key: the package name (e.g., 'com.whatsapp')
    app_id          TEXT PRIMARY KEY,

    -- App metadata (from Google Play)
    title           TEXT NOT NULL,
    developer       TEXT,
    genre           TEXT,

    -- Aggregate stats (updated on each scrape)
    play_store_rating   REAL,           -- Current store rating (e.g., 4.5)
    play_store_reviews  INTEGER,        -- Total review count on store
    installs            TEXT,           -- Install range string ('10,000,000+')

    -- Tracking
    first_scraped_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_scraped_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- REVIEWS TABLE
-- ============================================================================
-- Core table: one row per review. This is where the bulk of data lives.
-- Designed for fast filtering by app, rating, time, and text search.

CREATE TABLE IF NOT EXISTS reviews (
    -- Primary key: Google Play's unique review identifier
    review_id       TEXT PRIMARY KEY,

    -- Foreign key to apps table
    app_id          TEXT NOT NULL,

    -- Review content
    author          TEXT NOT NULL,
    rating          INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    content         TEXT NOT NULL DEFAULT '',

    -- Timestamps
    review_timestamp    TIMESTAMP NOT NULL,     -- When user posted the review
    scraped_at          TIMESTAMP NOT NULL,     -- When we collected it

    -- Metadata
    thumbs_up       INTEGER NOT NULL DEFAULT 0,
    app_version     TEXT,                       -- NULL in ~14% of reviews

    -- Developer reply (NULL if no reply; ~86% are NULL)
    reply_content       TEXT,
    reply_timestamp     TIMESTAMP,

    -- Foreign key constraint
    FOREIGN KEY (app_id) REFERENCES apps(app_id) ON DELETE CASCADE
);

-- ============================================================================
-- SCRAPE_RUNS TABLE
-- ============================================================================
-- Tracks each scraping session for auditability and debugging.
-- Useful for understanding data provenance and identifying issues.

CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Run parameters
    started_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    status          TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'completed', 'failed', 'partial')),

    -- Configuration used
    target_apps     TEXT,           -- JSON array of app_ids targeted
    reviews_per_app INTEGER,
    language        TEXT DEFAULT 'en',
    country         TEXT DEFAULT 'us',
    sort_order      TEXT DEFAULT 'newest',

    -- Results
    total_reviews_collected INTEGER DEFAULT 0,
    total_apps_processed    INTEGER DEFAULT 0,
    error_message           TEXT
);

-- ============================================================================
-- REVIEW_SCRAPE_LOG TABLE
-- ============================================================================
-- Junction table linking reviews to scrape runs.
-- Allows tracking which run collected which reviews (for incremental updates).

CREATE TABLE IF NOT EXISTS review_scrape_log (
    review_id       TEXT NOT NULL,
    run_id          INTEGER NOT NULL,

    PRIMARY KEY (review_id, run_id),
    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES scrape_runs(run_id) ON DELETE CASCADE
);

-- ============================================================================
-- INDEXES
-- ============================================================================
-- Designed for common query patterns identified during analysis:
--   - Filter by app
--   - Filter by rating (sentiment buckets)
--   - Filter by time range
--   - Find reviews with/without replies
--   - Text search on content

-- App-based queries (most common)
CREATE INDEX IF NOT EXISTS idx_reviews_app_id
    ON reviews(app_id);

-- Rating-based queries (sentiment analysis)
CREATE INDEX IF NOT EXISTS idx_reviews_rating
    ON reviews(rating);

-- Composite: app + rating (e.g., "all 1-star reviews for WhatsApp")
CREATE INDEX IF NOT EXISTS idx_reviews_app_rating
    ON reviews(app_id, rating);

-- Time-based queries (temporal analysis, incremental updates)
CREATE INDEX IF NOT EXISTS idx_reviews_timestamp
    ON reviews(review_timestamp);

CREATE INDEX IF NOT EXISTS idx_reviews_scraped_at
    ON reviews(scraped_at);

-- Composite: app + time (e.g., "WhatsApp reviews from last week")
CREATE INDEX IF NOT EXISTS idx_reviews_app_timestamp
    ON reviews(app_id, review_timestamp);

-- Reply presence (for filtering replied/unreplied)
CREATE INDEX IF NOT EXISTS idx_reviews_has_reply
    ON reviews(app_id, reply_content IS NOT NULL);

-- Thumbs up (for finding "helpful" reviews)
CREATE INDEX IF NOT EXISTS idx_reviews_thumbs_up
    ON reviews(thumbs_up DESC);

-- Scrape run tracking
CREATE INDEX IF NOT EXISTS idx_scrape_runs_status
    ON scrape_runs(status);

CREATE INDEX IF NOT EXISTS idx_review_scrape_log_run
    ON review_scrape_log(run_id);

-- ============================================================================
-- VIEWS
-- ============================================================================
-- Convenience views for common analysis queries.

-- View: Reviews with app metadata joined
CREATE VIEW IF NOT EXISTS v_reviews_with_app AS
SELECT
    r.*,
    a.title AS app_title,
    a.developer AS app_developer,
    a.genre AS app_genre
FROM reviews r
JOIN apps a ON r.app_id = a.app_id;

-- View: Sentiment-bucketed reviews
CREATE VIEW IF NOT EXISTS v_reviews_sentiment AS
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

-- View: App-level aggregates
CREATE VIEW IF NOT EXISTS v_app_stats AS
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

-- View: Daily review volume and rating trends
CREATE VIEW IF NOT EXISTS v_daily_stats AS
SELECT
    DATE(review_timestamp) AS review_date,
    COUNT(*) AS review_count,
    ROUND(AVG(rating), 2) AS avg_rating,
    SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) AS five_star,
    SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS one_star
FROM reviews
GROUP BY DATE(review_timestamp)
ORDER BY review_date;
