# Labeling System: Technical Roadmap

A detailed design for the sentiment labeling system that turns our review database into training-ready data.

---

## 1. Why We Need This

Star ratings are not sentiment labels. Our data quality analysis made this clear:

- **58.6% of reviews are 5-star**, but a 5-star "ok" and a 5-star "This app completely changed how I communicate with my family" carry fundamentally different sentiment signals
- **24.7% are 1-star**, creating a bimodal distribution that teaches a model about rating extremes, not sentiment
- **39% of reviews are low-signal** (single-word 22.5%, emoji-only 3.3%, repeated characters 1.3%) -- these inflate the dataset without adding learnable signal
- **3-star reviews are only 5.0%** of the data, but they're the most ambiguous and the most valuable to label

If we naively use star ratings as sentiment labels, we get a model that has learned a bimodal proxy, not actual sentiment understanding. Human annotation is the bridge between "we have 87k reviews" and "we have a dataset a model can actually learn from."

The labeling system needs to solve three problems simultaneously:
1. **What to label** -- not all 87k reviews are worth annotator time
2. **How to label** -- consistent, auditable, efficient annotation workflow
3. **How to know it's working** -- quality assurance and monitoring

---

## 2. Label Taxonomy

### 2.1 Sentiment Classes

Five classes rather than three. The difference matters.

| Label | Definition | Example |
|---|---|---|
| `very_negative` | Strong dissatisfaction, anger, explicit complaints about broken functionality | "This app is absolute garbage. Crashes every 5 minutes and lost all my data" |
| `negative` | Mild dissatisfaction, disappointment, minor complaints | "Not great. Used to be better before the last update" |
| `neutral` | No clear sentiment, factual observation, mixed feelings that cancel out | "It works. Does what it says" |
| `positive` | Satisfaction, mild enthusiasm, general approval | "Pretty good app, I use it daily" |
| `very_positive` | Strong enthusiasm, emotional language, explicit recommendation | "Best messaging app ever! Can't imagine life without it" |

**Why 5 classes instead of 3:** A 3-class system (positive/neutral/negative) loses the distinction between "this app is broken and I'm furious" and "meh, not my favorite." That distinction matters for sentiment analysis -- a company monitoring reviews cares about the severity of negative sentiment, not just its presence. The 5-class system captures intensity without being so granular that annotators can't agree.

### 2.2 Confidence Annotation

Each label also gets a confidence flag:

| Confidence | When to Use |
|---|---|
| `high` | Sentiment is unambiguous -- any annotator would agree |
| `medium` | Some ambiguity, but the annotator has a reasonable interpretation |
| `low` | Genuinely ambiguous -- could go either way, annotator is guessing |

This serves two purposes: it lets us weight training examples (high-confidence labels are more trustworthy), and it identifies the boundary cases where inter-annotator disagreement is expected rather than a quality problem.

### 2.3 Edge Cases

Some reviews don't fit cleanly into sentiment:

- **Emoji-only reviews** (3.3% of corpus): Label the sentiment of the emoji. "👍" is `positive`, "💩" is `very_negative`, "😐" is `neutral`. Confidence should reflect how unambiguous the emoji is.
- **Non-English reviews** (15.2% non-ASCII): Label if the annotator can understand them, skip if not. The queue system tracks skips.
- **Spam/gibberish** (repeated characters, 1.3%): Label as `neutral` with `low` confidence, or skip. These are low-value for training regardless.
- **Mixed sentiment**: "Great app but the latest update broke everything" -- label the dominant sentiment. If genuinely split, mark the confidence as `low`.

---

## 3. Schema Extensions

Four new tables that plug into the existing schema. The design follows the same patterns: `TEXT PRIMARY KEY` or `AUTOINCREMENT`, `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, `CHECK` constraints, and `FOREIGN KEY ... ON DELETE CASCADE`.

### 3.1 `annotators` Table

```sql
CREATE TABLE IF NOT EXISTS annotators (
    annotator_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
```

Minimal. We're not building a user management system -- just enough to track who labeled what.

### 3.2 `labels` Table

```sql
CREATE TABLE IF NOT EXISTS labels (
    label_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       TEXT NOT NULL,
    annotator_id    INTEGER NOT NULL,

    sentiment       TEXT NOT NULL
                        CHECK (sentiment IN (
                            'very_negative', 'negative', 'neutral',
                            'positive', 'very_positive'
                        )),
    confidence      TEXT NOT NULL DEFAULT 'high'
                        CHECK (confidence IN ('high', 'medium', 'low')),
    notes           TEXT,

    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (review_id, annotator_id),
    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY (annotator_id) REFERENCES annotators(annotator_id) ON DELETE CASCADE
);
```

Key decisions:
- **`UNIQUE (review_id, annotator_id)`** -- one label per annotator per review. Multiple annotators can label the same review for agreement measurement.
- **`notes` field** -- optional free-text for the annotator to explain ambiguous cases. Useful for adjudication.
- **No `updated_at`** -- labels are immutable once created. If an annotator changes their mind, we delete and re-create (audit trail via `created_at` ordering).

### 3.3 `label_queue` Table

```sql
CREATE TABLE IF NOT EXISTS label_queue (
    queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       TEXT NOT NULL,

    priority_tier   INTEGER NOT NULL CHECK (priority_tier >= 1 AND priority_tier <= 4),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'assigned', 'completed', 'skipped')),
    assigned_to     INTEGER,

    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_at     TIMESTAMP,
    completed_at    TIMESTAMP,

    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES annotators(annotator_id)
);

CREATE INDEX IF NOT EXISTS idx_label_queue_status
    ON label_queue(status, priority_tier);

CREATE INDEX IF NOT EXISTS idx_label_queue_assigned
    ON label_queue(assigned_to, status);
```

The queue is the interface between the sampling strategy and the annotator. Reviews get added to the queue with a priority tier, and annotators pull from it in priority order.

Priority tiers (defined in Section 4):
- **Tier 1**: Long negative reviews (highest value)
- **Tier 2**: Long positive reviews
- **Tier 3**: Ambiguous middle (3-star)
- **Tier 4**: Short-but-meaningful

### 3.4 `label_sessions` Table

```sql
CREATE TABLE IF NOT EXISTS label_sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    annotator_id    INTEGER NOT NULL,

    started_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed', 'abandoned')),

    labels_created  INTEGER NOT NULL DEFAULT 0,
    labels_skipped  INTEGER NOT NULL DEFAULT 0,
    avg_time_per_label_seconds  REAL,

    FOREIGN KEY (annotator_id) REFERENCES annotators(annotator_id) ON DELETE CASCADE
);
```

This mirrors `scrape_runs` -- one row per labeling session, tracking who annotated, how many labels they created, and how long it took. Essential for monitoring annotator productivity and detecting quality issues (an annotator labeling 200 reviews per hour is probably not reading them carefully).

### 3.5 `v_labeled_reviews` View

```sql
CREATE VIEW IF NOT EXISTS v_labeled_reviews AS
SELECT
    l.label_id,
    l.sentiment,
    l.confidence,
    l.annotator_id,
    a.name AS annotator_name,
    r.review_id,
    r.content,
    r.rating,
    r.thumbs_up,
    r.review_timestamp,
    app.app_id,
    app.title AS app_title,
    app.genre AS app_genre,
    LENGTH(r.content) AS content_length,
    CASE
        WHEN r.rating >= 4 THEN 'positive'
        WHEN r.rating = 3 THEN 'neutral'
        ELSE 'negative'
    END AS star_sentiment_bucket,
    CASE
        WHEN l.sentiment IN ('very_positive', 'positive') AND r.rating <= 2 THEN 1
        WHEN l.sentiment IN ('very_negative', 'negative') AND r.rating >= 4 THEN 1
        ELSE 0
    END AS star_label_mismatch
FROM labels l
JOIN reviews r ON l.review_id = r.review_id
JOIN apps app ON r.app_id = app.app_id
JOIN annotators a ON l.annotator_id = a.annotator_id;
```

The `star_label_mismatch` column is particularly useful -- it flags reviews where the human label contradicts the star rating. Those are exactly the cases that justify human labeling over star-based heuristics, and they're the most interesting training examples.

---

## 4. Sampling Strategy

The goal: maximize the learning signal per labeled review.

### 4.1 Priority Tiers

The `v_reviews_sentiment` view already buckets reviews by sentiment and length, so we can directly query for each tier.

**Tier 1: Long Negative (1-2 star, 200+ chars)**

```sql
SELECT review_id FROM v_reviews_sentiment
WHERE sentiment_bucket = 'negative' AND length_bucket = 'long'
ORDER BY LENGTH(content) DESC;
```

These are the richest training examples. Someone who writes three sentences about why an app is broken gives us detailed, learnable signal about what negative sentiment looks like in context.

**Tier 2: Long Positive (4-5 star, 200+ chars)**

```sql
SELECT review_id FROM v_reviews_sentiment
WHERE sentiment_bucket = 'positive' AND length_bucket = 'long'
ORDER BY LENGTH(content) DESC;
```

Balances the negative examples with substantive positive ones. A 5-star review that explains why they love the app is more useful than a 5-star "good."

**Tier 3: Ambiguous Middle (3-star, any length)**

```sql
SELECT review_id FROM v_reviews_sentiment
WHERE sentiment_bucket = 'neutral'
ORDER BY LENGTH(content) DESC;
```

The 3-star reviews (5.0% of corpus) are where star ratings fail as a sentiment proxy. "It's fine I guess" and "I used to love this app but the last update ruined everything" both get 3 stars but carry completely different sentiment.

**Tier 4: Short-but-Meaningful**

```sql
SELECT review_id FROM v_reviews_sentiment
WHERE length_bucket IN ('very_short', 'short')
  AND content NOT IN ('', ' ')
ORDER BY RANDOM();
```

Establishes baseline labels for the low-signal tier. We don't need many of these, but some are useful for teaching the model how to handle short text.

### 4.2 Target Allocation for First Batch

Target: **3,000 labeled reviews** for the first model iteration.

| Tier | Target Count | % of Batch | Source Pool (est.) |
|---|---|---|---|
| 1. Long negative | 800 | 27% | ~4,300 reviews |
| 2. Long positive | 700 | 23% | ~4,800 reviews |
| 3. Ambiguous middle | 500 | 17% | ~4,400 reviews |
| 4. Short meaningful | 400 | 13% | ~34,000 reviews |
| 5. Cross-app balance | 600 | 20% | distributed across 20 apps |

The "cross-app balance" allocation ensures every app has at least 30 labeled reviews. The `v_app_stats` view tells us which apps have the most reviews, so we can distribute the balance allocation proportionally.

### 4.3 Queue Population

A single function that populates `label_queue` from the sampling strategy:

```
populate_queue(target_total=3000, tier_allocation={...})
  -> query v_reviews_sentiment for each tier
  -> exclude already-queued and already-labeled review_ids
  -> apply cross-app balancing from v_app_stats
  -> INSERT INTO label_queue with priority_tier
```

The queue only gets populated once per labeling cycle. After the first 3,000 are labeled and a model is trained, the evaluation results inform the next round of queue population (active learning -- see Section 9).

---

## 5. Labeling Interface Design

CLI-first, matching the existing patterns established in `src/ingestion/cli.py`.

### 5.1 Module Structure

```
src/
  labeling/
    __init__.py
    cli.py            # Entry point (mirrors src/ingestion/cli.py)
    queue_manager.py  # Queue population, assignment, retrieval
    session.py        # Interactive labeling session logic
    sampler.py        # Sampling strategy implementation
    exporter.py       # Training data export
    monitor.py        # Labeling quality monitoring
```

### 5.2 CLI Commands

Following the pattern from `src/ingestion/cli.py` (argparse with mode flags):

```
# Start an interactive labeling session
python -m src.labeling.cli --annotate --name "alice"

# Start with a specific strategy
python -m src.labeling.cli --annotate --name "alice" --strategy negative-first

# Set batch size (reviews per session)
python -m src.labeling.cli --annotate --name "alice" --batch-size 30

# Populate the queue from sampling strategy
python -m src.labeling.cli --populate-queue --target 3000

# Show labeling progress
python -m src.labeling.cli --progress

# Show inter-annotator agreement stats
python -m src.labeling.cli --agreement

# Export labeled data for training
python -m src.labeling.cli --export --format jsonl --split 80/10/10

# Show queue status
python -m src.labeling.cli --queue-status
```

### 5.3 Annotator Workflow

What an annotator sees during `--annotate`:

```
=== Labeling Session #14 ===
Annotator: alice | Strategy: balanced | Batch: 1/30

----------------------------------------------------------------------
Review #1 of 30  |  Priority: Tier 1 (long negative)
App: WhatsApp Messenger (com.whatsapp)  |  Genre: Communication
Rating: ★☆☆☆☆  |  Length: 347 chars  |  Thumbs up: 12
----------------------------------------------------------------------

"I've been using this app for 5 years and the latest update is
terrible. Messages take forever to send, the new UI is confusing,
and worst of all my chat history disappeared after updating. I've
tried reinstalling twice and nothing works. Moving to Telegram."

----------------------------------------------------------------------
Sentiment: [1] very_negative  [2] negative  [3] neutral
           [4] positive       [5] very_positive
           [s] skip           [q] quit session

> 1

Confidence: [h] high  [m] medium  [l] low
> h

Notes (optional, Enter to skip):
>

Labeled: very_negative (high confidence)
Progress: 1/30 | Session total: 1 | Queue remaining: 2,999

----------------------------------------------------------------------
```

Key design decisions:
- **App context is shown** -- genre and developer matter for interpreting sentiment. "This game is too hard" means something different for Clash Royale vs. Google Chrome.
- **Star rating is shown** -- helps the annotator calibrate, but the instructions emphasize that the label should reflect the text, not the stars.
- **Skip option** -- for non-English reviews, gibberish, or cases the annotator genuinely can't label. Tracked in `label_sessions.labels_skipped`.
- **Notes are optional** -- only used when the annotator wants to flag something unusual.
- **Single-keystroke input** -- labeling needs to be fast. No menus, no mouse.

### 5.4 Session Management

Sessions map to `label_sessions` rows. When an annotator starts `--annotate`:

1. Look up or create the annotator in `annotators` table
2. Create a new `label_sessions` row with `status='active'`
3. Pull the next N reviews from `label_queue` where `status='pending'`, ordered by `priority_tier`
4. Mark those queue entries as `status='assigned'`, `assigned_to=annotator_id`
5. Present reviews one at a time, collecting labels
6. On each label: `INSERT INTO labels`, update `label_queue` entry to `status='completed'`
7. On quit or batch complete: update `label_sessions` with final counts and timing

If a session is abandoned (Ctrl+C), the assigned-but-unlabeled queue entries get reset to `status='pending'` on the next session start. This is the same robustness pattern used in the ingestion pipeline's run tracking.

---

## 6. Quality Assurance

### 6.1 Inter-Annotator Agreement

10-15% of queued reviews should be assigned to multiple annotators. This is implemented by inserting the same `review_id` into `label_queue` multiple times with different `assigned_to` values.

Agreement is measured with **Cohen's kappa**, which accounts for chance agreement:

```
kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)
```

Target kappa thresholds:
- **> 0.8**: Excellent agreement. Labels are reliable.
- **0.6 - 0.8**: Substantial agreement. Review disagreements, consider refining guidelines.
- **< 0.6**: Moderate or worse. Pause labeling, retrain annotators, revise taxonomy.

The `--agreement` CLI command computes kappa from the `labels` table by finding `review_id`s with multiple annotator entries.

### 6.2 Gold Standard Reviews

A set of 50-100 pre-labeled "gold" reviews with known-correct sentiment labels. Periodically inserted into an annotator's queue without marking them as gold. If the annotator's label disagrees with the gold label, it's flagged for review.

Implementation: a `is_gold` column on `label_queue` (default 0), and a check after each label submission.

### 6.3 Adjudication

When two annotators disagree on a review:

1. Both labels are stored in `labels` (the `UNIQUE (review_id, annotator_id)` constraint allows this)
2. An adjudication query finds all `review_id`s with conflicting labels
3. A senior annotator (or the project lead) resolves the conflict by adding a third label
4. For training, the majority label is used; if all three differ, the review is excluded or marked low-confidence

```sql
-- Find reviews with disagreement
SELECT review_id, COUNT(DISTINCT sentiment) AS distinct_labels
FROM labels
GROUP BY review_id
HAVING COUNT(DISTINCT sentiment) > 1;
```

### 6.4 Annotator Calibration Report

Detects annotators who skew heavily toward certain labels:

```sql
SELECT
    a.name,
    l.sentiment,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY a.name), 1)
        AS pct
FROM labels l
JOIN annotators a ON l.annotator_id = a.annotator_id
GROUP BY a.name, l.sentiment
ORDER BY a.name, l.sentiment;
```

If an annotator labels 80% of reviews as `positive`, something is wrong -- either with the annotator or with the reviews they're being shown (a sampling strategy that over-indexes on positive text).

---

## 7. Monitoring & Metrics

### 7.1 Architecture

The labeling monitor follows the same architecture as `IngestionMonitor`:

```
compute metrics -> compute deltas -> detect anomalies -> store report -> print alerts
```

Concretely, this means a `LabelingMonitor` class with:
- A `THRESHOLDS` dict (like `IngestionMonitor.THRESHOLDS`)
- An `evaluate_session()` method (like `evaluate_run()`)
- Dataclasses for `LabelingAlert` and `LabelingHealthReport` (like `Alert` and `HealthReport`)
- Storage in a `labeling_metrics` table (like `ingestion_metrics`)

### 7.2 Metrics Tracked

| Metric | What It Catches |
|---|---|
| Labels per session | Annotator going too fast (quality concern) or too slow (UX problem) |
| Average time per label | Baseline ~15-30s; <5s suggests not reading; >120s suggests confusion |
| Skip rate | High skip rate means queue is serving unlabelable reviews |
| Agreement rate (kappa) | Inter-annotator reliability over time |
| Label distribution | Drift toward one class suggests annotator bias or sampling imbalance |
| Queue coverage per app | Are all 20 apps getting labeled, or just the top 5? |
| Low-confidence rate | Rising low-confidence means annotators are unsure -- consider guideline revisions |

### 7.3 Anomaly Detection

Same patterns as the ingestion monitor:

- **Threshold checks**: labels per session drops below minimum, skip rate exceeds 30%
- **Delta comparison**: current session vs previous session and vs average of last 5
- **Z-score outliers**: flag sessions that are >2 standard deviations from the mean on any metric
- **Distribution drift**: compare current label distribution to the running average; alert if any class shifts by more than 10 percentage points

### 7.4 Storage

```sql
CREATE TABLE IF NOT EXISTS labeling_metrics (
    session_id              INTEGER PRIMARY KEY,
    report_json             TEXT NOT NULL,

    labels_created          INTEGER NOT NULL,
    labels_skipped          INTEGER NOT NULL,
    avg_time_per_label      REAL,
    agreement_kappa         REAL,

    label_dist_very_negative REAL,
    label_dist_negative     REAL,
    label_dist_neutral      REAL,
    label_dist_positive     REAL,
    label_dist_very_positive REAL,

    alerts_count            INTEGER DEFAULT 0,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id) REFERENCES label_sessions(session_id) ON DELETE CASCADE
);
```

Same pattern as `ingestion_metrics`: denormalized numeric columns for fast SQL queries, full JSON report for detailed analysis.

---

## 8. Training Data Export

### 8.1 Export Formats

Two formats, matching what common NLP frameworks expect:

**JSONL** (one JSON object per line):
```
{"text": "This app is garbage...", "label": "very_negative", "confidence": "high", "app_id": "com.whatsapp", "rating": 1, "split": "train"}
{"text": "Love this app!", "label": "very_positive", "confidence": "high", "app_id": "com.spotify.music", "rating": 5, "split": "train"}
```

**CSV** (tabular):
```
text,label,confidence,app_id,rating,split
"This app is garbage...",very_negative,high,com.whatsapp,1,train
"Love this app!",very_positive,high,com.spotify.music,5,train
```

### 8.2 Stratified Splitting

The export command produces train/validation/test splits:

```
python -m src.labeling.cli --export --format jsonl --split 80/10/10
```

Splitting is stratified on two dimensions:
1. **By sentiment class** -- each split maintains the same label distribution as the full labeled set
2. **By app** -- each split includes reviews from all 20 apps, not just the high-volume ones

This ensures the validation and test sets are representative of the full data, not just the majority classes or the most-reviewed apps.

### 8.3 Conflict Resolution for Export

When a review has multiple labels from different annotators:
1. If all labels agree: use that label
2. If majority agrees: use the majority label, mark confidence as the minimum of the individual confidences
3. If no majority: exclude from export (or include with `confidence='low'`)

### 8.4 Export Metadata

Each export produces a sidecar JSON file with:
- Export timestamp
- Total examples per split
- Label distribution per split
- Apps represented per split
- Agreement stats for the exported subset
- Any reviews excluded due to unresolved conflicts

---

## 9. Active Learning Loop

This is where labeling connects forward to training and evaluation, creating a feedback cycle.

### 9.1 The Loop

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│   Label     │───>│   Train     │───>│   Evaluate   │
│   3,000     │    │   Model     │    │   Per-App     │
│   reviews   │    │   v1        │    │   Metrics     │
└─────────────┘    └─────────────┘    └──────┬───────┘
       ^                                      │
       │           ┌─────────────────┐        │
       └───────────│  Identify Gaps  │<───────┘
                   │  & Re-populate  │
                   │  Queue          │
                   └─────────────────┘
```

### 9.2 How Evaluation Informs Labeling

After training Model v1 on the first 3,000 labeled reviews and evaluating per-app:

1. **Find the worst-performing apps**: If the model gets 90% accuracy on WhatsApp but 60% on Clash Royale, we need more Clash Royale labels
2. **Find the hardest sentiment class**: If `neutral` has the lowest F1, we need more labeled neutral examples
3. **Find high-uncertainty predictions**: Run the model on unlabeled reviews, find the ones where it's least confident, and add those to the queue

Each of these feeds back into `populate_queue()` with adjusted tier allocations. The second labeling round is informed by where the model is weakest, not by our initial assumptions about what's valuable.

### 9.3 Convergence

Each cycle should improve the model with fewer additional labels:
- **Round 1**: 3,000 labels (stratified sampling, no model guidance)
- **Round 2**: ~1,000 labels (targeted at model weak spots)
- **Round 3**: ~500 labels (fine-tuning on edge cases)

We stop when evaluation metrics plateau -- additional labels no longer improve per-app performance. The monitoring system (Section 7) tracks this trend automatically.

---

## 10. Integration Map

How the labeling system connects to everything we already have:

```
┌──────────────────────────────────────────────────────────────┐
│                    EXISTING INFRASTRUCTURE                    │
│                                                              │
│  ┌──────────┐  ┌───────────┐  ┌────────────┐  ┌──────────┐ │
│  │   apps   │  │  reviews  │  │ scrape_runs│  │ingestion │ │
│  │  table   │  │  table    │  │   table    │  │ _metrics │ │
│  └────┬─────┘  └─────┬─────┘  └────────────┘  └──────────┘ │
│       │              │                                       │
│       │   ┌──────────┴──────────────────┐                   │
│       │   │  v_reviews_sentiment        │                   │
│       │   │  v_reviews_with_app         │                   │
│       │   │  v_app_stats                │                   │
│       │   └──────────┬──────────────────┘                   │
│       │              │                                       │
└───────┼──────────────┼───────────────────────────────────────┘
        │              │
        ▼              ▼
┌──────────────────────────────────────────────────────────────┐
│                    LABELING SYSTEM (NEW)                      │
│                                                              │
│  ┌──────────┐  ┌───────────┐  ┌────────────┐  ┌──────────┐ │
│  │annotators│  │  labels   │  │label_queue │  │ label_   │ │
│  │  table   │  │  table    │  │   table    │  │ sessions │ │
│  └──────────┘  └─────┬─────┘  └────────────┘  └──────────┘ │
│                      │                                       │
│       ┌──────────────┴──────────────────┐                   │
│       │  v_labeled_reviews              │                   │
│       │  (joins labels + reviews + apps)│                   │
│       └──────────────┬──────────────────┘                   │
│                      │                                       │
│  ┌───────────────────┴───────────┐   ┌───────────────────┐  │
│  │  sampler.py                   │   │  monitor.py       │  │
│  │  (uses v_reviews_sentiment    │   │  (mirrors         │  │
│  │   to populate label_queue)    │   │   IngestionMonitor │  │
│  └───────────────────────────────┘   │   architecture)   │  │
│                                      └───────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  exporter.py                                          │  │
│  │  -> JSONL / CSV with stratified train/val/test splits │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Training Pipeline    │
              │  (Phase 3, next)      │
              └───────────────────────┘
```

### What Existing Code Gets Reused

| Existing Component | How It's Reused |
|---|---|
| `v_reviews_sentiment` view | Directly powers the sampling strategy -- filters by sentiment bucket and length bucket |
| `v_reviews_with_app` view | Provides app context (genre, developer) shown to annotators during labeling |
| `v_app_stats` view | Balances the labeling queue across all 20 apps |
| `IngestionMonitor` architecture | `LabelingMonitor` follows the same compute-compare-alert-store pattern |
| `ingestion_metrics` table pattern | `labeling_metrics` uses the same denormalized-columns-plus-JSON design |
| `scrape_runs` tracking pattern | `label_sessions` mirrors it for labeling session audit trails |
| `IngestionReporter` display patterns | Labeling progress and stats output follows the same formatted-print style |
| CLI argparse patterns from `cli.py` | Labeling CLI uses the same mode-flag design (--annotate, --progress, --export, etc.) |
| `DatabaseManager` | Extended with new methods for label CRUD, queue management, and session tracking |

---

## 11. Implementation Sequence

A practical ordering for building this system:

**Step 1: Schema + Database layer**
- Add the 4 new tables and view to `schema.sql`
- Extend `DatabaseManager` with methods for labels, queue, sessions, annotators
- This unblocks everything else

**Step 2: Sampler + Queue population**
- Implement the sampling strategy using existing views
- `populate_queue()` function that fills `label_queue` from `v_reviews_sentiment`
- CLI command: `--populate-queue`

**Step 3: Interactive labeling session**
- The core annotation loop: present review, collect label, store, advance
- Session management (start, resume, abandon)
- CLI command: `--annotate`

**Step 4: Progress + quality reporting**
- Labeling progress dashboard (how many labeled, per-app coverage, queue status)
- Inter-annotator agreement computation
- CLI commands: `--progress`, `--agreement`, `--queue-status`

**Step 5: Monitoring**
- `LabelingMonitor` class with anomaly detection
- `labeling_metrics` table and storage
- Alerts for distribution drift, speed anomalies, agreement drops

**Step 6: Training data export**
- Stratified splitting with conflict resolution
- JSONL and CSV output with metadata sidecar
- CLI command: `--export`

Each step produces a usable increment. After Step 3, we can start labeling. Steps 4-6 make the labeling process more robust and connect it to the training pipeline.
