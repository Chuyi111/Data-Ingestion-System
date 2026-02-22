# Ingestion Monitoring Layer

Self-monitoring system that runs automatically after every ingestion cycle, evaluating pipeline health, detecting anomalies, and storing structured reports.

## Architecture

```
Scheduler loop
  └── Pipeline.run()         ← scrape + insert
  └── Reporter.report_run()  ← console output
  └── Monitor.evaluate_run() ← health analysis (NEW)
        ├── compute metrics (dedup rate, error rate, null rates, ...)
        ├── compute deltas (vs previous run, vs last-5 average)
        ├── detect anomalies (threshold checks, z-scores)
        ├── store report → ingestion_metrics table
        └── print alerts → console + log
```

## Anomaly Detection Thresholds

| Check | Default | Level |
|-------|---------|-------|
| Insert count drop >50% vs recent avg | `reviews_inserted_drop_pct = 50%` | WARNING |
| Dedup rate >99.5% (API staleness) | `dedup_rate_ceiling = 0.995` | WARNING |
| Duration >2x recent avg | `duration_multiplier = 2.0` | WARNING |
| Any app failure | `error_rate_max = 0.0` | WARNING |
| Null field rate shifted >5pp | `null_rate_shift_pct = 5.0` | INFO |
| Z-score >2.0 std devs from mean | hardcoded | INFO |

Thresholds are configurable via `IngestionMonitor.THRESHOLDS` dict.

## Health Report Structure

Each run produces a JSON report stored in `ingestion_metrics.report_json`:

```
run_id, timestamp, status
├── metrics       → dedup_rate, error_rate, duration, ingestion_rate, null rates
├── deltas        → vs_previous (change_pct), vs_avg_last_5 (z_score)
├── data_quality  → null rates vs baseline, content length
├── alerts[]      → level, metric, message, threshold, actual_value
└── app_health[]  → per-app status (ok / stale / error)
```

Key metrics are also denormalized as columns on `ingestion_metrics` for fast SQL queries.

## CLI Commands

```bash
# Show latest full health report
python -m src.ingestion.cli --health

# Show last N runs as a summary table
python -m src.ingestion.cli --health-history 10

# Backfill metrics for historical runs (one-time)
python -m src.ingestion.cli --backfill-metrics
```

## Files

| File | Role |
|------|------|
| `src/ingestion/monitor.py` | `IngestionMonitor` class — metrics, anomaly detection, storage |
| `src/database/schema.sql` | `ingestion_metrics` table definition |
| `src/ingestion/scheduler.py` | Hook in `_report()` that invokes the monitor |
| `src/ingestion/cli.py` | `--health`, `--health-history`, `--backfill-metrics` flags |

## Querying Metrics Directly

```sql
-- Runs with anomalies
SELECT run_id, alerts_count, reviews_inserted, dedup_rate
FROM ingestion_metrics WHERE alerts_count > 0;

-- Dedup rate trend
SELECT run_id, dedup_rate, duration_seconds
FROM ingestion_metrics ORDER BY run_id;

-- Data quality over time
SELECT run_id, app_version_null_rate, reply_content_null_rate
FROM ingestion_metrics ORDER BY run_id;

-- Full JSON report for a specific run
SELECT report_json FROM ingestion_metrics WHERE run_id = 13;
```
