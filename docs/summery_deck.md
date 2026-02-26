# Data Ingestion System

**Sciencia AI** | Google Play Review Pipeline for Sentiment Analytics

A production-grade data pipeline that collects, stores, monitors, and analyzes app reviews at scale -- designed as the foundation for downstream sentiment labeling and model training.

| Reviews Collected | Apps Monitored | Python Modules | Lines of Code |
|:-----------------:|:--------------:|:--------------:|:-------------:|
| **87,000+**       | **20**         | **25**         | **4,500+**    |

---

## 1. Why Build This?

Sciencia AI needs a reliable way to collect and manage large volumes of user reviews to power sentiment analytics. Without a structured pipeline, data collection is manual, inconsistent, and impossible to scale.

- **No existing dataset** -- needed to build a curated review corpus from scratch
- **Scale matters** -- sentiment models require tens of thousands of labeled examples
- **Data freshness** -- reviews change daily; need continuous ingestion, not one-off scrapes
- **Quality control** -- raw reviews are noisy (39% low-signal), need monitoring
- **Audit trail** -- must know exactly when and how each review was collected

> **End Goal:** A fully automated pipeline: **collect** real user reviews, **store** them in a queryable database, **monitor** data health, and feed clean data into a **sentiment labeling** and **model training** workflow.

> **This Deck Covers:** Phases 0-2 of the project: data source research, scraper development, database design, ingestion automation, and monitoring.

---

## 2. Phased Approach

Each phase was designed to be self-contained and testable before moving to the next. The data source analysis (Phase 0) informed every downstream design decision.

| Phase | Status | Title | Description |
|:-----:|:------:|-------|-------------|
| **0** | Complete | **Data Source Research** | Evaluated 5+ data sources (Twitter/X, Reddit, Amazon, Yelp, Google Play). Selected Google Play reviews based on access, volume, structure, and sentiment signal quality. |
| **1** | Complete | **Core Infrastructure** | Built the scraper, database schema, data models, file storage, and CLI tools. Collected 80k reviews from 20 major apps. Ran data quality analysis. |
| **2** | Complete | **Live Pipeline & Monitoring** | Built the automated ingestion pipeline, scheduler, reporter, and self-monitoring layer with anomaly detection. Grew dataset to 87k+ reviews. |
| **3** | Next | **Labeling & Training** | Build a labeling interface for sentiment annotation, create training/eval splits, train and evaluate sentiment models. |

---

## 3. Data Source Analysis

Before writing any code, we evaluated multiple data sources against criteria critical for sentiment model training.

| Source | Access | Volume | Structure | Sentiment Signal | Verdict |
|--------|--------|--------|-----------|------------------|---------|
| **Google Play** | Free library | Millions | Star rating + text | Strong (1-5 scale) | **Selected** |
| Twitter / X | Paid API ($100+/mo) | High | Unstructured | No built-in labels | Rejected |
| Reddit | Rate-limited API | High | Upvotes only | No sentiment scale | Considered |
| Amazon Reviews | No public API | Billions | Star + text | Strong | Access barrier |
| Yelp | Limited API | Domain-specific | Star + text | Strong | Too narrow |

> **Why Google Play Won:** Free access via `google-play-scraper` library. Built-in 1-5 star ratings serve as natural sentiment labels. Diverse app categories provide cross-domain coverage. High volume ensures enough data for model training.

---

## 4. High-Level Architecture

```
Google Play    -->    Scraper    -->    Pipeline    -->    SQLite DB    -->    Monitor
(Reviews API)     (Rate limiter      (Dedup +         (5 tables,        (Anomaly
                   + Backoff)         Insert)           9 indexes)        detection)
```

### Scraper Layer

`google_play_scraper.py` + `rate_limiter.py` handle API interaction with configurable jitter (1-3s), exponential backoff (3 retries), and batch pagination (200/batch).

### Ingestion Layer

`pipeline.py` + `scheduler.py` wire scraping to storage. Runs every 4 hours, 300 reviews/app/run. Handles dedup, atomic run tracking, graceful shutdown (SIGINT/SIGTERM).

### Monitoring Layer

`monitor.py` evaluates each run: dedup rate, error rate, null rate drift, duration spikes. Stores JSON health reports. Alerts on 6 anomaly types with configurable thresholds.

### Module Structure

```
# 4,500+ lines of Python across 25 files
src/
  config/settings.py       # Central configuration
  scraper/                 # API interaction + rate limiting
  models/review.py         # Review & AppInfo dataclasses
  database/                # Schema, DB manager, CLI
  storage/file_storage.py  # JSON/CSV export + checkpointing
  ingestion/               # Pipeline, scheduler, monitor, reporter
  analysis/                # Data quality + deep statistical analysis
  utils/logger.py          # Structured logging (file + console)
```

---

## 5. Database Schema

### Tables (5 total, 9 indexes, 4 views)

```sql
-- 5 tables, 9 indexes, 4 views

CREATE TABLE apps (
    app_id          TEXT PRIMARY KEY,     -- e.g. 'com.whatsapp'
    title           TEXT NOT NULL,
    developer       TEXT,
    genre           TEXT,
    play_store_rating   REAL,
    play_store_reviews  INTEGER,
    installs            TEXT,
    first_scraped_at    TIMESTAMP,
    last_scraped_at     TIMESTAMP
);

CREATE TABLE reviews (
    review_id       TEXT PRIMARY KEY,     -- Google Play unique ID
    app_id          TEXT NOT NULL REFERENCES apps,
    author          TEXT NOT NULL,
    rating          INTEGER CHECK (1-5),
    content         TEXT NOT NULL,
    review_timestamp    TIMESTAMP,
    scraped_at          TIMESTAMP,
    thumbs_up       INTEGER DEFAULT 0,
    app_version     TEXT,               -- ~14% NULL
    reply_content   TEXT,               -- ~86% NULL
    reply_timestamp TIMESTAMP
);

CREATE TABLE scrape_runs      -- Audit trail: every collection session
CREATE TABLE review_scrape_log -- Junction: which run collected which review
CREATE TABLE ingestion_metrics -- Monitoring: health report per run
```

### Design Principles

- **Normalize apps** -- avoids repeating metadata across 87k rows
- **Denormalize reviews** -- all fields needed for analysis in one table
- **Audit everything** -- scrape_runs + review_scrape_log track provenance
- **Index for queries** -- 9 indexes covering app, rating, time, reply patterns

### Pre-built Views

- **`v_reviews_with_app`** -- joined review + app metadata
- **`v_reviews_sentiment`** -- buckets: positive / neutral / negative
- **`v_app_stats`** -- per-app aggregates
- **`v_daily_stats`** -- daily volume and rating trends

> Database file size: **45.9 MB**

---

## 6. Ingestion Pipeline

```
Scheduler  -->  Fetch App Info  -->  Fetch Reviews  -->  Deduplicate  -->  Bulk Insert  -->  Log + Report
(Every 4h)      (20 apps)           (300/app)           (Check IDs)      (New only)        (Audit trail)
```

### Run #3 -- Full 20-app Ingestion (actual log output)

```
==================================================================
  INGESTION RUN #3  |  2026-02-11 14:40:28
==================================================================
  Status   : completed
  Duration : 9m 2s
  Apps     : 20 processed

  Per-app breakdown:
  App                                 Fetched   New   Skip    Time
  ------------------------------------------------------------------
  WhatsApp Messenger                      400   350     50   17.8s
  Instagram                               400   400      0   21.5s
  TikTok - Videos, Shop & LIVE            400   399      1   18.4s
  Google Chrome                           400   393      7   17.8s
  Gmail                                   400   391      9   24.4s
  YouTube                                 400   398      2   50.6s
  Facebook                                400   400      0   20.4s
  Spotify: Music and Podcasts             400   399      1   19.2s
  Snapchat                                400   398      2   24.1s
  Discord                                 400   397      3   20.2s
    ... 10 more apps ...

  Totals:
    Reviews fetched    : 8,000
    New (inserted)     : 7,336
    Duplicates skipped : 664
    Dedup rate         : 8.3%
==================================================================
```

### Run #4 -- Same apps, 1 hour later (dedup in action)

```
Run #4: 20 apps, 300 reviews each
  com.whatsapp              fetched=400  new=245  skipped=155
  com.instagram.android     fetched=400  new=110  skipped=290
  com.zhiliaoapp.musically  fetched=400  new=19   skipped=381
  com.android.chrome        fetched=400  new=18   skipped=382
  com.google.android.gm     fetched=400  new=10   skipped=390
    ...
```

> **Dedup Rate Behavior:** Run #3 (first run): **8.3%** dedup (mostly new data). Run #4 (1 hour later): significantly higher dedup because most "newest 300" reviews per app were already collected. This is expected and healthy -- the monitor flags it only if it exceeds 99.5%.

### DB Snapshot After Run #3

```
Total reviews  : 87,381
Total apps     : 20
Avg rating     : 3.7
Date range     : 2025-10-27 .. 2026-02-10
DB file size   : 50.82 MB
```

---

## 7. Self-Monitoring & Anomaly Detection

Every ingestion run automatically triggers a health evaluation that computes metrics, compares against historical baselines, and flags anomalies.

### Monitor Architecture

```
Scheduler loop
  --> Pipeline.run()            # scrape + insert
  --> Reporter.report_run()     # console output
  --> Monitor.evaluate_run()    # health analysis
        --> compute metrics        # dedup, error, null rates
        --> compute deltas         # vs previous, vs last-5 avg
        --> detect anomalies       # threshold + z-score checks
        --> store report           # JSON --> ingestion_metrics table
        --> print alerts           # console + log file
```

### Anomaly Detection Thresholds

| Anomaly Check | Threshold | Level |
|---------------|-----------|-------|
| Insert count drops >50% vs avg | `50%` | WARNING |
| Dedup rate >99.5% (stale API) | `99.5%` | WARNING |
| Duration >2x recent average | `2.0x` | WARNING |
| Any app failure | `0%` | WARNING |
| Null rate shifted >5pp | `5.0pp` | INFO |
| Z-score >2.0 std devs | `2.0 sigma` | INFO |

### Sample Health Report (CLI output)

```
======================================================================
  HEALTH REPORT - Run #3  |  2026-02-11 14:49:31
  Status: completed
======================================================================

  Performance:
    Reviews inserted     : 7,336
    Reviews fetched      : 8,000
    Dedup rate           : 8.3%
    Error rate           : 0.0%
    Duration             : 542s
    Ingestion rate       : 885 reviews/min
    Apps                 : 20 ok, 0 failed

  Data Quality:
    app_version null     : 13.8%  (baseline 14.0%, shift -0.2pp)
    reply_content null   : 91.2%  (baseline 86.3%, shift +4.9pp)
    empty content        : 0.3%
    avg content length   : 65 chars  (baseline 68)

  Delta vs Previous Run:
    reviews_inserted     :     7336  (was 50, +14572.0%)
    duration             :      542  (was 21, +2527.1%)

  Alerts: None

======================================================================
```

### Querying Metrics Directly

```sql
-- Runs with anomalies
SELECT run_id, alerts_count, dedup_rate
FROM ingestion_metrics WHERE alerts_count > 0;

-- Dedup rate trend over time
SELECT run_id, dedup_rate, duration_seconds
FROM ingestion_metrics ORDER BY run_id;
```

---

## 8. What We Collected

| Total Reviews | App Categories | Avg Rating | Dev Reply Rate | Avg Chars/Review |
|:------------:|:--------------:|:----------:|:--------------:|:----------------:|
| **87,381**   | **20**         | **3.71**   | **13.7%**      | **67.7**         |

### Rating Distribution (Bimodal)

```
5 stars  ███████████████████████████████████████████████████████████  58.6%
4 stars  ████████                                                     7.3%
3 stars  █████                                                        5.0%
2 stars  ████                                                         4.3%
1 star   █████████████████████████                                   24.7%
```

Strong bimodal pattern: users who love the app (5-star) or hate it (1-star) are most likely to leave reviews. The 3-star "neutral" bucket is thin at 5%, which is typical for app store review distributions.

### Text Quality Breakdown

```
Very short (1-10 chars)    ██████████████████████████████████   34.2%
Short (11-50 chars)        █████████████████████████████████    33.7%
Medium (51-200 chars)      ██████████████████████               22.1%
Long (200+ chars)          ██████████                           10.1%
```

### Quality Flags

| Single-word reviews | Emoji-only reviews | Repeated characters | Non-ASCII content |
|:-------------------:|:------------------:|:-------------------:|:-----------------:|
| **22.5%**           | **3.3%**           | **1.3%**            | **15.2%**         |

---

## 9. Sample Queries & CLI

The system ships with a full CLI for querying, searching, and inspecting the database without writing SQL.

### Database CLI Commands

```bash
# Get database statistics
$ python -m src.database.cli stats

# Query 1-star WhatsApp reviews
$ python -m src.database.cli query \
    --app com.whatsapp --rating 1 --limit 10

# Search for crash reports across all apps
$ python -m src.database.cli search "crash" --limit 20

# Query reviews with developer replies
$ python -m src.database.cli query \
    --app com.spotify.music --has-reply --rating 1
```

### Ingestion CLI Commands

```bash
# Single ingestion run
$ python -m src.ingestion.cli --once

# Start scheduled ingestion (every 4 hours)
$ python -m src.ingestion.cli

# Custom interval and specific apps
$ python -m src.ingestion.cli --interval 3600 \
    --apps com.whatsapp,com.spotify.music

# View run history
$ python -m src.ingestion.cli --history

# View latest health report
$ python -m src.ingestion.cli --health

# View health trend for last 10 runs
$ python -m src.ingestion.cli --health-history 10
```

### Pre-built SQL Views

```sql
-- Sentiment-bucketed view with length categories
SELECT * FROM v_reviews_sentiment
WHERE sentiment_bucket = 'negative'
  AND length_bucket = 'long'
LIMIT 20;

-- Per-app statistics
SELECT app_id, review_count, avg_rating,
       positive_count, negative_count, replied_count
FROM v_app_stats
ORDER BY review_count DESC;

-- Daily review volume trends
SELECT review_date, review_count, avg_rating,
       five_star, one_star
FROM v_daily_stats
ORDER BY review_date DESC LIMIT 30;

-- Reviews with app metadata
SELECT app_title, author, rating, content
FROM v_reviews_with_app
WHERE app_genre = 'Communication'
  AND rating = 1;
```

> **Why Views Matter for Phase 3:** These views provide ready-made query patterns for the labeling interface. `v_reviews_sentiment` maps directly to the labeling task -- surface long negative reviews first for annotation, since they carry the most signal for model training.

---

## 10. Key Design Decisions

### SQLite over PostgreSQL

**Why:** Zero infrastructure, single-file database, perfect for a project that starts local.
**Trade-off:** No concurrent writes, but ingestion is single-threaded so this doesn't matter.
**Mitigation:** Schema is PostgreSQL-compatible for future migration.

### Dedup at Insert Time, Not Fetch Time

**Why:** The Google Play API returns reviews sorted by "newest" -- fetching 300 per app every 4 hours means significant overlap.
**Trade-off:** We fetch data we already have (wasted API calls).
**Rationale:** It's simpler and safer than trying to track "last fetched timestamp" per app, which is fragile.

### Sleep-loop Scheduler over Cron/Celery

**Why:** A simple `while True: run(); sleep(interval)` loop with signal handlers keeps the system self-contained.
**Trade-off:** No distributed scheduling, no retry queue.
**Rationale:** For a single-machine pipeline, this is the right complexity level. Adding Celery would be premature.

### Denormalized Monitoring Metrics

**Why:** Key metrics (dedup_rate, error_rate, etc.) are stored as columns AND as a full JSON report.
**Trade-off:** Slight data duplication.
**Rationale:** Columns allow fast SQL aggregation queries; JSON preserves the complete report for detailed analysis.

### Junction Table for Provenance

**Why:** `review_scrape_log` tracks which run collected which review.
**Trade-off:** Extra writes on every insert.
**Rationale:** Essential for debugging and understanding data freshness. Also enables the backfill feature for historical runs.

### Random Jitter Rate Limiting

**Why:** Delays between API requests use `random(1.0, 3.0)` seconds.
**Trade-off:** Slower than fixed delay but harder to detect/block as automated traffic.
**Rationale:** Protects against API bans while keeping throughput reasonable (~885 reviews/min).

---

## 11. Reflections

### What Worked Well

- **Modular architecture** -- clean separation of scraper, pipeline, storage, and monitoring made it easy to build and test each layer independently
- **Data source research first** -- evaluating sources before coding prevented rework; Google Play was the right choice
- **Incremental build approach** -- Phase 1 (bulk scrape) then Phase 2 (live pipeline) let us validate the schema before adding automation
- **Dedup + audit trail** -- the review_scrape_log table paid dividends immediately when debugging overlapping runs
- **Self-monitoring** -- detecting anomalies automatically caught issues like API staleness early

### What Was Challenging

- **API unpredictability** -- Google Play API sometimes returns more reviews than requested (400 instead of 300), pagination behavior is opaque
- **Data quality noise** -- 39% of reviews are low-signal (single word, emoji-only, repeated characters), requiring careful filtering decisions
- **Dedup rate tuning** -- deciding when high dedup is "normal" vs "API is stale" required empirical observation across multiple runs
- **Schema evolution** -- adding ingestion_metrics after the initial schema required a backfill mechanism for historical data
- **Balancing completeness vs simplicity** -- resisting the urge to over-engineer (no ORM, no task queue, no microservices)

### What I'd Improve

- **Add async I/O** -- concurrent per-app fetching (asyncio or threading) could cut ingestion time from 9 minutes to ~2 minutes
- **Better test coverage** -- unit tests for the pipeline logic, especially edge cases in dedup and error handling
- **Dashboard UI** -- a simple web dashboard to visualize monitoring trends instead of CLI-only output
- **Smarter scheduling** -- adaptive intervals based on per-app review velocity instead of fixed 4-hour cycles
- **Language detection** -- 15.2% of reviews are non-ASCII; adding langdetect would help filter for English-only training data

> Overall, the key lesson was that **investing in data infrastructure pays off early**. The audit trail, monitoring, and schema design all seem like overhead initially, but they became essential when debugging live ingestion runs and preparing data for the labeling phase.

---

## 12. What's Next: Phase 3

### Labeling Interface

Build a web-based annotation tool for human labelers to assign sentiment labels to reviews. Prioritize long negative reviews (highest signal for model training). The `v_reviews_sentiment` view is already designed for this.

### Training Pipeline

Create train/dev/test splits from labeled data. Build a reproducible training pipeline with experiment tracking. Leverage the star ratings as weak supervision labels alongside human annotations.

### Evaluation Loops

Implement model evaluation with per-app breakdowns. Compare model predictions against the bimodal rating distribution observed in the data. Feed evaluation results back into labeling priorities.

### Foundation Already in Place

| Asset | Status | Feeds Into |
|-------|:------:|------------|
| 87k+ reviews in SQLite | Ready | Labeling queue |
| Sentiment-bucketed view | Ready | Annotation priority |
| Star ratings (1-5) | Ready | Weak supervision |
| Quality flags (short/emoji/etc.) | Ready | Filtering noisy data |
| Per-app breakdowns | Ready | Domain-specific eval |
| Continuous ingestion | Running | Fresh training data |
| Monitoring + alerting | Running | Data drift detection |

The ingestion system is designed to keep growing the dataset while Phase 3 work proceeds in parallel -- every 4 hours, new reviews flow in automatically.
