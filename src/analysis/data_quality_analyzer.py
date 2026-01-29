"""
Data Quality Analyzer for Google Play Reviews.

Performs exploratory and descriptive analysis to understand the dataset
and identify potential data quality issues for downstream modeling/labeling.
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import statistics


class DataQualityAnalyzer:
    """Analyzer for Google Play review data quality."""

    def __init__(self, data: List[Dict[str, Any]]):
        """
        Initialize analyzer with review data.

        Args:
            data: List of review dictionaries
        """
        self.data = data
        self.total_reviews = len(data)

    @classmethod
    def from_json_file(cls, filepath: Path) -> 'DataQualityAnalyzer':
        """Load data from JSON file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(data)

    def run_full_analysis(self) -> Dict[str, Any]:
        """Run complete data quality analysis."""
        print("=" * 70)
        print("GOOGLE PLAY REVIEWS - DATA QUALITY ANALYSIS")
        print("=" * 70)
        print(f"\nDataset size: {self.total_reviews:,} reviews")

        results = {
            'overview': self.analyze_overview(),
            'missing_values': self.analyze_missing_values(),
            'rating_distribution': self.analyze_ratings(),
            'text_quality': self.analyze_text_quality(),
            'temporal': self.analyze_temporal(),
            'app_distribution': self.analyze_app_distribution(),
            'duplicates': self.analyze_duplicates(),
            'language_issues': self.analyze_language_issues(),
            'developer_replies': self.analyze_developer_replies(),
        }

        self.print_summary(results)
        return results

    def analyze_overview(self) -> Dict[str, Any]:
        """Basic dataset overview."""
        print("\n" + "-" * 70)
        print("1. DATASET OVERVIEW")
        print("-" * 70)

        apps = set(r.get('app_id', '') for r in self.data)
        authors = set(r.get('author', '') for r in self.data)

        overview = {
            'total_reviews': self.total_reviews,
            'unique_apps': len(apps),
            'unique_authors': len(authors),
            'fields_per_review': list(self.data[0].keys()) if self.data else [],
        }

        print(f"Total reviews: {overview['total_reviews']:,}")
        print(f"Unique apps: {overview['unique_apps']}")
        print(f"Unique authors: {overview['unique_authors']:,}")
        print(f"Fields per review: {len(overview['fields_per_review'])}")
        print(f"  Fields: {', '.join(overview['fields_per_review'])}")

        return overview

    def analyze_missing_values(self) -> Dict[str, Any]:
        """Analyze missing/null values in each field."""
        print("\n" + "-" * 70)
        print("2. MISSING VALUES ANALYSIS")
        print("-" * 70)

        fields = [
            'review_id', 'app_id', 'author', 'rating', 'content',
            'timestamp', 'thumbs_up', 'app_version', 'reply_content',
            'reply_timestamp', 'scraped_at'
        ]

        missing = {}
        for field in fields:
            null_count = sum(1 for r in self.data if r.get(field) is None)
            empty_count = sum(1 for r in self.data if r.get(field) == '')
            total_missing = null_count + empty_count
            pct = (total_missing / self.total_reviews * 100) if self.total_reviews > 0 else 0
            missing[field] = {
                'null': null_count,
                'empty': empty_count,
                'total': total_missing,
                'percentage': round(pct, 2)
            }

        print(f"\n{'Field':<20} {'Null':>8} {'Empty':>8} {'Total':>8} {'%':>8}")
        print("-" * 56)
        for field, stats in missing.items():
            status = "[!]" if stats['percentage'] > 5 else "[OK]" if stats['total'] == 0 else "[~]"
            print(f"{field:<20} {stats['null']:>8} {stats['empty']:>8} "
                  f"{stats['total']:>8} {stats['percentage']:>7.1f}% {status}")

        return missing

    def analyze_ratings(self) -> Dict[str, Any]:
        """Analyze rating distribution and potential skew."""
        print("\n" + "-" * 70)
        print("3. RATING DISTRIBUTION")
        print("-" * 70)

        ratings = [r.get('rating', 0) for r in self.data if r.get('rating') is not None]

        if not ratings:
            print("No rating data available")
            return {}

        distribution = Counter(ratings)
        total = len(ratings)

        # Calculate statistics
        mean_rating = statistics.mean(ratings)
        median_rating = statistics.median(ratings)
        stdev_rating = statistics.stdev(ratings) if len(ratings) > 1 else 0

        # Check for invalid ratings
        invalid_ratings = [r for r in ratings if r < 1 or r > 5]

        result = {
            'distribution': dict(distribution),
            'mean': round(mean_rating, 2),
            'median': median_rating,
            'stdev': round(stdev_rating, 2),
            'invalid_count': len(invalid_ratings),
        }

        print(f"\nMean rating: {result['mean']:.2f}")
        print(f"Median rating: {result['median']:.1f}")
        print(f"Std deviation: {result['stdev']:.2f}")
        print(f"Invalid ratings (outside 1-5): {result['invalid_count']}")

        print("\nDistribution:")
        for star in range(5, 0, -1):
            count = distribution.get(star, 0)
            pct = count / total * 100 if total > 0 else 0
            bar = "#" * int(pct / 2)
            print(f"  {star} stars: {count:>6} ({pct:>5.1f}%) {bar}")

        # Detect skew
        skew_ratio = distribution.get(5, 0) / max(distribution.get(1, 1), 1)
        if skew_ratio > 3:
            print(f"\n[!] Positive skew detected: 5-star reviews are {skew_ratio:.1f}x more than 1-star")
        elif skew_ratio < 0.33:
            print(f"\n[!] Negative skew detected: 1-star reviews dominate")

        result['skew_ratio'] = round(skew_ratio, 2)
        return result

    def analyze_text_quality(self) -> Dict[str, Any]:
        """Analyze review text content quality."""
        print("\n" + "-" * 70)
        print("4. TEXT CONTENT QUALITY")
        print("-" * 70)

        contents = [r.get('content', '') or '' for r in self.data]

        # Length analysis
        lengths = [len(c) for c in contents]
        word_counts = [len(c.split()) for c in contents]

        # Empty/very short reviews
        empty_reviews = sum(1 for c in contents if len(c.strip()) == 0)
        very_short = sum(1 for c in contents if 0 < len(c.strip()) <= 10)
        short = sum(1 for c in contents if 10 < len(c.strip()) <= 50)
        medium = sum(1 for c in contents if 50 < len(c.strip()) <= 200)
        long_reviews = sum(1 for c in contents if len(c.strip()) > 200)

        # Single word reviews
        single_word = sum(1 for c in contents if len(c.split()) == 1)

        # Repeated characters (spam indicator)
        repeated_pattern = re.compile(r'(.)\1{4,}')
        repeated_char_reviews = sum(1 for c in contents if repeated_pattern.search(c))

        # All caps reviews
        all_caps = sum(1 for c in contents if c.isupper() and len(c) > 5)

        # Reviews with only emojis/special chars
        emoji_only = sum(1 for c in contents if c and not re.search(r'[a-zA-Z]', c))

        result = {
            'char_length': {
                'min': min(lengths) if lengths else 0,
                'max': max(lengths) if lengths else 0,
                'mean': round(statistics.mean(lengths), 1) if lengths else 0,
                'median': statistics.median(lengths) if lengths else 0,
            },
            'word_count': {
                'min': min(word_counts) if word_counts else 0,
                'max': max(word_counts) if word_counts else 0,
                'mean': round(statistics.mean(word_counts), 1) if word_counts else 0,
            },
            'length_distribution': {
                'empty': empty_reviews,
                'very_short_1_10': very_short,
                'short_11_50': short,
                'medium_51_200': medium,
                'long_200+': long_reviews,
            },
            'quality_flags': {
                'single_word': single_word,
                'repeated_chars': repeated_char_reviews,
                'all_caps': all_caps,
                'emoji_only': emoji_only,
            }
        }

        print("\nCharacter length statistics:")
        print(f"  Min: {result['char_length']['min']}")
        print(f"  Max: {result['char_length']['max']}")
        print(f"  Mean: {result['char_length']['mean']:.1f}")
        print(f"  Median: {result['char_length']['median']}")

        print("\nWord count statistics:")
        print(f"  Min: {result['word_count']['min']}")
        print(f"  Max: {result['word_count']['max']}")
        print(f"  Mean: {result['word_count']['mean']:.1f}")

        print("\nLength distribution:")
        for category, count in result['length_distribution'].items():
            pct = count / self.total_reviews * 100 if self.total_reviews > 0 else 0
            print(f"  {category:<20}: {count:>6} ({pct:>5.1f}%)")

        print("\nPotential quality issues:")
        for flag, count in result['quality_flags'].items():
            pct = count / self.total_reviews * 100 if self.total_reviews > 0 else 0
            status = "[!]" if pct > 10 else "[OK]"
            print(f"  {flag:<20}: {count:>6} ({pct:>5.1f}%) {status}")

        return result

    def analyze_temporal(self) -> Dict[str, Any]:
        """Analyze temporal patterns in reviews."""
        print("\n" + "-" * 70)
        print("5. TEMPORAL ANALYSIS")
        print("-" * 70)

        timestamps = []
        parse_errors = 0

        for r in self.data:
            ts = r.get('timestamp')
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    else:
                        dt = ts
                    timestamps.append(dt)
                except (ValueError, TypeError):
                    parse_errors += 1

        if not timestamps:
            print("No valid timestamps found")
            return {'parse_errors': parse_errors}

        # Date range
        min_date = min(timestamps)
        max_date = max(timestamps)
        date_range_days = (max_date - min_date).days

        # Distribution by month
        month_dist = Counter(dt.strftime('%Y-%m') for dt in timestamps)

        # Distribution by day of week
        dow_dist = Counter(dt.strftime('%A') for dt in timestamps)

        result = {
            'date_range': {
                'earliest': min_date.isoformat(),
                'latest': max_date.isoformat(),
                'range_days': date_range_days,
            },
            'parse_errors': parse_errors,
            'by_month': dict(month_dist.most_common(12)),
            'by_day_of_week': dict(dow_dist),
        }

        print(f"\nDate range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
        print(f"Range: {date_range_days} days")
        print(f"Timestamp parse errors: {parse_errors}")

        if date_range_days < 7:
            print("[!] Very narrow date range - reviews may not be representative")

        print("\nReviews by month (top 6):")
        for month, count in list(month_dist.most_common(6)):
            print(f"  {month}: {count}")

        return result

    def analyze_app_distribution(self) -> Dict[str, Any]:
        """Analyze distribution across apps."""
        print("\n" + "-" * 70)
        print("6. APP DISTRIBUTION")
        print("-" * 70)

        app_counts = Counter(r.get('app_id', 'unknown') for r in self.data)

        result = {
            'total_apps': len(app_counts),
            'distribution': dict(app_counts),
            'min_reviews': min(app_counts.values()) if app_counts else 0,
            'max_reviews': max(app_counts.values()) if app_counts else 0,
        }

        print(f"\nTotal apps: {result['total_apps']}")
        print(f"Reviews per app range: {result['min_reviews']} - {result['max_reviews']}")

        print("\nReviews per app:")
        for app_id, count in app_counts.most_common():
            pct = count / self.total_reviews * 100 if self.total_reviews > 0 else 0
            print(f"  {app_id:<45}: {count:>6} ({pct:>5.1f}%)")

        # Check for imbalance
        if app_counts:
            max_count = max(app_counts.values())
            min_count = min(app_counts.values())
            if max_count > min_count * 2:
                print("\n[!] Imbalanced app distribution detected")

        return result

    def analyze_duplicates(self) -> Dict[str, Any]:
        """Detect duplicate reviews."""
        print("\n" + "-" * 70)
        print("7. DUPLICATE ANALYSIS")
        print("-" * 70)

        # Duplicate review IDs
        review_ids = [r.get('review_id', '') for r in self.data]
        id_counts = Counter(review_ids)
        duplicate_ids = {k: v for k, v in id_counts.items() if v > 1}

        # Duplicate content
        contents = [r.get('content', '') for r in self.data]
        content_counts = Counter(contents)
        duplicate_content = {k: v for k, v in content_counts.items() if v > 1 and k}

        # Exact duplicate reviews (same ID and content)
        review_hashes = Counter(
            (r.get('review_id', ''), r.get('content', ''))
            for r in self.data
        )
        exact_duplicates = sum(1 for v in review_hashes.values() if v > 1)

        result = {
            'duplicate_review_ids': len(duplicate_ids),
            'duplicate_content': len(duplicate_content),
            'exact_duplicates': exact_duplicates,
            'top_duplicate_content': list(content_counts.most_common(5)),
        }

        print(f"\nDuplicate review IDs: {result['duplicate_review_ids']}")
        print(f"Duplicate content (different IDs): {result['duplicate_content']}")
        print(f"Exact duplicate reviews: {result['exact_duplicates']}")

        if duplicate_content:
            print("\nMost repeated review content:")
            for content, count in list(content_counts.most_common(5)):
                if count > 1 and content:
                    preview = content[:50] + "..." if len(content) > 50 else content
                    print(f"  [{count}x] \"{preview}\"")

        return result

    def analyze_language_issues(self) -> Dict[str, Any]:
        """Detect potential language/encoding issues."""
        print("\n" + "-" * 70)
        print("8. LANGUAGE & ENCODING ISSUES")
        print("-" * 70)

        contents = [r.get('content', '') or '' for r in self.data]

        # Non-ASCII content (potential non-English)
        non_ascii = sum(1 for c in contents if c and not c.isascii())

        # Encoding issues (common patterns)
        encoding_issues = sum(1 for c in contents if '�' in c or '\ufffd' in c)

        # HTML entities not decoded
        html_entities = sum(1 for c in contents if '&amp;' in c or '&lt;' in c or '&#' in c)

        # Detect primary scripts
        scripts = {
            'latin': 0,
            'cyrillic': 0,
            'arabic': 0,
            'devanagari': 0,
            'cjk': 0,
            'other': 0,
        }

        for c in contents:
            if not c:
                continue
            # Simple heuristic based on character ranges
            if re.search(r'[а-яА-ЯёЁ]', c):
                scripts['cyrillic'] += 1
            elif re.search(r'[\u0600-\u06FF]', c):
                scripts['arabic'] += 1
            elif re.search(r'[\u0900-\u097F]', c):
                scripts['devanagari'] += 1
            elif re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', c):
                scripts['cjk'] += 1
            elif re.search(r'[a-zA-Z]', c):
                scripts['latin'] += 1
            else:
                scripts['other'] += 1

        result = {
            'non_ascii_reviews': non_ascii,
            'encoding_errors': encoding_issues,
            'html_entities': html_entities,
            'script_distribution': scripts,
        }

        pct_non_ascii = non_ascii / self.total_reviews * 100 if self.total_reviews > 0 else 0
        print(f"\nNon-ASCII reviews: {non_ascii} ({pct_non_ascii:.1f}%)")
        print(f"Encoding errors (replacement chars): {encoding_issues}")
        print(f"Unescaped HTML entities: {html_entities}")

        print("\nScript distribution:")
        for script, count in scripts.items():
            if count > 0:
                pct = count / self.total_reviews * 100
                print(f"  {script:<15}: {count:>6} ({pct:>5.1f}%)")

        return result

    def analyze_developer_replies(self) -> Dict[str, Any]:
        """Analyze developer reply patterns."""
        print("\n" + "-" * 70)
        print("9. DEVELOPER REPLIES")
        print("-" * 70)

        replies = [r for r in self.data if r.get('reply_content')]

        reply_count = len(replies)
        reply_pct = reply_count / self.total_reviews * 100 if self.total_reviews > 0 else 0

        # Reply rates by rating
        reply_by_rating = {}
        for star in range(1, 6):
            total_for_star = sum(1 for r in self.data if r.get('rating') == star)
            replied_for_star = sum(1 for r in self.data if r.get('rating') == star and r.get('reply_content'))
            rate = replied_for_star / total_for_star * 100 if total_for_star > 0 else 0
            reply_by_rating[star] = {
                'total': total_for_star,
                'replied': replied_for_star,
                'rate': round(rate, 1)
            }

        result = {
            'total_replies': reply_count,
            'reply_rate': round(reply_pct, 1),
            'reply_by_rating': reply_by_rating,
        }

        print(f"\nReviews with developer replies: {reply_count} ({reply_pct:.1f}%)")

        print("\nReply rate by rating:")
        for star in range(5, 0, -1):
            stats = reply_by_rating[star]
            print(f"  {star} stars: {stats['replied']}/{stats['total']} ({stats['rate']:.1f}%)")

        return result

    def print_summary(self, results: Dict[str, Any]):
        """Print executive summary of data quality."""
        print("\n" + "=" * 70)
        print("EXECUTIVE SUMMARY - DATA QUALITY ISSUES")
        print("=" * 70)

        issues = []

        # Check missing values
        for field, stats in results['missing_values'].items():
            if stats['percentage'] > 5 and field not in ['reply_content', 'reply_timestamp', 'app_version']:
                issues.append(f"High missing rate for '{field}': {stats['percentage']:.1f}%")

        # Check text quality
        text_stats = results['text_quality']
        empty_pct = text_stats['length_distribution']['empty'] / self.total_reviews * 100 if self.total_reviews > 0 else 0
        if empty_pct > 5:
            issues.append(f"High empty review rate: {empty_pct:.1f}%")

        single_word_pct = text_stats['quality_flags']['single_word'] / self.total_reviews * 100 if self.total_reviews > 0 else 0
        if single_word_pct > 20:
            issues.append(f"High single-word review rate: {single_word_pct:.1f}%")

        # Check duplicates
        if results['duplicates']['duplicate_review_ids'] > 0:
            issues.append(f"Duplicate review IDs detected: {results['duplicates']['duplicate_review_ids']}")

        # Check temporal
        if results['temporal'].get('date_range', {}).get('range_days', 0) < 7:
            issues.append("Narrow date range may not be representative")

        # Check encoding
        if results['language_issues']['encoding_errors'] > 0:
            issues.append(f"Encoding errors detected: {results['language_issues']['encoding_errors']}")

        if issues:
            print("\n[!] Issues requiring attention:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("\n[OK] No critical data quality issues detected")

        print("\nDataset ready for downstream processing with noted considerations.")


def main():
    """Run analysis on the latest data file."""
    import sys

    # Find the largest/most recent JSON file
    data_dir = Path("data")
    json_files = list(data_dir.glob("google_play_reviews_*.json"))

    if not json_files:
        print("No data files found in data/ directory")
        sys.exit(1)

    # Use the largest file (most reviews)
    target_file = max(json_files, key=lambda f: f.stat().st_size)
    print(f"Analyzing: {target_file}")
    print(f"File size: {target_file.stat().st_size / 1024 / 1024:.2f} MB\n")

    analyzer = DataQualityAnalyzer.from_json_file(target_file)
    results = analyzer.run_full_analysis()

    # Save results
    output_file = data_dir / "data_quality_report.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull report saved to: {output_file}")


if __name__ == "__main__":
    main()
