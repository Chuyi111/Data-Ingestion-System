"""
Deep Descriptive & Statistical Analysis of Google Play Reviews.

Goes beyond surface-level counts to build practical intuition about the
dataset: distributions, correlations, time patterns, per-app behavior,
and text-level quality signals relevant to downstream labeling and modeling.
"""

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
import statistics
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def percentile(data: List[float], p: float) -> float:
    """Calculate p-th percentile (0-100)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def safe_div(a, b, default=0.0):
    return a / b if b else default


def histogram_bar(value, max_value, width=40):
    filled = int(value / max_value * width) if max_value else 0
    return "#" * filled


def section(title: str, level: int = 1):
    if level == 1:
        print(f"\n{'=' * 72}")
        print(f"  {title}")
        print(f"{'=' * 72}")
    else:
        print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_dataset(data_dir: Path) -> List[Dict[str, Any]]:
    json_files = list(data_dir.glob("google_play_reviews*.json"))
    if not json_files:
        print("No data files found in data/ directory")
        sys.exit(1)
    target = max(json_files, key=lambda f: f.stat().st_size)
    print(f"Source file : {target}")
    print(f"File size   : {target.stat().st_size / 1024 / 1024:.2f} MB")
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"Total rows  : {len(data):,}")
    return data


# ---------------------------------------------------------------------------
# 1. Rating analysis
# ---------------------------------------------------------------------------

def analyze_ratings(data: List[Dict]) -> None:
    section("1. RATING DISTRIBUTION & SUMMARY STATISTICS")

    ratings = [r["rating"] for r in data]
    n = len(ratings)
    dist = Counter(ratings)

    mean_r = statistics.mean(ratings)
    median_r = statistics.median(ratings)
    mode_r = statistics.mode(ratings)
    stdev_r = statistics.stdev(ratings)

    # Skewness (Fisher-Pearson)
    skewness = (
        sum((x - mean_r) ** 3 for x in ratings) / n
    ) / (stdev_r ** 3) if stdev_r else 0

    # Kurtosis (excess)
    kurtosis = (
        sum((x - mean_r) ** 4 for x in ratings) / n
    ) / (stdev_r ** 4) - 3 if stdev_r else 0

    print(f"\n  Count   : {n:,}")
    print(f"  Mean    : {mean_r:.3f}")
    print(f"  Median  : {median_r:.1f}")
    print(f"  Mode    : {mode_r}")
    print(f"  Std Dev : {stdev_r:.3f}")
    print(f"  Skewness: {skewness:.3f}  {'(left-skewed / negative-heavy)' if skewness < -0.5 else '(right-skewed / positive-heavy)' if skewness > 0.5 else '(roughly symmetric)'}")
    print(f"  Kurtosis: {kurtosis:.3f}  {'(heavy tails)' if kurtosis > 1 else '(light tails)' if kurtosis < -1 else '(near normal)'}")

    max_count = max(dist.values())
    print("\n  Star | Count  |    %   | Distribution")
    print("  " + "-" * 58)
    for star in range(5, 0, -1):
        c = dist.get(star, 0)
        pct = c / n * 100
        bar = histogram_bar(c, max_count)
        print(f"    {star}  | {c:>6} | {pct:>5.1f}% | {bar}")

    # Sentiment buckets
    positive = sum(1 for r in ratings if r >= 4)
    neutral = sum(1 for r in ratings if r == 3)
    negative = sum(1 for r in ratings if r <= 2)
    print(f"\n  Sentiment buckets (for labeling reference):")
    print(f"    Positive (4-5) : {positive:>6} ({positive/n*100:.1f}%)")
    print(f"    Neutral  (3)   : {neutral:>6} ({neutral/n*100:.1f}%)")
    print(f"    Negative (1-2) : {negative:>6} ({negative/n*100:.1f}%)")
    print(f"    Pos:Neg ratio  : {safe_div(positive, negative):.2f}:1")


# ---------------------------------------------------------------------------
# 2. Text length analysis
# ---------------------------------------------------------------------------

def analyze_text_lengths(data: List[Dict]) -> None:
    section("2. REVIEW TEXT LENGTH DISTRIBUTIONS")

    contents = [r.get("content", "") or "" for r in data]
    char_lens = [len(c) for c in contents]
    word_lens = [len(c.split()) for c in contents]

    for label, lens in [("Character length", char_lens), ("Word count", word_lens)]:
        section(label, level=2)
        p5 = percentile(lens, 5)
        p25 = percentile(lens, 25)
        p50 = percentile(lens, 50)
        p75 = percentile(lens, 75)
        p95 = percentile(lens, 95)
        p99 = percentile(lens, 99)
        mean_l = statistics.mean(lens)
        stdev_l = statistics.stdev(lens) if len(lens) > 1 else 0

        print(f"    Min     : {min(lens)}")
        print(f"    P5      : {p5:.0f}")
        print(f"    P25 (Q1): {p25:.0f}")
        print(f"    P50 (med): {p50:.0f}")
        print(f"    Mean    : {mean_l:.1f}")
        print(f"    P75 (Q3): {p75:.0f}")
        print(f"    P95     : {p95:.0f}")
        print(f"    P99     : {p99:.0f}")
        print(f"    Max     : {max(lens)}")
        print(f"    Std Dev : {stdev_l:.1f}")
        print(f"    IQR     : {p75 - p25:.0f}")

    # Bucketized histogram of character lengths
    section("Character-length histogram", level=2)
    buckets = [(0, 0, "empty"), (1, 10, "1-10"), (11, 25, "11-25"),
               (26, 50, "26-50"), (51, 100, "51-100"), (101, 200, "101-200"),
               (201, 350, "201-350"), (351, 500, "351-500")]
    bucket_counts = []
    for lo, hi, label in buckets:
        c = sum(1 for l in char_lens if lo <= l <= hi)
        bucket_counts.append((label, c))
    max_bc = max(c for _, c in bucket_counts)
    print(f"    {'Bucket':<12} {'Count':>7} {'%':>7}  Distribution")
    print("    " + "-" * 55)
    for label, c in bucket_counts:
        pct = c / len(char_lens) * 100
        bar = histogram_bar(c, max_bc, 30)
        print(f"    {label:<12} {c:>7} {pct:>6.1f}%  {bar}")

    # Length by rating
    section("Median character length by rating", level=2)
    by_rating = defaultdict(list)
    for r in data:
        by_rating[r["rating"]].append(len(r.get("content", "") or ""))
    for star in range(5, 0, -1):
        vals = by_rating[star]
        med = statistics.median(vals) if vals else 0
        avg = statistics.mean(vals) if vals else 0
        print(f"    {star} stars: median={med:>5.0f} chars, mean={avg:>6.1f} chars  (n={len(vals)})")


# ---------------------------------------------------------------------------
# 3. Temporal patterns
# ---------------------------------------------------------------------------

def analyze_temporal(data: List[Dict]) -> None:
    section("3. TIME-BASED PATTERNS")

    timestamps = []
    for r in data:
        ts = r.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except ValueError:
                pass

    if not timestamps:
        print("  No parseable timestamps.")
        return

    min_dt = min(timestamps)
    max_dt = max(timestamps)
    span = (max_dt - min_dt).days

    print(f"\n  Earliest review : {min_dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Latest review   : {max_dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Span            : {span} days")

    # Daily volume
    section("Reviews per day", level=2)
    day_counts = Counter(dt.strftime("%Y-%m-%d") for dt in timestamps)
    days_sorted = sorted(day_counts.items())
    volumes = [c for _, c in days_sorted]
    if volumes:
        print(f"    Days with data : {len(volumes)}")
        print(f"    Mean per day   : {statistics.mean(volumes):.1f}")
        print(f"    Median per day : {statistics.median(volumes):.0f}")
        print(f"    Min per day    : {min(volumes)}")
        print(f"    Max per day    : {max(volumes)}")
        print(f"    Std Dev        : {statistics.stdev(volumes):.1f}" if len(volumes) > 1 else "")

    # Day-of-week distribution
    section("Reviews by day of week", level=2)
    dow_counts = Counter(dt.strftime("%A") for dt in timestamps)
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    max_dow = max(dow_counts.values()) if dow_counts else 1
    for day in dow_order:
        c = dow_counts.get(day, 0)
        bar = histogram_bar(c, max_dow, 30)
        print(f"    {day:<12}: {c:>5}  {bar}")

    # Hour-of-day distribution
    section("Reviews by hour of day (UTC)", level=2)
    hour_counts = Counter(dt.hour for dt in timestamps)
    max_hour = max(hour_counts.values()) if hour_counts else 1
    for h in range(24):
        c = hour_counts.get(h, 0)
        bar = histogram_bar(c, max_hour, 25)
        print(f"    {h:>2}:00 : {c:>5}  {bar}")

    # Average rating over time (by day)
    section("Average rating by day", level=2)
    day_ratings = defaultdict(list)
    for r in data:
        ts = r.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                day = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
                day_ratings[day].append(r["rating"])
            except ValueError:
                pass
    for day in sorted(day_ratings.keys()):
        vals = day_ratings[day]
        avg = statistics.mean(vals)
        print(f"    {day}: avg={avg:.2f}  n={len(vals)}")


# ---------------------------------------------------------------------------
# 4. Per-app breakdown
# ---------------------------------------------------------------------------

def analyze_per_app(data: List[Dict]) -> None:
    section("4. PER-APP BREAKDOWN")

    apps = defaultdict(list)
    for r in data:
        apps[r.get("app_id", "unknown")].append(r)

    header = (f"    {'App':<40} {'N':>5} {'Mean':>5} {'Med':>4} "
              f"{'StdDev':>6} {'AvgWords':>8} {'Short%':>7} {'Reply%':>7}")
    print(header)
    print("    " + "-" * (len(header) - 4))

    rows = []
    for app_id, reviews in sorted(apps.items()):
        n = len(reviews)
        ratings = [r["rating"] for r in reviews]
        mean_r = statistics.mean(ratings)
        med_r = statistics.median(ratings)
        std_r = statistics.stdev(ratings) if n > 1 else 0
        word_counts = [len((r.get("content", "") or "").split()) for r in reviews]
        avg_words = statistics.mean(word_counts) if word_counts else 0
        short_pct = sum(1 for w in word_counts if w <= 3) / n * 100
        reply_pct = sum(1 for r in reviews if r.get("reply_content")) / n * 100

        rows.append((app_id, n, mean_r, med_r, std_r, avg_words, short_pct, reply_pct))

    for app_id, n, mean_r, med_r, std_r, avg_words, short_pct, reply_pct in rows:
        short_name = app_id if len(app_id) <= 40 else "..." + app_id[-37:]
        print(f"    {short_name:<40} {n:>5} {mean_r:>5.2f} {med_r:>4.1f} "
              f"{std_r:>6.2f} {avg_words:>8.1f} {short_pct:>6.1f}% {reply_pct:>6.1f}%")

    # Cross-app variance
    app_means = [statistics.mean(r["rating"] for r in revs) for revs in apps.values()]
    if len(app_means) > 1:
        print(f"\n  Cross-app rating variance: {statistics.variance(app_means):.4f}")
        print(f"  Cross-app rating range  : {min(app_means):.2f} - {max(app_means):.2f}")


# ---------------------------------------------------------------------------
# 5. Data quality deep-dive
# ---------------------------------------------------------------------------

def analyze_data_quality(data: List[Dict]) -> None:
    section("5. DATA QUALITY DEEP-DIVE")
    n = len(data)

    # 5a. Duplicate analysis
    section("Duplicate review IDs", level=2)
    id_counts = Counter(r.get("review_id", "") for r in data)
    dup_ids = {k: v for k, v in id_counts.items() if v > 1}
    print(f"    Unique review IDs : {len(id_counts):,}")
    print(f"    Duplicate IDs     : {len(dup_ids)}")
    if dup_ids:
        print(f"    Total dup rows    : {sum(dup_ids.values()):,}")

    # 5b. Content duplicates (exact match)
    section("Exact content duplicates", level=2)
    content_counts = Counter(r.get("content", "") for r in data)
    dup_contents = {k: v for k, v in content_counts.items() if v > 1 and k}
    print(f"    Unique texts      : {len(content_counts):,}")
    print(f"    Repeated texts    : {len(dup_contents):,}")
    total_dup_rows = sum(v for v in dup_contents.values())
    print(f"    Rows with dup text: {total_dup_rows:,} ({total_dup_rows/n*100:.1f}%)")

    print("\n    Top 10 repeated review texts:")
    for text, count in content_counts.most_common(12):
        if count < 2 or not text:
            continue
        preview = text[:60].replace("\n", " ")
        # Strip non-ascii for safe console output
        preview = preview.encode("ascii", errors="replace").decode("ascii")
        if len(text) > 60:
            preview += "..."
        print(f"      {count:>4}x  \"{preview}\"")

    # 5c. Missing / null fields
    section("Field completeness", level=2)
    fields = list(data[0].keys()) if data else []
    print(f"    {'Field':<22} {'Present':>8} {'Null':>8} {'Empty':>8} {'Fill %':>8}")
    print("    " + "-" * 58)
    for field in fields:
        present = sum(1 for r in data if r.get(field) is not None and r.get(field) != "")
        null_c = sum(1 for r in data if r.get(field) is None)
        empty_c = sum(1 for r in data if r.get(field) == "")
        fill_pct = present / n * 100
        print(f"    {field:<22} {present:>8} {null_c:>8} {empty_c:>8} {fill_pct:>7.1f}%")

    # 5d. app_version missingness by app
    section("app_version missing rate by app", level=2)
    apps = defaultdict(lambda: {"total": 0, "missing": 0})
    for r in data:
        aid = r.get("app_id", "")
        apps[aid]["total"] += 1
        if r.get("app_version") is None or r.get("app_version") == "":
            apps[aid]["missing"] += 1
    for aid in sorted(apps):
        t = apps[aid]["total"]
        m = apps[aid]["missing"]
        pct = m / t * 100
        flag = " <--" if pct > 25 else ""
        print(f"    {aid:<45}: {m:>4}/{t:>4} missing ({pct:>5.1f}%){flag}")

    # 5e. Rating vs content length correlation
    section("Rating vs. review length (chars)", level=2)
    by_rating = defaultdict(list)
    for r in data:
        by_rating[r["rating"]].append(len(r.get("content", "") or ""))
    print(f"    {'Star':>4}  {'N':>6}  {'Mean':>7}  {'Median':>7}  {'P95':>7}  {'%<=10ch':>8}")
    print("    " + "-" * 50)
    for star in range(5, 0, -1):
        lens = by_rating[star]
        nn = len(lens)
        mn = statistics.mean(lens) if lens else 0
        md = statistics.median(lens) if lens else 0
        p95 = percentile(lens, 95)
        short_pct = sum(1 for l in lens if l <= 10) / nn * 100 if nn else 0
        print(f"    {star:>4}  {nn:>6}  {mn:>7.1f}  {md:>7.0f}  {p95:>7.0f}  {short_pct:>7.1f}%")

    # 5f. Suspicious patterns
    section("Suspicious / low-quality review patterns", level=2)
    patterns = {
        "Empty or whitespace-only": lambda c: len(c.strip()) == 0,
        "Single word": lambda c: len(c.split()) == 1,
        "2-3 words": lambda c: 2 <= len(c.split()) <= 3,
        "All uppercase (>5 chars)": lambda c: c.isupper() and len(c) > 5,
        "Repeated chars (5+)": lambda c: bool(re.search(r'(.)\1{4,}', c)),
        "No Latin letters": lambda c: bool(c) and not re.search(r'[a-zA-Z]', c),
        "Excessive punctuation (>30%)": lambda c: len(c) > 5 and sum(1 for ch in c if ch in '!?.,:;') / len(c) > 0.3,
        "URL or link present": lambda c: bool(re.search(r'https?://|www\.', c)),
    }
    contents = [r.get("content", "") or "" for r in data]
    for label, fn in patterns.items():
        count = sum(1 for c in contents if fn(c))
        pct = count / n * 100
        flag = " [!]" if pct > 10 else ""
        print(f"    {label:<35}: {count:>6} ({pct:>5.1f}%){flag}")

    # Combined: reviews that would likely be filtered before labeling
    filterable = sum(
        1 for c in contents
        if len(c.strip()) == 0
        or len(c.split()) <= 2
        or (not re.search(r'[a-zA-Z]', c) and c)
    )
    print(f"\n    Combined low-signal reviews     : {filterable:>6} ({filterable/n*100:.1f}%)")
    print(f"    Usable for labeling (estimated) : {n - filterable:>6} ({(n-filterable)/n*100:.1f}%)")


# ---------------------------------------------------------------------------
# 6. Thumbs-up / helpfulness
# ---------------------------------------------------------------------------

def analyze_thumbs_up(data: List[Dict]) -> None:
    section("6. THUMBS-UP (HELPFULNESS) DISTRIBUTION")

    thumbs = [r.get("thumbs_up", 0) for r in data]
    n = len(thumbs)
    zero = sum(1 for t in thumbs if t == 0)
    nonzero = n - zero

    print(f"\n  Zero thumbs-up : {zero:>6} ({zero/n*100:.1f}%)")
    print(f"  Non-zero       : {nonzero:>6} ({nonzero/n*100:.1f}%)")

    if nonzero:
        nz_vals = [t for t in thumbs if t > 0]
        print(f"\n  Among non-zero:")
        print(f"    Mean   : {statistics.mean(nz_vals):.1f}")
        print(f"    Median : {statistics.median(nz_vals):.0f}")
        print(f"    P95    : {percentile(nz_vals, 95):.0f}")
        print(f"    Max    : {max(nz_vals)}")

    # Thumbs-up by rating
    section("Mean thumbs-up by rating", level=2)
    by_rating = defaultdict(list)
    for r in data:
        by_rating[r["rating"]].append(r.get("thumbs_up", 0))
    for star in range(5, 0, -1):
        vals = by_rating[star]
        avg = statistics.mean(vals) if vals else 0
        nz = sum(1 for v in vals if v > 0)
        print(f"    {star} stars: mean={avg:>6.2f}, non-zero={nz:>4} ({nz/len(vals)*100:.1f}%)")


# ---------------------------------------------------------------------------
# 7. Developer reply patterns
# ---------------------------------------------------------------------------

def analyze_replies(data: List[Dict]) -> None:
    section("7. DEVELOPER REPLY ANALYSIS")

    replied = [r for r in data if r.get("reply_content")]
    unreplied = [r for r in data if not r.get("reply_content")]
    n = len(data)
    nr = len(replied)

    print(f"\n  Replied   : {nr:>6} ({nr/n*100:.1f}%)")
    print(f"  Unreplied : {len(unreplied):>6} ({len(unreplied)/n*100:.1f}%)")

    if replied:
        reply_lens = [len(r["reply_content"]) for r in replied]
        print(f"\n  Reply text length:")
        print(f"    Mean   : {statistics.mean(reply_lens):.1f} chars")
        print(f"    Median : {statistics.median(reply_lens):.0f} chars")
        print(f"    P95    : {percentile(reply_lens, 95):.0f} chars")

    # Reply rate by app
    section("Reply rate by app", level=2)
    apps = defaultdict(lambda: {"total": 0, "replied": 0})
    for r in data:
        aid = r.get("app_id", "")
        apps[aid]["total"] += 1
        if r.get("reply_content"):
            apps[aid]["replied"] += 1
    for aid in sorted(apps):
        t = apps[aid]["total"]
        rr = apps[aid]["replied"]
        pct = rr / t * 100
        print(f"    {aid:<45}: {rr:>4}/{t:>4} ({pct:>5.1f}%)")

    # Avg rating: replied vs unreplied
    if replied and unreplied:
        avg_replied = statistics.mean(r["rating"] for r in replied)
        avg_unreplied = statistics.mean(r["rating"] for r in unreplied)
        print(f"\n  Avg rating (replied)   : {avg_replied:.2f}")
        print(f"  Avg rating (unreplied) : {avg_unreplied:.2f}")
        print(f"  Delta                  : {avg_replied - avg_unreplied:+.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data = load_dataset(Path("data"))

    print(f"\n{'#' * 72}")
    print(f"#  DEEP DESCRIPTIVE ANALYSIS")
    print(f"{'#' * 72}")

    analyze_ratings(data)
    analyze_text_lengths(data)
    analyze_temporal(data)
    analyze_per_app(data)
    analyze_data_quality(data)
    analyze_thumbs_up(data)
    analyze_replies(data)

    section("END OF ANALYSIS")
    print("  All checks complete.\n")


if __name__ == "__main__":
    main()
