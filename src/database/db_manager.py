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
