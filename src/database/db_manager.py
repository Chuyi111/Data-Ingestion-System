"""
Database Manager for Google Play Reviews.

Handles database initialization, data loading, and common queries.
Compatible with SQLite (default) and PostgreSQL.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from src.models.review import Review, AppInfo
from src.utils.logger import get_logger


class DatabaseManager:
    """
    Manages database connections and operations for review data.

    Handles schema initialization, bulk loading, and querying.
    """

    def __init__(self, db_path: str = "data/reviews.db"):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("database")
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -------------------------------------------------------------------------
    # Schema management
    # -------------------------------------------------------------------------

    def init_schema(self):
        """Initialize database schema from SQL file."""
        schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = self.connect()
        conn.executescript(schema_sql)
        conn.commit()
        self.logger.info(f"Database schema initialized: {self.db_path}")

    def reset_database(self):
        """Drop all tables and reinitialize schema."""
        conn = self.connect()
        # Get all table names
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

        for (table_name,) in tables:
            if table_name != "sqlite_sequence":
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        conn.commit()
        self.init_schema()
        self.logger.info("Database reset complete")

    # -------------------------------------------------------------------------
    # Data loading
    # -------------------------------------------------------------------------

    def insert_app(self, app_info: AppInfo) -> bool:
        """
        Insert or update app metadata.

        Args:
            app_info: AppInfo object

        Returns:
            True if inserted/updated successfully
        """
        conn = self.connect()
        try:
            conn.execute("""
                INSERT INTO apps (
                    app_id, title, developer, genre,
                    play_store_rating, play_store_reviews, installs,
                    first_scraped_at, last_scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_id) DO UPDATE SET
                    title = excluded.title,
                    developer = excluded.developer,
                    genre = excluded.genre,
                    play_store_rating = excluded.play_store_rating,
                    play_store_reviews = excluded.play_store_reviews,
                    installs = excluded.installs,
                    last_scraped_at = excluded.last_scraped_at
            """, (
                app_info.app_id,
                app_info.title,
                app_info.developer,
                app_info.genre,
                app_info.rating,
                app_info.reviews_count,
                app_info.installs,
                app_info.scraped_at.isoformat(),
                app_info.scraped_at.isoformat(),
            ))
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Failed to insert app {app_info.app_id}: {e}")
            return False

    def insert_review(self, review: Review) -> bool:
        """
        Insert a single review.

        Args:
            review: Review object

        Returns:
            True if inserted successfully (or already exists)
        """
        conn = self.connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO reviews (
                    review_id, app_id, author, rating, content,
                    review_timestamp, scraped_at, thumbs_up, app_version,
                    reply_content, reply_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                review.review_id,
                review.app_id,
                review.author,
                review.rating,
                review.content,
                review.timestamp.isoformat() if review.timestamp else None,
                review.scraped_at.isoformat() if review.scraped_at else None,
                review.thumbs_up,
                review.app_version,
                review.reply_content,
                review.reply_timestamp.isoformat() if review.reply_timestamp else None,
            ))
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Failed to insert review {review.review_id}: {e}")
            return False

    def insert_reviews_bulk(
        self,
        reviews: List[Review],
        batch_size: int = 1000
    ) -> Tuple[int, int]:
        """
        Bulk insert reviews for performance.

        Args:
            reviews: List of Review objects
            batch_size: Number of reviews per batch

        Returns:
            Tuple of (inserted_count, skipped_count)
        """
        conn = self.connect()
        inserted = 0
        skipped = 0

        for i in range(0, len(reviews), batch_size):
            batch = reviews[i:i + batch_size]
            try:
                cursor = conn.executemany("""
                    INSERT OR IGNORE INTO reviews (
                        review_id, app_id, author, rating, content,
                        review_timestamp, scraped_at, thumbs_up, app_version,
                        reply_content, reply_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    (
                        r.review_id,
                        r.app_id,
                        r.author,
                        r.rating,
                        r.content,
                        r.timestamp.isoformat() if r.timestamp else None,
                        r.scraped_at.isoformat() if r.scraped_at else None,
                        r.thumbs_up,
                        r.app_version,
                        r.reply_content,
                        r.reply_timestamp.isoformat() if r.reply_timestamp else None,
                    )
                    for r in batch
                ])
                conn.commit()
                inserted += cursor.rowcount
                skipped += len(batch) - cursor.rowcount
            except Exception as e:
                self.logger.error(f"Batch insert failed: {e}")
                skipped += len(batch)

        self.logger.info(f"Bulk insert complete: {inserted} inserted, {skipped} skipped")
        return inserted, skipped

    def load_from_json(self, json_path: Path) -> Tuple[int, int]:
        """
        Load reviews from a JSON file into the database.

        Args:
            json_path: Path to JSON file with review data

        Returns:
            Tuple of (inserted_count, skipped_count)
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        reviews = [Review.from_dict(r) for r in data]
        self.logger.info(f"Loaded {len(reviews)} reviews from {json_path}")

        # Extract unique apps and insert them first
        apps_seen = set()
        for r in reviews:
            if r.app_id not in apps_seen:
                # Create minimal AppInfo (we don't have full metadata in review JSON)
                self.connect().execute("""
                    INSERT OR IGNORE INTO apps (app_id, title, developer)
                    VALUES (?, ?, ?)
                """, (r.app_id, r.app_id, "Unknown"))
                apps_seen.add(r.app_id)
        self.connect().commit()

        return self.insert_reviews_bulk(reviews)

    # -------------------------------------------------------------------------
    # Scrape run tracking
    # -------------------------------------------------------------------------

    def start_scrape_run(
        self,
        target_apps: List[str],
        reviews_per_app: int,
        language: str = "en",
        country: str = "us",
        sort_order: str = "newest"
    ) -> int:
        """
        Record the start of a scrape run.

        Returns:
            run_id for this scrape session
        """
        conn = self.connect()
        cursor = conn.execute("""
            INSERT INTO scrape_runs (
                target_apps, reviews_per_app, language, country, sort_order
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            json.dumps(target_apps),
            reviews_per_app,
            language,
            country,
            sort_order,
        ))
        conn.commit()
        return cursor.lastrowid

    def complete_scrape_run(
        self,
        run_id: int,
        total_reviews: int,
        total_apps: int,
        status: str = "completed",
        error_message: Optional[str] = None
    ):
        """Record the completion of a scrape run."""
        conn = self.connect()
        conn.execute("""
            UPDATE scrape_runs SET
                completed_at = CURRENT_TIMESTAMP,
                status = ?,
                total_reviews_collected = ?,
                total_apps_processed = ?,
                error_message = ?
            WHERE run_id = ?
        """, (status, total_reviews, total_apps, error_message, run_id))
        conn.commit()

    # -------------------------------------------------------------------------
    # Querying
    # -------------------------------------------------------------------------

    def get_review_count(self, app_id: Optional[str] = None) -> int:
        """Get total review count, optionally filtered by app."""
        conn = self.connect()
        if app_id:
            result = conn.execute(
                "SELECT COUNT(*) FROM reviews WHERE app_id = ?", (app_id,)
            ).fetchone()
        else:
            result = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()
        return result[0]

    def get_reviews(
        self,
        app_id: Optional[str] = None,
        rating: Optional[int] = None,
        min_rating: Optional[int] = None,
        max_rating: Optional[int] = None,
        has_reply: Optional[bool] = None,
        min_length: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Query reviews with flexible filters.

        Args:
            app_id: Filter by app
            rating: Exact rating match
            min_rating: Minimum rating (inclusive)
            max_rating: Maximum rating (inclusive)
            has_reply: Filter by reply presence
            min_length: Minimum content length
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of review dictionaries
        """
        conn = self.connect()
        conditions = []
        params = []

        if app_id:
            conditions.append("app_id = ?")
            params.append(app_id)
        if rating is not None:
            conditions.append("rating = ?")
            params.append(rating)
        if min_rating is not None:
            conditions.append("rating >= ?")
            params.append(min_rating)
        if max_rating is not None:
            conditions.append("rating <= ?")
            params.append(max_rating)
        if has_reply is not None:
            if has_reply:
                conditions.append("reply_content IS NOT NULL")
            else:
                conditions.append("reply_content IS NULL")
        if min_length is not None:
            conditions.append("LENGTH(content) >= ?")
            params.append(min_length)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        query = f"""
            SELECT * FROM reviews
            WHERE {where_clause}
            ORDER BY review_timestamp DESC
            LIMIT ? OFFSET ?
        """

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_app_stats(self) -> List[Dict[str, Any]]:
        """Get aggregated stats for all apps."""
        conn = self.connect()
        rows = conn.execute("SELECT * FROM v_app_stats").fetchall()
        return [dict(row) for row in rows]

    def get_daily_stats(self) -> List[Dict[str, Any]]:
        """Get daily review volume and rating trends."""
        conn = self.connect()
        rows = conn.execute("SELECT * FROM v_daily_stats").fetchall()
        return [dict(row) for row in rows]

    def get_sentiment_distribution(
        self,
        app_id: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Get sentiment bucket distribution.

        Returns:
            Dict with keys 'positive', 'neutral', 'negative'
        """
        conn = self.connect()
        query = """
            SELECT
                SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) AS neutral,
                SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative
            FROM reviews
        """
        if app_id:
            query += " WHERE app_id = ?"
            row = conn.execute(query, (app_id,)).fetchone()
        else:
            row = conn.execute(query).fetchone()

        return {
            "positive": row["positive"],
            "neutral": row["neutral"],
            "negative": row["negative"],
        }

    def search_reviews(
        self,
        query: str,
        app_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search reviews by content (simple LIKE query).

        For production, consider FTS5 for full-text search.
        """
        conn = self.connect()
        params = [f"%{query}%"]

        sql = "SELECT * FROM reviews WHERE content LIKE ?"
        if app_id:
            sql += " AND app_id = ?"
            params.append(app_id)
        sql += " ORDER BY thumbs_up DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Database info
    # -------------------------------------------------------------------------

    def get_existing_review_ids(self, review_ids: set) -> set:
        """
        Return the subset of review_ids that already exist in the database.

        Batches lookups in chunks of 900 to stay within SQLite's
        variable limit (999).
        """
        conn = self.connect()
        existing = set()
        ids_list = list(review_ids)

        for i in range(0, len(ids_list), 900):
            chunk = ids_list[i:i + 900]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT review_id FROM reviews WHERE review_id IN ({placeholders})",
                chunk
            ).fetchall()
            existing.update(row[0] for row in rows)

        return existing

    def log_review_scrape_bulk(self, review_ids: List[str], run_id: int) -> int:
        """
        Bulk-insert entries into review_scrape_log linking reviews to a run.

        Uses INSERT OR IGNORE on the composite PK (review_id, run_id).

        Returns:
            Number of log entries inserted
        """
        if not review_ids:
            return 0

        conn = self.connect()
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO review_scrape_log (review_id, run_id) VALUES (?, ?)",
            [(rid, run_id) for rid in review_ids]
        )
        conn.commit()
        return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Get overall database statistics."""
        conn = self.connect()

        total_reviews = conn.execute(
            "SELECT COUNT(*) FROM reviews"
        ).fetchone()[0]

        total_apps = conn.execute(
            "SELECT COUNT(*) FROM apps"
        ).fetchone()[0]

        avg_rating = conn.execute(
            "SELECT AVG(rating) FROM reviews"
        ).fetchone()[0]

        date_range = conn.execute("""
            SELECT MIN(review_timestamp), MAX(review_timestamp)
            FROM reviews
        """).fetchone()

        return {
            "total_reviews": total_reviews,
            "total_apps": total_apps,
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
            "earliest_review": date_range[0],
            "latest_review": date_range[1],
            "db_file_size_mb": round(
                self.db_path.stat().st_size / 1024 / 1024, 2
            ) if self.db_path.exists() else 0,
        }

    # -------------------------------------------------------------------------
    # Labeling: annotators
    # -------------------------------------------------------------------------

    def get_or_create_annotator(self, name: str) -> int:
        """Get existing annotator by name, or create one. Returns annotator_id."""
        conn = self.connect()
        conn.execute(
            "INSERT OR IGNORE INTO annotators (name) VALUES (?)", (name,)
        )
        conn.commit()
        row = conn.execute(
            "SELECT annotator_id FROM annotators WHERE name = ?", (name,)
        ).fetchone()
        return row["annotator_id"]

    def get_annotator(self, annotator_id: int) -> Optional[Dict[str, Any]]:
        """Get annotator by ID."""
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM annotators WHERE annotator_id = ?", (annotator_id,)
        ).fetchone()
        return dict(row) if row else None

    # -------------------------------------------------------------------------
    # Labeling: labels
    # -------------------------------------------------------------------------

    def insert_label(
        self,
        review_id: str,
        annotator_id: int,
        sentiment: str,
        confidence: str = "high",
        notes: Optional[str] = None,
    ) -> int:
        """
        Insert a sentiment label for a review.

        Returns:
            label_id of the new label
        """
        conn = self.connect()
        cursor = conn.execute("""
            INSERT INTO labels (review_id, annotator_id, sentiment, confidence, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (review_id, annotator_id, sentiment, confidence, notes))
        conn.commit()
        return cursor.lastrowid

    def get_labels_for_review(self, review_id: str) -> List[Dict[str, Any]]:
        """Get all labels for a specific review."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM labels WHERE review_id = ?", (review_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get_label_count(self, annotator_id: Optional[int] = None) -> int:
        """Get total label count, optionally filtered by annotator."""
        conn = self.connect()
        if annotator_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM labels WHERE annotator_id = ?",
                (annotator_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM labels").fetchone()
        return row[0]

    # -------------------------------------------------------------------------
    # Labeling: queue
    # -------------------------------------------------------------------------

    def populate_queue(
        self, review_ids_with_tiers: List[Tuple[str, int]]
    ) -> int:
        """
        Bulk-insert reviews into the label queue.

        Args:
            review_ids_with_tiers: List of (review_id, priority_tier) tuples

        Returns:
            Number of queue entries inserted
        """
        if not review_ids_with_tiers:
            return 0

        conn = self.connect()
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO label_queue (review_id, priority_tier) VALUES (?, ?)",
            review_ids_with_tiers
        )
        conn.commit()
        return cursor.rowcount

    def fetch_queue_batch(
        self, batch_size: int, annotator_id: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch and assign the next batch of reviews from the queue.

        Selects pending items ordered by priority tier, marks them as
        assigned to the annotator, and returns them joined with review
        and app context.
        """
        conn = self.connect()

        # Get pending queue items
        queue_rows = conn.execute("""
            SELECT queue_id, review_id, priority_tier
            FROM label_queue
            WHERE status = 'pending'
            ORDER BY priority_tier ASC, queue_id ASC
            LIMIT ?
        """, (batch_size,)).fetchall()

        if not queue_rows:
            return []

        # Mark as assigned
        queue_ids = [row["queue_id"] for row in queue_rows]
        placeholders = ",".join("?" * len(queue_ids))
        conn.execute(f"""
            UPDATE label_queue
            SET status = 'assigned',
                assigned_to = ?,
                assigned_at = CURRENT_TIMESTAMP
            WHERE queue_id IN ({placeholders})
        """, [annotator_id] + queue_ids)
        conn.commit()

        # Fetch full review + app context for each
        review_ids = [row["review_id"] for row in queue_rows]
        results = []
        for qrow in queue_rows:
            review = conn.execute("""
                SELECT r.*, a.title AS app_title, a.developer AS app_developer,
                       a.genre AS app_genre
                FROM reviews r
                JOIN apps a ON r.app_id = a.app_id
                WHERE r.review_id = ?
            """, (qrow["review_id"],)).fetchone()

            if review:
                item = dict(review)
                item["queue_id"] = qrow["queue_id"]
                item["priority_tier"] = qrow["priority_tier"]
                results.append(item)

        return results

    def complete_queue_item(
        self, queue_id: int, status: str = "completed"
    ) -> None:
        """Mark a queue item as completed or skipped."""
        conn = self.connect()
        conn.execute("""
            UPDATE label_queue
            SET status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE queue_id = ?
        """, (status, queue_id))
        conn.commit()

    def reset_abandoned_assignments(self, annotator_id: int) -> int:
        """Reset assigned-but-incomplete queue items back to pending."""
        conn = self.connect()
        cursor = conn.execute("""
            UPDATE label_queue
            SET status = 'pending', assigned_to = NULL, assigned_at = NULL
            WHERE assigned_to = ? AND status = 'assigned'
        """, (annotator_id,))
        conn.commit()
        return cursor.rowcount

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue breakdown by status and tier."""
        conn = self.connect()

        # By status
        status_rows = conn.execute("""
            SELECT status, COUNT(*) AS cnt
            FROM label_queue GROUP BY status
        """).fetchall()
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        # By tier
        tier_rows = conn.execute("""
            SELECT priority_tier, status, COUNT(*) AS cnt
            FROM label_queue GROUP BY priority_tier, status
        """).fetchall()
        by_tier = {}
        for row in tier_rows:
            tier = row["priority_tier"]
            if tier not in by_tier:
                by_tier[tier] = {}
            by_tier[tier][row["status"]] = row["cnt"]

        # Total
        total = conn.execute(
            "SELECT COUNT(*) FROM label_queue"
        ).fetchone()[0]

        return {
            "total": total,
            "by_status": by_status,
            "by_tier": by_tier,
        }

    # -------------------------------------------------------------------------
    # Labeling: sessions
    # -------------------------------------------------------------------------

    def start_label_session(self, annotator_id: int) -> int:
        """Start a labeling session. Returns session_id."""
        conn = self.connect()
        cursor = conn.execute(
            "INSERT INTO label_sessions (annotator_id) VALUES (?)",
            (annotator_id,)
        )
        conn.commit()
        return cursor.lastrowid

    def complete_label_session(
        self,
        session_id: int,
        labels_created: int,
        labels_skipped: int,
        avg_time: Optional[float] = None,
    ) -> None:
        """Record session completion."""
        conn = self.connect()
        conn.execute("""
            UPDATE label_sessions
            SET completed_at = CURRENT_TIMESTAMP,
                status = 'completed',
                labels_created = ?,
                labels_skipped = ?,
                avg_time_per_label_seconds = ?
            WHERE session_id = ?
        """, (labels_created, labels_skipped, avg_time, session_id))
        conn.commit()

    def abandon_label_session(self, session_id: int) -> None:
        """Mark a session as abandoned (e.g. user quit early)."""
        conn = self.connect()
        conn.execute("""
            UPDATE label_sessions
            SET completed_at = CURRENT_TIMESTAMP, status = 'abandoned'
            WHERE session_id = ?
        """, (session_id,))
        conn.commit()

    def get_recent_sessions(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent labeling sessions."""
        conn = self.connect()
        rows = conn.execute("""
            SELECT ls.*, a.name AS annotator_name
            FROM label_sessions ls
            JOIN annotators a ON ls.annotator_id = a.annotator_id
            ORDER BY ls.session_id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Labeling: stats & queries
    # -------------------------------------------------------------------------

    def get_labeling_progress(self) -> Dict[str, Any]:
        """Get overall labeling progress."""
        conn = self.connect()

        total_labeled = conn.execute(
            "SELECT COUNT(DISTINCT review_id) FROM labels"
        ).fetchone()[0]

        total_queued = conn.execute(
            "SELECT COUNT(*) FROM label_queue"
        ).fetchone()[0]

        queue_pending = conn.execute(
            "SELECT COUNT(*) FROM label_queue WHERE status = 'pending'"
        ).fetchone()[0]

        queue_completed = conn.execute(
            "SELECT COUNT(*) FROM label_queue WHERE status = 'completed'"
        ).fetchone()[0]

        # Per-app coverage
        app_rows = conn.execute("""
            SELECT r.app_id, a.title AS app_title,
                   COUNT(DISTINCT l.review_id) AS labeled_count,
                   COUNT(DISTINCT r.review_id) AS total_reviews
            FROM reviews r
            JOIN apps a ON r.app_id = a.app_id
            LEFT JOIN labels l ON r.review_id = l.review_id
            GROUP BY r.app_id
            ORDER BY labeled_count DESC
        """).fetchall()

        return {
            "total_labeled": total_labeled,
            "total_queued": total_queued,
            "queue_pending": queue_pending,
            "queue_completed": queue_completed,
            "per_app": [dict(row) for row in app_rows],
        }

    def get_label_distribution(
        self, annotator_id: Optional[int] = None
    ) -> Dict[str, int]:
        """Get count of labels per sentiment class."""
        conn = self.connect()
        if annotator_id is not None:
            rows = conn.execute("""
                SELECT sentiment, COUNT(*) AS cnt FROM labels
                WHERE annotator_id = ? GROUP BY sentiment
            """, (annotator_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT sentiment, COUNT(*) AS cnt FROM labels
                GROUP BY sentiment
            """).fetchall()
        return {row["sentiment"]: row["cnt"] for row in rows}

    def get_agreement_pairs(self) -> List[Dict[str, Any]]:
        """
        Get reviews that have been labeled by multiple annotators,
        with their labels for agreement computation.
        """
        conn = self.connect()
        rows = conn.execute("""
            SELECT l1.review_id,
                   l1.annotator_id AS annotator_1,
                   l1.sentiment AS label_1,
                   l2.annotator_id AS annotator_2,
                   l2.sentiment AS label_2
            FROM labels l1
            JOIN labels l2 ON l1.review_id = l2.review_id
                          AND l1.annotator_id < l2.annotator_id
        """).fetchall()
        return [dict(row) for row in rows]

    def get_labeled_reviews(
        self, min_confidence: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all labeled reviews via the v_labeled_reviews view."""
        conn = self.connect()
        if min_confidence:
            confidence_order = {"high": 1, "medium": 2, "low": 3}
            threshold = confidence_order.get(min_confidence, 3)
            valid = [k for k, v in confidence_order.items() if v <= threshold]
            placeholders = ",".join("?" * len(valid))
            rows = conn.execute(
                f"SELECT * FROM v_labeled_reviews WHERE confidence IN ({placeholders})",
                valid
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM v_labeled_reviews"
            ).fetchall()
        return [dict(row) for row in rows]
