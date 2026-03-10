"""
Interactive labeling session for review annotation.

Presents reviews from the queue one at a time, collects sentiment labels,
and tracks session metrics.
"""

import logging
import time
from typing import Dict, Any, List, Optional

from src.database.db_manager import DatabaseManager
from src.config.settings import LABELING_DEFAULT_BATCH_SIZE
from src.utils.logger import setup_logger


SENTIMENT_MAP = {
    "1": "very_negative",
    "2": "negative",
    "3": "neutral",
    "4": "positive",
    "5": "very_positive",
}

CONFIDENCE_MAP = {
    "h": "high",
    "m": "medium",
    "l": "low",
}

TIER_LABELS = {
    1: "long negative",
    2: "long positive",
    3: "ambiguous middle",
    4: "short meaningful",
}


class LabelingSession:
    """
    Interactive CLI-based labeling session.

    Pulls reviews from the queue, presents them with app context,
    and collects sentiment labels from the annotator.
    """

    def __init__(
        self,
        db: DatabaseManager,
        annotator_name: str,
        batch_size: int = LABELING_DEFAULT_BATCH_SIZE,
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db
        self.annotator_name = annotator_name
        self.batch_size = batch_size
        self.logger = logger or setup_logger(
            "labeling.session", log_file="labeling.log"
        )

    def start(self) -> Dict[str, Any]:
        """
        Run an interactive labeling session.

        Returns:
            Session summary dict with counts and timing
        """
        # Setup
        annotator_id = self.db.get_or_create_annotator(self.annotator_name)
        reset_count = self.db.reset_abandoned_assignments(annotator_id)
        if reset_count:
            self.logger.info(
                f"Reset {reset_count} abandoned assignments for "
                f"{self.annotator_name}"
            )

        session_id = self.db.start_label_session(annotator_id)

        # Fetch batch
        reviews = self.db.fetch_queue_batch(self.batch_size, annotator_id)
        if not reviews:
            print("\n  No reviews available in the queue.")
            print("  Run --populate-queue first to add reviews.\n")
            self.db.abandon_label_session(session_id)
            return {"labels_created": 0, "labels_skipped": 0}

        total = len(reviews)
        self._print_session_header(session_id, total)

        labels_created = 0
        labels_skipped = 0
        label_times: List[float] = []
        quit_early = False

        for idx, review in enumerate(reviews):
            self._display_review(review, idx + 1, total)

            label_start = time.time()

            # Collect sentiment
            sentiment = self._collect_sentiment()
            if sentiment is None:
                # User quit
                quit_early = True
                # Mark remaining assigned items as pending
                for remaining in reviews[idx:]:
                    self.db.complete_queue_item(
                        remaining["queue_id"], status="pending"
                    )
                    # Also reset assignment
                    conn = self.db.connect()
                    conn.execute("""
                        UPDATE label_queue
                        SET status = 'pending', assigned_to = NULL,
                            assigned_at = NULL
                        WHERE queue_id = ?
                    """, (remaining["queue_id"],))
                    conn.commit()
                break

            if sentiment == "skip":
                self.db.complete_queue_item(
                    review["queue_id"], status="skipped"
                )
                labels_skipped += 1
                elapsed = time.time() - label_start
                print(f"\n  Skipped. ({elapsed:.1f}s)\n")
                continue

            # Collect confidence
            confidence = self._collect_confidence()

            # Collect notes
            notes = self._collect_notes()

            # Store label
            self.db.insert_label(
                review_id=review["review_id"],
                annotator_id=annotator_id,
                sentiment=sentiment,
                confidence=confidence,
                notes=notes,
            )
            self.db.complete_queue_item(review["queue_id"])

            elapsed = time.time() - label_start
            label_times.append(elapsed)
            labels_created += 1

            print(
                f"\n  Labeled: {sentiment} ({confidence} confidence)"
                f"  [{elapsed:.1f}s]"
            )

            # Progress line
            queue_remaining = total - (idx + 1)
            print(
                f"  Progress: {idx + 1}/{total}  |  "
                f"Session total: {labels_created} labeled, "
                f"{labels_skipped} skipped"
            )

        # Finalize session
        avg_time = (
            sum(label_times) / len(label_times) if label_times else None
        )
        if quit_early:
            self.db.complete_label_session(
                session_id, labels_created, labels_skipped, avg_time
            )
        else:
            self.db.complete_label_session(
                session_id, labels_created, labels_skipped, avg_time
            )

        self._print_session_summary(
            session_id, labels_created, labels_skipped, avg_time, label_times
        )

        return {
            "session_id": session_id,
            "labels_created": labels_created,
            "labels_skipped": labels_skipped,
            "avg_time_per_label": avg_time,
        }

    # -----------------------------------------------------------------
    # Display helpers
    # -----------------------------------------------------------------

    def _print_session_header(self, session_id: int, batch_total: int):
        div = "=" * 70
        print(f"\n{div}")
        print(
            f"  LABELING SESSION #{session_id}  |  "
            f"Annotator: {self.annotator_name}  |  "
            f"Batch: {batch_total} reviews"
        )
        print(div)

    def _display_review(
        self, review: Dict[str, Any], index: int, total: int
    ):
        tier = review.get("priority_tier", "?")
        tier_label = TIER_LABELS.get(tier, "unknown")

        div = "-" * 70
        stars = "\u2605" * review["rating"] + "\u2606" * (5 - review["rating"])
        content_len = len(review.get("content", "") or "")

        print(f"\n{div}")
        print(
            f"  Review {index}/{total}  |  "
            f"Priority: Tier {tier} ({tier_label})"
        )
        print(
            f"  App: {review.get('app_title', review['app_id'])} "
            f"({review['app_id']})"
        )
        print(
            f"  Genre: {review.get('app_genre', 'N/A')}  |  "
            f"Rating: {stars}  |  "
            f"Length: {content_len} chars  |  "
            f"Thumbs up: {review.get('thumbs_up', 0)}"
        )
        print(div)

        content = review.get("content", "") or "(empty)"
        # Word-wrap long content at ~70 chars
        lines = _wrap_text(content, width=66)
        for line in lines:
            print(f"  {line}")

        print(div)

    def _collect_sentiment(self) -> Optional[str]:
        """
        Collect sentiment input. Returns sentiment string, 'skip', or None (quit).
        """
        print(
            "  Sentiment: [1] very_negative  [2] negative  [3] neutral"
        )
        print(
            "             [4] positive       [5] very_positive"
        )
        print(
            "             [s] skip           [q] quit session"
        )

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None

            if choice == "q":
                return None
            if choice == "s":
                return "skip"
            if choice in SENTIMENT_MAP:
                return SENTIMENT_MAP[choice]

            print("  Invalid input. Enter 1-5, s, or q.")

    def _collect_confidence(self) -> str:
        """Collect confidence input."""
        print("  Confidence: [h] high  [m] medium  [l] low")

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "high"

            if choice in CONFIDENCE_MAP:
                return CONFIDENCE_MAP[choice]
            # Default to high on empty input
            if choice == "":
                return "high"

            print("  Invalid input. Enter h, m, or l.")

    def _collect_notes(self) -> Optional[str]:
        """Collect optional notes."""
        print("  Notes (optional, Enter to skip):")
        try:
            notes = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return notes if notes else None

    def _print_session_summary(
        self,
        session_id: int,
        created: int,
        skipped: int,
        avg_time: Optional[float],
        label_times: List[float],
    ):
        div = "=" * 70
        total_time = sum(label_times) if label_times else 0

        print(f"\n{div}")
        print(f"  SESSION #{session_id} COMPLETE")
        print(div)
        print(f"  Labels created  : {created}")
        print(f"  Reviews skipped : {skipped}")
        if avg_time:
            print(f"  Avg time/label  : {avg_time:.1f}s")
        print(f"  Total time      : {total_time:.0f}s")
        print(f"{div}\n")


def _wrap_text(text: str, width: int = 66) -> List[str]:
    """Simple word-wrap for display."""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}" if current else word
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines if lines else ["(empty)"]
