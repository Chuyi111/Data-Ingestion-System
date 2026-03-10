"""
Labeling CLI entry point.

Usage:
    # Populate the labeling queue with stratified samples
    python -m src.labeling.cli --populate-queue
    python -m src.labeling.cli --populate-queue --target 500

    # Start an interactive labeling session
    python -m src.labeling.cli --annotate --name alice
    python -m src.labeling.cli --annotate --name alice --batch-size 10

    # Show labeling progress
    python -m src.labeling.cli --progress

    # Show queue status
    python -m src.labeling.cli --queue-status

    # Show inter-annotator agreement
    python -m src.labeling.cli --agreement

    # Show recent sessions
    python -m src.labeling.cli --sessions

    # Export labeled data for training
    python -m src.labeling.cli --export
    python -m src.labeling.cli --export --format csv --split 80/10/10
"""

import argparse
import sys

from src.database.db_manager import DatabaseManager
from src.config.settings import (
    LABELING_DB_PATH,
    LABELING_DEFAULT_BATCH_SIZE,
    LABELING_TARGET_QUEUE_SIZE,
    LABELING_EXPORT_DIR,
)


def main():
    parser = argparse.ArgumentParser(
        description="Sentiment labeling system for review annotation"
    )

    # Queue population
    parser.add_argument(
        "--populate-queue", action="store_true",
        help="Populate the labeling queue with stratified samples",
    )
    parser.add_argument(
        "--target", type=int, default=LABELING_TARGET_QUEUE_SIZE,
        help=f"Target queue size (default: {LABELING_TARGET_QUEUE_SIZE})",
    )

    # Annotation
    parser.add_argument(
        "--annotate", action="store_true",
        help="Start an interactive labeling session",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Annotator name (required for --annotate)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=LABELING_DEFAULT_BATCH_SIZE,
        help=f"Reviews per session (default: {LABELING_DEFAULT_BATCH_SIZE})",
    )

    # Reporting
    parser.add_argument(
        "--progress", action="store_true",
        help="Show labeling progress and exit",
    )
    parser.add_argument(
        "--queue-status", action="store_true",
        help="Show queue breakdown and exit",
    )
    parser.add_argument(
        "--agreement", action="store_true",
        help="Show inter-annotator agreement and exit",
    )
    parser.add_argument(
        "--sessions", action="store_true",
        help="Show recent labeling sessions and exit",
    )

    # Export
    parser.add_argument(
        "--export", action="store_true",
        help="Export labeled data for training",
    )
    parser.add_argument(
        "--format", type=str, default="jsonl",
        choices=["jsonl", "csv"],
        help="Export format (default: jsonl)",
    )
    parser.add_argument(
        "--split", type=str, default="80/10/10",
        help="Train/val/test split ratio (default: 80/10/10)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=LABELING_EXPORT_DIR,
        help=f"Export directory (default: {LABELING_EXPORT_DIR})",
    )

    # Database
    parser.add_argument(
        "--database", default=LABELING_DB_PATH,
        help=f"Path to SQLite database (default: {LABELING_DB_PATH})",
    )

    args = parser.parse_args()

    # Initialize DB
    db = DatabaseManager(args.database)
    db.init_schema()

    try:
        # Queue population
        if args.populate_queue:
            from src.labeling.sampler import LabelingSampler

            sampler = LabelingSampler(db=db)
            inserted = sampler.populate_queue(target_total=args.target)
            print(f"\n  Queue populated: {inserted} reviews added.\n")
            return 0

        # Annotation
        if args.annotate:
            if not args.name:
                print("\n  Error: --name is required for --annotate\n")
                return 1

            from src.labeling.session import LabelingSession

            session = LabelingSession(
                db=db,
                annotator_name=args.name,
                batch_size=args.batch_size,
            )
            session.start()
            return 0

        # Reporting
        if args.progress:
            from src.labeling.reporter import LabelingReporter
            reporter = LabelingReporter()
            reporter.report_progress(db)
            return 0

        if args.queue_status:
            from src.labeling.reporter import LabelingReporter
            reporter = LabelingReporter()
            reporter.report_queue_status(db)
            return 0

        if args.agreement:
            from src.labeling.reporter import LabelingReporter
            reporter = LabelingReporter()
            reporter.report_agreement(db)
            return 0

        if args.sessions:
            from src.labeling.reporter import LabelingReporter
            reporter = LabelingReporter()
            reporter.report_sessions(db)
            return 0

        # Export
        if args.export:
            from src.labeling.exporter import TrainingDataExporter

            exporter = TrainingDataExporter(db=db)
            exporter.export(
                fmt=args.format,
                split_ratio=args.split,
                output_dir=args.output_dir,
            )
            return 0

        # No action specified
        parser.print_help()
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
