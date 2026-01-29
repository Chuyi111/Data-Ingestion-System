"""
File storage utilities for Google Play Review Scraper.

Handles exporting scraped data to JSON and CSV formats with
support for incremental saving and deduplication.
"""

import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
from datetime import datetime

from src.models.review import Review, AppInfo
from src.config.settings import DATA_DIR, DEFAULT_OUTPUT_PREFIX
from src.utils.logger import get_logger


class FileStorage:
    """
    Handles file-based storage for scraped reviews.

    Supports JSON and CSV export with deduplication and incremental saving.
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        output_prefix: str = DEFAULT_OUTPUT_PREFIX
    ):
        """
        Initialize file storage.

        Args:
            output_dir: Directory for output files (default: DATA_DIR)
            output_prefix: Prefix for output filenames
        """
        self.output_dir = Path(output_dir) if output_dir else DATA_DIR
        self.output_prefix = output_prefix
        self.logger = get_logger("storage")
        self._seen_ids: Set[str] = set()

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_reviews_json(
        self,
        reviews: List[Review],
        filename: Optional[str] = None,
        append: bool = False
    ) -> Path:
        """
        Save reviews to JSON file.

        Args:
            reviews: List of Review objects to save
            filename: Output filename (default: auto-generated)
            append: If True, append to existing file

        Returns:
            Path to the saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.output_prefix}_{timestamp}.json"

        filepath = self.output_dir / filename

        # Convert reviews to dictionaries
        reviews_data = [review.to_dict() for review in reviews]

        if append and filepath.exists():
            # Load existing data and merge
            existing_data = self._load_json(filepath)
            reviews_data = self._deduplicate_reviews(existing_data + reviews_data)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(reviews_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(reviews_data)} reviews to {filepath}")
        return filepath

    def save_reviews_csv(
        self,
        reviews: List[Review],
        filename: Optional[str] = None,
        append: bool = False
    ) -> Path:
        """
        Save reviews to CSV file.

        Args:
            reviews: List of Review objects to save
            filename: Output filename (default: auto-generated)
            append: If True, append to existing file

        Returns:
            Path to the saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.output_prefix}_{timestamp}.csv"

        filepath = self.output_dir / filename

        # Determine write mode and whether to write headers
        mode = 'a' if append and filepath.exists() else 'w'
        write_header = not (append and filepath.exists())

        with open(filepath, mode, newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            if write_header:
                writer.writerow(Review.csv_headers())

            for review in reviews:
                # Skip duplicates if we're tracking them
                if review.review_id in self._seen_ids:
                    continue
                self._seen_ids.add(review.review_id)
                writer.writerow(review.to_csv_row())

        self.logger.info(f"Saved reviews to {filepath}")
        return filepath

    def save_reviews(
        self,
        reviews: List[Review],
        formats: List[str] = ['json', 'csv'],
        filename_prefix: Optional[str] = None
    ) -> Dict[str, Path]:
        """
        Save reviews to multiple formats.

        Args:
            reviews: List of Review objects to save
            formats: List of formats to save ('json', 'csv')
            filename_prefix: Prefix for filenames (default: auto-generated)

        Returns:
            Dictionary mapping format to saved file path
        """
        if filename_prefix is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_prefix = f"{self.output_prefix}_{timestamp}"

        saved_files: Dict[str, Path] = {}

        if 'json' in formats:
            json_path = self.save_reviews_json(
                reviews,
                filename=f"{filename_prefix}.json"
            )
            saved_files['json'] = json_path

        if 'csv' in formats:
            csv_path = self.save_reviews_csv(
                reviews,
                filename=f"{filename_prefix}.csv"
            )
            saved_files['csv'] = csv_path

        return saved_files

    def save_app_info(
        self,
        app_infos: List[AppInfo],
        filename: Optional[str] = None
    ) -> Path:
        """
        Save app information to JSON file.

        Args:
            app_infos: List of AppInfo objects
            filename: Output filename (default: auto-generated)

        Returns:
            Path to the saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"app_info_{timestamp}.json"

        filepath = self.output_dir / filename

        data = [info.to_dict() for info in app_infos]

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(data)} app info records to {filepath}")
        return filepath

    def load_reviews_json(self, filepath: Path) -> List[Review]:
        """
        Load reviews from JSON file.

        Args:
            filepath: Path to JSON file

        Returns:
            List of Review objects
        """
        data = self._load_json(filepath)
        reviews = [Review.from_dict(item) for item in data]
        self.logger.info(f"Loaded {len(reviews)} reviews from {filepath}")
        return reviews

    def checkpoint_save(
        self,
        reviews: List[Review],
        checkpoint_id: int,
        app_id: str
    ) -> Path:
        """
        Save a checkpoint during scraping.

        Args:
            reviews: Reviews collected so far
            checkpoint_id: Checkpoint number
            app_id: App being scraped

        Returns:
            Path to checkpoint file
        """
        safe_app_id = app_id.replace('.', '_')
        filename = f"checkpoint_{safe_app_id}_{checkpoint_id}.json"

        return self.save_reviews_json(reviews, filename=filename)

    def _load_json(self, filepath: Path) -> List[Dict[str, Any]]:
        """
        Load JSON data from file.

        Args:
            filepath: Path to JSON file

        Returns:
            List of dictionaries
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _deduplicate_reviews(
        self,
        reviews_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate reviews based on review_id.

        Args:
            reviews_data: List of review dictionaries

        Returns:
            Deduplicated list
        """
        seen: Set[str] = set()
        unique: List[Dict[str, Any]] = []

        for review in reviews_data:
            review_id = review.get('review_id', '')
            if review_id not in seen:
                seen.add(review_id)
                unique.append(review)

        removed = len(reviews_data) - len(unique)
        if removed > 0:
            self.logger.info(f"Removed {removed} duplicate reviews")

        return unique

    def get_stats(self, filepath: Path) -> Dict[str, Any]:
        """
        Get statistics about a saved reviews file.

        Args:
            filepath: Path to reviews file

        Returns:
            Dictionary with statistics
        """
        if filepath.suffix == '.json':
            reviews = self.load_reviews_json(filepath)
        else:
            # For CSV, count lines
            with open(filepath, 'r', encoding='utf-8') as f:
                reviews_count = sum(1 for _ in f) - 1  # Subtract header
            return {'total_reviews': reviews_count, 'format': 'csv'}

        # Calculate stats for JSON
        ratings = [r.rating for r in reviews]
        apps = set(r.app_id for r in reviews)

        return {
            'total_reviews': len(reviews),
            'unique_apps': len(apps),
            'apps': list(apps),
            'average_rating': sum(ratings) / len(ratings) if ratings else 0,
            'rating_distribution': {
                i: ratings.count(i) for i in range(1, 6)
            },
            'format': 'json'
        }
