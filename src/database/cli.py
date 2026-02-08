"""
Database CLI for Google Play Reviews.

Command-line interface for database initialization, data loading, and querying.

Usage:
    python -m src.database.cli init          # Initialize database schema
    python -m src.database.cli load FILE     # Load reviews from JSON file
    python -m src.database.cli stats         # Show database statistics
    python -m src.database.cli query [opts]  # Query reviews
"""

import argparse
import json
import sys
from pathlib import Path

from src.database.db_manager import DatabaseManager
from src.utils.logger import setup_logger


def cmd_init(args):
    """Initialize database schema."""
    db = DatabaseManager(args.database)
    if args.reset:
        confirm = input("This will DELETE all existing data. Are you sure? [y/N]: ")
        if confirm.lower() != "y":
            print("Aborted.")
            return 1
        db.reset_database()
    else:
        db.init_schema()
    print(f"Database initialized: {args.database}")
    return 0


def cmd_load(args):
    """Load reviews from JSON file."""
    json_path = Path(args.file)
    if not json_path.exists():
        print(f"File not found: {json_path}")
        return 1

    db = DatabaseManager(args.database)
    db.init_schema()  # Ensure schema exists

    print(f"Loading reviews from: {json_path}")
    inserted, skipped = db.load_from_json(json_path)

    print(f"\nLoad complete:")
    print(f"  Inserted: {inserted:,}")
    print(f"  Skipped (duplicates): {skipped:,}")

    stats = db.get_stats()
    print(f"\nDatabase now contains:")
    print(f"  Total reviews: {stats['total_reviews']:,}")
    print(f"  Total apps: {stats['total_apps']}")
    print(f"  DB file size: {stats['db_file_size_mb']:.2f} MB")

    db.close()
    return 0


def cmd_stats(args):
    """Show database statistics."""
    db = DatabaseManager(args.database)

    try:
        stats = db.get_stats()
    except Exception as e:
        print(f"Error accessing database: {e}")
        print("Run 'init' first to create the database.")
        return 1

    print("\n" + "=" * 50)
    print("DATABASE STATISTICS")
    print("=" * 50)
    print(f"\nOverall:")
    print(f"  Total reviews  : {stats['total_reviews']:,}")
    print(f"  Total apps     : {stats['total_apps']}")
    print(f"  Average rating : {stats['avg_rating']}")
    print(f"  Date range     : {stats['earliest_review']} to {stats['latest_review']}")
    print(f"  DB file size   : {stats['db_file_size_mb']:.2f} MB")

    if stats['total_reviews'] > 0:
        sentiment = db.get_sentiment_distribution()
        total = sum(sentiment.values())
        print(f"\nSentiment distribution:")
        print(f"  Positive (4-5): {sentiment['positive']:,} ({sentiment['positive']/total*100:.1f}%)")
        print(f"  Neutral  (3)  : {sentiment['neutral']:,} ({sentiment['neutral']/total*100:.1f}%)")
        print(f"  Negative (1-2): {sentiment['negative']:,} ({sentiment['negative']/total*100:.1f}%)")

        print("\nPer-app breakdown:")
        app_stats = db.get_app_stats()
        print(f"  {'App':<40} {'Reviews':>8} {'Avg Rating':>10}")
        print("  " + "-" * 60)
        for row in app_stats:
            print(f"  {row['app_id']:<40} {row['review_count']:>8} {row['avg_rating']:>10.2f}")

    db.close()
    return 0


def cmd_query(args):
    """Query reviews."""
    db = DatabaseManager(args.database)

    reviews = db.get_reviews(
        app_id=args.app,
        rating=args.rating,
        min_rating=args.min_rating,
        max_rating=args.max_rating,
        has_reply=args.has_reply,
        min_length=args.min_length,
        limit=args.limit,
        offset=args.offset,
    )

    if args.format == "json":
        print(json.dumps(reviews, indent=2, default=str))
    else:
        print(f"\nFound {len(reviews)} reviews:\n")
        for r in reviews:
            print(f"[{r['rating']}*] {r['app_id']}")
            print(f"    {r['content'][:100]}{'...' if len(r['content']) > 100 else ''}")
            print(f"    -- {r['author']}, {r['review_timestamp']}")
            print()

    db.close()
    return 0


def cmd_search(args):
    """Search reviews by content."""
    db = DatabaseManager(args.database)

    reviews = db.search_reviews(
        query=args.query,
        app_id=args.app,
        limit=args.limit,
    )

    print(f"\nFound {len(reviews)} reviews matching '{args.query}':\n")
    for r in reviews:
        print(f"[{r['rating']}*] {r['app_id']} (thumbs: {r['thumbs_up']})")
        print(f"    {r['content'][:150]}{'...' if len(r['content']) > 150 else ''}")
        print()

    db.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Google Play Reviews Database CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database", "-d",
        default="data/reviews.db",
        help="Path to SQLite database file"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize database schema")
    init_parser.add_argument(
        "--reset", action="store_true",
        help="Drop all tables and reinitialize (DESTRUCTIVE)"
    )

    # load
    load_parser = subparsers.add_parser("load", help="Load reviews from JSON file")
    load_parser.add_argument("file", help="Path to JSON file")

    # stats
    subparsers.add_parser("stats", help="Show database statistics")

    # query
    query_parser = subparsers.add_parser("query", help="Query reviews")
    query_parser.add_argument("--app", help="Filter by app_id")
    query_parser.add_argument("--rating", type=int, help="Exact rating")
    query_parser.add_argument("--min-rating", type=int, help="Minimum rating")
    query_parser.add_argument("--max-rating", type=int, help="Maximum rating")
    query_parser.add_argument("--has-reply", type=bool, help="Has developer reply")
    query_parser.add_argument("--min-length", type=int, help="Minimum content length")
    query_parser.add_argument("--limit", type=int, default=10, help="Max results")
    query_parser.add_argument("--offset", type=int, default=0, help="Pagination offset")
    query_parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format"
    )

    # search
    search_parser = subparsers.add_parser("search", help="Search reviews by content")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--app", help="Filter by app_id")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    setup_logger("database", log_to_file=False)

    commands = {
        "init": cmd_init,
        "load": cmd_load,
        "stats": cmd_stats,
        "query": cmd_query,
        "search": cmd_search,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
