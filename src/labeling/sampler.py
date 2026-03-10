"""
Sampling strategy for labeling queue population.

Selects the most valuable reviews for annotation using a tiered strategy
based on existing v_reviews_sentiment and v_app_stats views.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from src.database.db_manager import DatabaseManager
from src.config.settings import (
    LABELING_TARGET_QUEUE_SIZE,
    LABELING_TIER_ALLOCATION,
    LABELING_CROSS_APP_RESERVE,
)
from src.utils.logger import setup_logger


TIER_LABELS = {
    1: "Long negative (1-2 star, 200+ chars)",
    2: "Long positive (4-5 star, 200+ chars)",
    3: "Ambiguous middle (3-star)",
    4: "Short meaningful",
}


class LabelingSampler:
    """
    Populates the labeling queue using a stratified sampling strategy.

    Uses the existing v_reviews_sentiment view to select reviews from
    four priority tiers, then applies cross-app balancing.
    """

    def __init__(
        self,
        db: DatabaseManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db
        self.logger = logger or setup_logger(
            "labeling.sampler", log_file="labeling.log"
        )

    def populate_queue(
        self,
        target_total: int = LABELING_TARGET_QUEUE_SIZE,
        tier_allocation: Optional[Dict[int, int]] = None,
        cross_app_reserve: int = LABELING_CROSS_APP_RESERVE,
    ) -> int:
        """
        Populate the label queue with stratified review samples.

        Returns:
            Number of reviews added to the queue
        """
        base_allocation = tier_allocation or LABELING_TIER_ALLOCATION
        exclude = self._get_already_queued_or_labeled()

        # Scale allocations proportionally if target < default total
        default_total = sum(base_allocation.values()) + cross_app_reserve
        if target_total < default_total:
            scale = target_total / default_total
            allocation = {
                t: max(1, int(n * scale))
                for t, n in base_allocation.items()
            }
            cross_app_reserve = max(0, int(cross_app_reserve * scale))
        else:
            allocation = dict(base_allocation)

        self.logger.info(
            f"Populating queue: target={target_total}, "
            f"excluding {len(exclude)} already-queued/labeled reviews"
        )

        all_items: List[Tuple[str, int]] = []

        # Tier-based sampling
        for tier, limit in sorted(allocation.items()):
            tier_reviews = self._get_tier_reviews(tier, limit, exclude)
            for rid in tier_reviews:
                all_items.append((rid, tier))
                exclude.add(rid)
            self.logger.info(
                f"  Tier {tier} ({TIER_LABELS.get(tier, '?')}): "
                f"{len(tier_reviews)} selected"
            )

        # Cross-app balancing
        if cross_app_reserve > 0:
            app_reviews = self._get_cross_app_balance(
                cross_app_reserve, exclude
            )
            # Assign cross-app reviews as tier 2 (mid-priority)
            for rid in app_reviews:
                all_items.append((rid, 2))
                exclude.add(rid)
            self.logger.info(
                f"  Cross-app balance: {len(app_reviews)} selected"
            )

        # Insert into queue
        inserted = self.db.populate_queue(all_items)
        self.logger.info(f"Queue populated: {inserted} reviews added")
        return inserted

    def _get_tier_reviews(
        self, tier: int, limit: int, exclude: Set[str]
    ) -> List[str]:
        """Get review IDs for a specific sampling tier."""
        conn = self.db.connect()

        if tier == 1:
            # Long negative: 1-2 star, 200+ chars
            rows = conn.execute("""
                SELECT review_id FROM v_reviews_sentiment
                WHERE sentiment_bucket = 'negative' AND length_bucket = 'long'
                ORDER BY LENGTH(content) DESC
            """).fetchall()
        elif tier == 2:
            # Long positive: 4-5 star, 200+ chars
            rows = conn.execute("""
                SELECT review_id FROM v_reviews_sentiment
                WHERE sentiment_bucket = 'positive' AND length_bucket = 'long'
                ORDER BY LENGTH(content) DESC
            """).fetchall()
        elif tier == 3:
            # Ambiguous middle: 3-star, any length
            rows = conn.execute("""
                SELECT review_id FROM v_reviews_sentiment
                WHERE sentiment_bucket = 'neutral'
                ORDER BY LENGTH(content) DESC
            """).fetchall()
        elif tier == 4:
            # Short meaningful: short/very_short but not empty
            rows = conn.execute("""
                SELECT review_id FROM v_reviews_sentiment
                WHERE length_bucket IN ('very_short', 'short')
                  AND content != '' AND content != ' '
                ORDER BY RANDOM()
            """).fetchall()
        else:
            return []

        # Filter out excluded and limit
        result = []
        for row in rows:
            if row["review_id"] not in exclude:
                result.append(row["review_id"])
                if len(result) >= limit:
                    break
        return result

    def _get_cross_app_balance(
        self, reserve: int, exclude: Set[str]
    ) -> List[str]:
        """
        Select reviews to ensure every app has representation in the queue.

        Allocates proportionally by review count, with a minimum of 30 per app.
        """
        conn = self.db.connect()

        # Get app review counts
        app_stats = conn.execute("""
            SELECT app_id, review_count FROM v_app_stats
            ORDER BY review_count DESC
        """).fetchall()

        if not app_stats:
            return []

        total_reviews = sum(row["review_count"] for row in app_stats)
        per_app_min = 30
        num_apps = len(app_stats)

        result = []
        for row in app_stats:
            # Proportional allocation with minimum
            proportion = row["review_count"] / total_reviews if total_reviews else 0
            target = max(per_app_min, int(reserve * proportion))

            # Get medium-length reviews from this app (good balance)
            app_reviews = conn.execute("""
                SELECT review_id FROM v_reviews_sentiment
                WHERE app_id = ? AND length_bucket IN ('medium', 'short')
                ORDER BY RANDOM()
            """, (row["app_id"],)).fetchall()

            count = 0
            for r in app_reviews:
                if r["review_id"] not in exclude and count < target:
                    result.append(r["review_id"])
                    exclude.add(r["review_id"])
                    count += 1

            if len(result) >= reserve:
                break

        return result[:reserve]

    def _get_already_queued_or_labeled(self) -> Set[str]:
        """Get review IDs that are already in the queue or already labeled."""
        conn = self.db.connect()

        queued = conn.execute(
            "SELECT review_id FROM label_queue"
        ).fetchall()

        labeled = conn.execute(
            "SELECT DISTINCT review_id FROM labels"
        ).fetchall()

        result = set()
        for row in queued:
            result.add(row["review_id"])
        for row in labeled:
            result.add(row["review_id"])

        return result
