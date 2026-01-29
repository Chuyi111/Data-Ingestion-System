"""
Data models for Google Play reviews.

Defines the Review dataclass for structured review data storage.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class Review:
    """
    Represents a Google Play Store review.

    Attributes:
        review_id: Unique identifier for the review
        app_id: App package name (e.g., 'com.whatsapp')
        author: Reviewer's display name
        rating: Star rating (1-5)
        content: Review text content
        timestamp: When the review was posted
        thumbs_up: Number of helpful votes
        app_version: App version at time of review
        reply_content: Developer's reply (if any)
        reply_timestamp: When developer replied (if any)
        scraped_at: When this review was scraped
    """

    review_id: str
    app_id: str
    author: str
    rating: int
    content: str
    timestamp: datetime
    thumbs_up: int = 0
    app_version: Optional[str] = None
    reply_content: Optional[str] = None
    reply_timestamp: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert review to dictionary format.

        Handles datetime serialization for JSON compatibility.

        Returns:
            Dictionary representation of the review
        """
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Review':
        """
        Create a Review from dictionary data.

        Args:
            data: Dictionary containing review data

        Returns:
            Review instance
        """
        # Convert ISO strings back to datetime
        for key in ['timestamp', 'reply_timestamp', 'scraped_at']:
            if key in data and data[key] is not None:
                if isinstance(data[key], str):
                    data[key] = datetime.fromisoformat(data[key])

        return cls(**data)

    @classmethod
    def from_google_play(cls, raw_review: Dict[str, Any], app_id: str) -> 'Review':
        """
        Create a Review from raw google-play-scraper data.

        Args:
            raw_review: Raw review data from google-play-scraper
            app_id: App package name

        Returns:
            Review instance
        """
        return cls(
            review_id=raw_review.get('reviewId', ''),
            app_id=app_id,
            author=raw_review.get('userName', 'Anonymous'),
            rating=raw_review.get('score', 0),
            content=raw_review.get('content', ''),
            timestamp=raw_review.get('at', datetime.now()),
            thumbs_up=raw_review.get('thumbsUpCount', 0),
            app_version=raw_review.get('reviewCreatedVersion'),
            reply_content=raw_review.get('replyContent'),
            reply_timestamp=raw_review.get('repliedAt'),
            scraped_at=datetime.now()
        )

    def to_csv_row(self) -> List[Any]:
        """
        Convert review to a list for CSV row.

        Returns:
            List of values in CSV column order
        """
        return [
            self.review_id,
            self.app_id,
            self.author,
            self.rating,
            self.content,
            self.timestamp.isoformat() if self.timestamp else '',
            self.thumbs_up,
            self.app_version or '',
            self.reply_content or '',
            self.reply_timestamp.isoformat() if self.reply_timestamp else '',
            self.scraped_at.isoformat() if self.scraped_at else ''
        ]

    @staticmethod
    def csv_headers() -> List[str]:
        """
        Get CSV column headers.

        Returns:
            List of column header names
        """
        return [
            'review_id',
            'app_id',
            'author',
            'rating',
            'content',
            'timestamp',
            'thumbs_up',
            'app_version',
            'reply_content',
            'reply_timestamp',
            'scraped_at'
        ]


@dataclass
class AppInfo:
    """
    Represents Google Play app metadata.

    Attributes:
        app_id: App package name
        title: App display name
        developer: Developer name
        rating: Average rating
        reviews_count: Total number of reviews
        installs: Install count string (e.g., '1,000,000+')
        genre: App category
        scraped_at: When this info was scraped
    """

    app_id: str
    title: str
    developer: str
    rating: float
    reviews_count: int
    installs: str
    genre: str
    scraped_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert app info to dictionary format.

        Returns:
            Dictionary representation
        """
        data = asdict(self)
        if isinstance(data['scraped_at'], datetime):
            data['scraped_at'] = data['scraped_at'].isoformat()
        return data

    @classmethod
    def from_google_play(cls, raw_data: Dict[str, Any]) -> 'AppInfo':
        """
        Create AppInfo from raw google-play-scraper data.

        Args:
            raw_data: Raw app data from google-play-scraper

        Returns:
            AppInfo instance
        """
        return cls(
            app_id=raw_data.get('appId', ''),
            title=raw_data.get('title', ''),
            developer=raw_data.get('developer', ''),
            rating=raw_data.get('score', 0.0),
            reviews_count=raw_data.get('reviews', 0),
            installs=raw_data.get('installs', ''),
            genre=raw_data.get('genre', ''),
            scraped_at=datetime.now()
        )
