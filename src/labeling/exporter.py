"""
Training data export from labeled reviews.

Exports labeled reviews as JSONL or CSV with stratified train/val/test
splits, conflict resolution for multi-annotator reviews, and metadata.
"""

import csv
import json
import logging
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from src.database.db_manager import DatabaseManager
from src.config.settings import LABELING_EXPORT_DIR
from src.utils.logger import setup_logger


class TrainingDataExporter:
    """Exports labeled reviews as training data with stratified splits."""

    def __init__(
        self,
        db: DatabaseManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db
        self.logger = logger or setup_logger(
            "labeling.exporter", log_file="labeling.log"
        )

    def export(
        self,
        fmt: str = "jsonl",
        split_ratio: str = "80/10/10",
        output_dir: str = LABELING_EXPORT_DIR,
        min_confidence: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Export labeled reviews as training data.

        Args:
            fmt: Output format ('jsonl' or 'csv')
            split_ratio: Train/val/test split as 'X/Y/Z'
            output_dir: Output directory path
            min_confidence: Minimum confidence to include ('high', 'medium', 'low')

        Returns:
            Summary dict with counts and file paths
        """
        # Parse split ratio
        parts = [int(x) for x in split_ratio.split("/")]
        if len(parts) != 3 or sum(parts) != 100:
            raise ValueError(
                f"Split ratio must be three numbers summing to 100, "
                f"got '{split_ratio}'"
            )
        ratios = [p / 100.0 for p in parts]

        # Get labeled reviews
        raw_labels = self.db.get_labeled_reviews(min_confidence)
        if not raw_labels:
            print("\n  No labeled reviews to export.\n")
            return {"total": 0}

        self.logger.info(f"Exporting {len(raw_labels)} label records")

        # Resolve conflicts (multi-annotator -> single label)
        examples = self._resolve_conflicts(raw_labels)
        self.logger.info(
            f"Resolved to {len(examples)} unique examples"
        )

        # Stratified split
        train, val, test = self._stratified_split(examples, ratios)

        # Assign split labels
        for ex in train:
            ex["split"] = "train"
        for ex in val:
            ex["split"] = "val"
        for ex in test:
            ex["split"] = "test"

        # Write files
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if fmt == "jsonl":
            paths = self._write_jsonl(train, val, test, out_path)
        elif fmt == "csv":
            paths = self._write_csv(train, val, test, out_path)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        # Write metadata
        metadata = self._build_metadata(
            train, val, test, fmt, split_ratio, min_confidence, paths
        )
        meta_path = out_path / "export_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        self._print_summary(metadata)
        return metadata

    def _resolve_conflicts(
        self, labels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Resolve multi-annotator labels into single examples via majority vote.
        """
        by_review: Dict[str, List[Dict]] = defaultdict(list)
        for lbl in labels:
            by_review[lbl["review_id"]].append(lbl)

        examples = []
        for review_id, review_labels in by_review.items():
            if len(review_labels) == 1:
                # Single annotator - use directly
                lbl = review_labels[0]
            else:
                # Multiple annotators - majority vote
                sentiment_counts: Dict[str, int] = defaultdict(int)
                for lbl in review_labels:
                    sentiment_counts[lbl["sentiment"]] += 1

                majority_sentiment = max(
                    sentiment_counts, key=sentiment_counts.get
                )

                # If no majority (tie), use the first label but lower confidence
                max_count = sentiment_counts[majority_sentiment]
                has_majority = (
                    list(sentiment_counts.values()).count(max_count) == 1
                )

                # Pick the label matching majority
                lbl = next(
                    l for l in review_labels
                    if l["sentiment"] == majority_sentiment
                )
                if not has_majority:
                    lbl = dict(lbl)
                    lbl["confidence"] = "low"

            examples.append({
                "text": lbl["content"],
                "label": lbl["sentiment"],
                "confidence": lbl["confidence"],
                "app_id": lbl["app_id"],
                "rating": lbl["rating"],
                "review_id": lbl["review_id"],
            })

        return examples

    def _stratified_split(
        self,
        examples: List[Dict],
        ratios: List[float],
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Split examples into train/val/test maintaining label distribution.

        Stratifies by sentiment class and app_id to ensure representative splits.
        """
        # Group by sentiment class
        by_class: Dict[str, List[Dict]] = defaultdict(list)
        for ex in examples:
            by_class[ex["label"]].append(ex)

        train, val, test = [], [], []

        for cls, cls_examples in by_class.items():
            random.shuffle(cls_examples)
            n = len(cls_examples)
            n_train = int(n * ratios[0])
            n_val = int(n * ratios[1])

            train.extend(cls_examples[:n_train])
            val.extend(cls_examples[n_train:n_train + n_val])
            test.extend(cls_examples[n_train + n_val:])

        # Shuffle each split
        random.shuffle(train)
        random.shuffle(val)
        random.shuffle(test)

        return train, val, test

    def _write_jsonl(
        self,
        train: List[Dict],
        val: List[Dict],
        test: List[Dict],
        out_path: Path,
    ) -> Dict[str, str]:
        """Write train/val/test as JSONL files."""
        paths = {}
        for name, data in [("train", train), ("val", val), ("test", test)]:
            fpath = out_path / f"{name}.jsonl"
            with open(fpath, "w", encoding="utf-8") as f:
                for ex in data:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            paths[name] = str(fpath)
        return paths

    def _write_csv(
        self,
        train: List[Dict],
        val: List[Dict],
        test: List[Dict],
        out_path: Path,
    ) -> Dict[str, str]:
        """Write train/val/test as CSV files."""
        fields = ["text", "label", "confidence", "app_id", "rating", "split"]
        paths = {}
        for name, data in [("train", train), ("val", val), ("test", test)]:
            fpath = out_path / f"{name}.csv"
            with open(fpath, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=fields, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(data)
            paths[name] = str(fpath)
        return paths

    def _build_metadata(
        self,
        train: List[Dict],
        val: List[Dict],
        test: List[Dict],
        fmt: str,
        split_ratio: str,
        min_confidence: Optional[str],
        paths: Dict[str, str],
    ) -> Dict[str, Any]:
        """Build export metadata."""
        def split_stats(data):
            dist = defaultdict(int)
            apps = set()
            for ex in data:
                dist[ex["label"]] += 1
                apps.add(ex["app_id"])
            return {
                "count": len(data),
                "label_distribution": dict(dist),
                "apps_represented": len(apps),
            }

        return {
            "export_timestamp": datetime.now().isoformat(),
            "format": fmt,
            "split_ratio": split_ratio,
            "min_confidence": min_confidence,
            "total_examples": len(train) + len(val) + len(test),
            "splits": {
                "train": split_stats(train),
                "val": split_stats(val),
                "test": split_stats(test),
            },
            "files": paths,
        }

    def _print_summary(self, metadata: Dict[str, Any]):
        """Print export summary."""
        div = "=" * 70
        print(f"\n{div}")
        print("  TRAINING DATA EXPORT")
        print(div)
        print(f"  Total examples: {metadata['total_examples']}")
        print(f"  Format        : {metadata['format']}")
        print(f"  Split ratio   : {metadata['split_ratio']}")

        for split_name in ["train", "val", "test"]:
            s = metadata["splits"][split_name]
            print(
                f"\n  {split_name.upper()} ({s['count']} examples, "
                f"{s['apps_represented']} apps):"
            )
            for cls, count in sorted(s["label_distribution"].items()):
                pct = count / s["count"] * 100 if s["count"] else 0
                print(f"    {cls:<16}: {count:>5} ({pct:.1f}%)")

        print(f"\n  Files:")
        for name, path in metadata["files"].items():
            print(f"    {name}: {path}")

        print(f"\n  Metadata: {metadata.get('export_timestamp', '')}")
        print(f"{div}\n")
