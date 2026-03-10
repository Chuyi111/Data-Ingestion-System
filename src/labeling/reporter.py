"""
Labeling progress reporting and quality metrics display.

Follows the formatting patterns from src/ingestion/reporter.py:
divider-based ASCII tables, 2-space indentation, aligned columns.
"""

import logging
from typing import Dict, List, Any, Optional

from src.database.db_manager import DatabaseManager
from src.utils.logger import setup_logger


SENTIMENT_CLASSES = [
    "very_negative", "negative", "neutral", "positive", "very_positive"
]


class LabelingReporter:
    """Formats and displays labeling metrics and progress."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or setup_logger(
            "labeling.reporter", log_file="labeling.log"
        )

    def report_progress(self, db: DatabaseManager) -> None:
        """Print overall labeling progress with per-app breakdown."""
        progress = db.get_labeling_progress()

        div = "=" * 70
        print(f"\n{div}")
        print("  LABELING PROGRESS")
        print(div)
        print(f"  Total reviews labeled : {progress['total_labeled']:,}")
        print(f"  Queue total           : {progress['total_queued']:,}")
        print(f"  Queue pending         : {progress['queue_pending']:,}")
        print(f"  Queue completed       : {progress['queue_completed']:,}")

        # Label distribution
        dist = db.get_label_distribution()
        if dist:
            total = sum(dist.values())
            print(f"\n  Label Distribution ({total} total):")
            for cls in SENTIMENT_CLASSES:
                count = dist.get(cls, 0)
                pct = count / total * 100 if total else 0
                bar = "#" * int(pct / 2)
                print(f"    {cls:<16}: {count:>5}  ({pct:>5.1f}%)  {bar}")

        # Per-app coverage
        apps = progress.get("per_app", [])
        if apps:
            print(f"\n  Per-App Coverage:")
            print(
                f"  {'App':<45} {'Labeled':>7} {'Total':>7} {'Coverage':>8}"
            )
            print("  " + "-" * 67)
            for app in apps:
                labeled = app["labeled_count"]
                total = app["total_reviews"]
                pct = labeled / total * 100 if total else 0
                name = app.get("app_title", app["app_id"])
                if len(name) > 42:
                    name = name[:42] + "..."
                print(
                    f"  {name:<45} {labeled:>7} {total:>7} {pct:>7.1f}%"
                )

        print(f"\n{div}\n")

    def report_queue_status(self, db: DatabaseManager) -> None:
        """Print queue breakdown by tier and status."""
        stats = db.get_queue_stats()

        div = "=" * 70
        print(f"\n{div}")
        print(f"  QUEUE STATUS  |  Total: {stats['total']:,}")
        print(div)

        # By status
        print(f"\n  By Status:")
        for status in ["pending", "assigned", "completed", "skipped"]:
            count = stats["by_status"].get(status, 0)
            print(f"    {status:<12}: {count:>6}")

        # By tier
        print(f"\n  By Tier:")
        tier_labels = {
            1: "Long negative",
            2: "Long positive",
            3: "Ambiguous middle",
            4: "Short meaningful",
        }
        for tier in sorted(stats.get("by_tier", {}).keys()):
            tier_data = stats["by_tier"][tier]
            total_tier = sum(tier_data.values())
            pending = tier_data.get("pending", 0)
            completed = tier_data.get("completed", 0)
            label = tier_labels.get(tier, f"Tier {tier}")
            print(
                f"    Tier {tier} ({label:<17}): "
                f"{total_tier:>5} total, "
                f"{pending:>5} pending, "
                f"{completed:>5} done"
            )

        print(f"\n{div}\n")

    def report_agreement(self, db: DatabaseManager) -> None:
        """Compute and display inter-annotator agreement (Cohen's kappa)."""
        pairs = db.get_agreement_pairs()

        div = "=" * 70
        print(f"\n{div}")
        print("  INTER-ANNOTATOR AGREEMENT")
        print(div)

        if not pairs:
            print("  No overlapping labels found.")
            print("  Agreement requires reviews labeled by 2+ annotators.")
            print(f"\n{div}\n")
            return

        total_pairs = len(pairs)
        agree = sum(1 for p in pairs if p["label_1"] == p["label_2"])
        observed_agreement = agree / total_pairs if total_pairs else 0

        # Expected agreement (chance)
        all_labels = []
        for p in pairs:
            all_labels.append(p["label_1"])
            all_labels.append(p["label_2"])
        label_counts = {}
        for lbl in all_labels:
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
        total_labels = len(all_labels)
        expected_agreement = sum(
            (c / total_labels) ** 2 for c in label_counts.values()
        )

        # Cohen's kappa
        if expected_agreement < 1.0:
            kappa = (
                (observed_agreement - expected_agreement)
                / (1 - expected_agreement)
            )
        else:
            kappa = 1.0

        # Interpret
        if kappa > 0.8:
            interpretation = "Excellent"
        elif kappa > 0.6:
            interpretation = "Substantial"
        elif kappa > 0.4:
            interpretation = "Moderate"
        elif kappa > 0.2:
            interpretation = "Fair"
        else:
            interpretation = "Poor"

        print(f"  Overlapping reviews : {total_pairs}")
        print(f"  Observed agreement  : {observed_agreement:.1%}")
        print(f"  Expected (chance)   : {expected_agreement:.1%}")
        print(f"  Cohen's kappa       : {kappa:.3f} ({interpretation})")

        # Disagreement breakdown
        if total_pairs > agree:
            print(f"\n  Disagreements ({total_pairs - agree}):")
            for p in pairs:
                if p["label_1"] != p["label_2"]:
                    print(
                        f"    Review {p['review_id'][:20]}...: "
                        f"{p['label_1']} vs {p['label_2']}"
                    )

        print(f"\n{div}\n")

    def report_sessions(self, db: DatabaseManager, limit: int = 10) -> None:
        """Print recent labeling sessions."""
        sessions = db.get_recent_sessions(limit)

        div = "=" * 90
        print(f"\n{div}")
        print(f"  RECENT LABELING SESSIONS (last {limit})")
        print(div)

        if not sessions:
            print("  No labeling sessions found.")
            print(f"\n{div}\n")
            return

        print(
            f"  {'ID':>4}  {'Annotator':<15} {'Status':<12} "
            f"{'Created':>7} {'Skipped':>7} {'Avg(s)':>7} "
            f"{'Started':<20}"
        )
        print("  " + "-" * 84)

        for s in sessions:
            avg = (
                f"{s['avg_time_per_label_seconds']:.1f}"
                if s["avg_time_per_label_seconds"] else "-"
            )
            started = (
                s["started_at"][:19] if s["started_at"] else "-"
            )
            print(
                f"  {s['session_id']:>4}  "
                f"{s.get('annotator_name', '?'):<15} "
                f"{s['status']:<12} "
                f"{s['labels_created']:>7} "
                f"{s['labels_skipped']:>7} "
                f"{avg:>7} "
                f"{started:<20}"
            )

        print(f"\n{div}\n")
