"""
Ingestion monitoring: health metrics, anomaly detection, and alerting.

Analyzes each ingestion run for performance degradation, data quality
shifts, and operational anomalies. Stores structured reports in the
ingestion_metrics table for trend analysis.
"""

import json
import logging
import statistics
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

from src.ingestion.pipeline import RunResult, AppRunResult
from src.database.db_manager import DatabaseManager
from src.utils.logger import setup_logger


# =========================================================================
# Dataclasses
# =========================================================================

@dataclass
class Alert:
    """A single anomaly or noteworthy event."""
    level: str          # "INFO", "WARNING"
    metric: str
    message: str
    threshold: Optional[float] = None
    actual_value: Optional[float] = None


@dataclass
class HealthReport:
    """Complete health report for an ingestion run."""
    run_id: int
    timestamp: str
    status: str
    metrics: Dict[str, Any]
    deltas: Dict[str, Any]
    data_quality: Dict[str, Any]
    alerts: List[Alert] = field(default_factory=list)
    app_health: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "metrics": self.metrics,
            "deltas": self.deltas,
            "data_quality": self.data_quality,
            "alerts": [asdict(a) for a in self.alerts],
            "app_health": self.app_health,
        }


# =========================================================================
# Monitor
# =========================================================================

class IngestionMonitor:
    """
    Self-monitoring layer for the ingestion pipeline.

    Computes health metrics from RunResult + DB state, detects anomalies
    by comparing against recent run history, and stores structured reports.
    """

    THRESHOLDS = {
        "reviews_inserted_drop_pct": 50.0,
        "dedup_rate_ceiling": 0.995,
        "duration_multiplier": 2.0,
        "error_rate_max": 0.0,
        "null_rate_shift_pct": 5.0,
    }

    def __init__(
        self,
        db: DatabaseManager,
        logger: Optional[logging.Logger] = None,
        lookback_window: int = 10,
    ):
        self.db = db
        self.logger = logger or setup_logger(
            "ingestion.monitor", log_file="ingestion.log"
        )
        self.lookback_window = lookback_window

    # -----------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------

    def evaluate_run(self, result: RunResult) -> HealthReport:
        """Evaluate a completed run and produce a health report."""
        self.logger.info(f"Evaluating health for run #{result.run_id}")

        metrics = self._compute_metrics(result)
        deltas = self._compute_deltas(result, metrics)
        data_quality = self._compute_data_quality(result.run_id)
        alerts = self._detect_anomalies(result, metrics, deltas, data_quality)
        app_health = self._build_app_health(result.app_results)

        ts = (
            result.completed_at.isoformat()
            if result.completed_at
            else datetime.now().isoformat()
        )

        return HealthReport(
            run_id=result.run_id,
            timestamp=ts,
            status=result.status,
            metrics=metrics,
            deltas=deltas,
            data_quality=data_quality,
            alerts=alerts,
            app_health=app_health,
        )

    # -----------------------------------------------------------------
    # Metrics computation
    # -----------------------------------------------------------------

    def _compute_metrics(self, result: RunResult) -> Dict[str, Any]:
        """Core performance metrics derived from RunResult."""
        total_apps = result.total_apps_processed + result.total_apps_failed
        dedup_rate = (
            result.total_reviews_skipped / result.total_reviews_fetched
            if result.total_reviews_fetched > 0 else 0.0
        )
        error_rate = (
            result.total_apps_failed / total_apps
            if total_apps > 0 else 0.0
        )
        ingestion_rate = (
            (result.total_reviews_fetched / result.duration_seconds) * 60
            if result.duration_seconds > 0 else 0.0
        )

        return {
            "reviews_inserted": result.total_reviews_inserted,
            "reviews_fetched": result.total_reviews_fetched,
            "reviews_skipped": result.total_reviews_skipped,
            "dedup_rate": round(dedup_rate, 4),
            "error_rate": round(error_rate, 4),
            "duration_seconds": round(result.duration_seconds, 2),
            "ingestion_rate_per_min": round(ingestion_rate, 2),
            "apps_processed": result.total_apps_processed,
            "apps_failed": result.total_apps_failed,
        }

    def _compute_deltas(
        self, result: RunResult, metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare current run against recent history."""
        conn = self.db.connect()

        rows = conn.execute("""
            SELECT run_id, total_reviews_collected,
                   CAST(
                       (julianday(completed_at) - julianday(started_at))
                       * 86400 AS REAL
                   ) AS duration_sec
            FROM scrape_runs
            WHERE run_id < ? AND status IN ('completed', 'partial')
              AND completed_at IS NOT NULL
            ORDER BY run_id DESC
            LIMIT ?
        """, (result.run_id, self.lookback_window)).fetchall()

        if not rows:
            return {"vs_previous": {}, "vs_avg_last_5": {}}

        # vs previous
        vs_previous = {}
        prev = rows[0]
        vs_previous["reviews_inserted"] = self._change(
            prev["total_reviews_collected"], metrics["reviews_inserted"]
        )
        vs_previous["duration"] = self._change(
            prev["duration_sec"] or 0, metrics["duration_seconds"]
        )

        # vs average of last 5
        window = rows[:5]
        avg_ins = statistics.mean(
            [r["total_reviews_collected"] for r in window]
        )
        avg_dur = statistics.mean(
            [(r["duration_sec"] or 0) for r in window]
        )

        std_ins = (
            statistics.stdev([r["total_reviews_collected"] for r in window])
            if len(window) > 1 else 0
        )

        vs_avg = {}
        vs_avg["reviews_inserted"] = self._deviation(
            avg_ins, metrics["reviews_inserted"], std_ins
        )
        vs_avg["duration"] = self._deviation(
            avg_dur, metrics["duration_seconds"], 0
        )

        return {"vs_previous": vs_previous, "vs_avg_last_5": vs_avg}

    def _compute_data_quality(self, run_id: int) -> Dict[str, Any]:
        """Null rates for this run's reviews vs overall baseline."""
        conn = self.db.connect()

        # This run's reviews (via review_scrape_log)
        cur = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN r.app_version IS NULL THEN 1 ELSE 0 END)
                    AS null_version,
                SUM(CASE WHEN r.reply_content IS NULL THEN 1 ELSE 0 END)
                    AS null_reply,
                SUM(CASE WHEN r.content IS NULL OR r.content = '' THEN 1 ELSE 0 END)
                    AS empty_content,
                AVG(LENGTH(r.content)) AS avg_len
            FROM reviews r
            JOIN review_scrape_log rsl ON r.review_id = rsl.review_id
            WHERE rsl.run_id = ?
        """, (run_id,)).fetchone()

        # Overall baseline
        base = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN app_version IS NULL THEN 1 ELSE 0 END)
                    AS null_version,
                SUM(CASE WHEN reply_content IS NULL THEN 1 ELSE 0 END)
                    AS null_reply,
                SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END)
                    AS empty_content,
                AVG(LENGTH(content)) AS avg_len
            FROM reviews
        """).fetchone()

        ct = cur["total"] or 1
        bt = base["total"] or 1

        cur_ver = (cur["null_version"] or 0) / ct
        cur_rep = (cur["null_reply"] or 0) / ct
        cur_emp = (cur["empty_content"] or 0) / ct
        base_ver = (base["null_version"] or 0) / bt
        base_rep = (base["null_reply"] or 0) / bt
        base_emp = (base["empty_content"] or 0) / bt

        return {
            "app_version_null_rate": round(cur_ver, 4),
            "app_version_null_rate_baseline": round(base_ver, 4),
            "app_version_null_rate_shift_pct": round(
                (cur_ver - base_ver) * 100, 2
            ),
            "reply_content_null_rate": round(cur_rep, 4),
            "reply_content_null_rate_baseline": round(base_rep, 4),
            "reply_content_null_rate_shift_pct": round(
                (cur_rep - base_rep) * 100, 2
            ),
            "empty_content_rate": round(cur_emp, 4),
            "empty_content_rate_baseline": round(base_emp, 4),
            "avg_content_length": round(cur["avg_len"] or 0, 1),
            "avg_content_length_baseline": round(base["avg_len"] or 0, 1),
        }

    # -----------------------------------------------------------------
    # Anomaly detection
    # -----------------------------------------------------------------

    def _detect_anomalies(
        self,
        result: RunResult,
        metrics: Dict[str, Any],
        deltas: Dict[str, Any],
        data_quality: Dict[str, Any],
    ) -> List[Alert]:
        alerts: List[Alert] = []

        # 1. Error rate
        if metrics["error_rate"] > self.THRESHOLDS["error_rate_max"]:
            failed = [ar.app_id for ar in result.app_results if ar.error]
            alerts.append(Alert(
                level="WARNING",
                metric="error_rate",
                message=(
                    f"{metrics['apps_failed']} app(s) failed: "
                    + ", ".join(failed)
                ),
                threshold=self.THRESHOLDS["error_rate_max"],
                actual_value=metrics["error_rate"],
            ))

        # 2. Dedup rate ceiling
        if metrics["dedup_rate"] > self.THRESHOLDS["dedup_rate_ceiling"]:
            alerts.append(Alert(
                level="WARNING",
                metric="dedup_rate",
                message=(
                    f"Dedup rate {metrics['dedup_rate']*100:.1f}% exceeds "
                    f"{self.THRESHOLDS['dedup_rate_ceiling']*100:.1f}% "
                    "threshold - possible API staleness"
                ),
                threshold=self.THRESHOLDS["dedup_rate_ceiling"],
                actual_value=metrics["dedup_rate"],
            ))

        # 3. Inserted count drop vs recent average
        avg5 = deltas.get("vs_avg_last_5", {})
        if "reviews_inserted" in avg5:
            dev_pct = avg5["reviews_inserted"]["deviation_pct"]
            threshold = self.THRESHOLDS["reviews_inserted_drop_pct"]
            if dev_pct < -threshold:
                alerts.append(Alert(
                    level="WARNING",
                    metric="reviews_inserted",
                    message=(
                        f"Reviews inserted dropped {abs(dev_pct):.1f}% "
                        "vs recent average"
                    ),
                    threshold=-threshold,
                    actual_value=dev_pct,
                ))
            elif dev_pct > threshold:
                alerts.append(Alert(
                    level="INFO",
                    metric="reviews_inserted",
                    message=(
                        f"Reviews inserted increased {dev_pct:.1f}% "
                        "vs recent average"
                    ),
                    actual_value=dev_pct,
                ))

        # 4. Duration spike
        if "duration" in avg5 and avg5["duration"]["baseline"] > 0:
            baseline = avg5["duration"]["baseline"]
            mult = self.THRESHOLDS["duration_multiplier"]
            if metrics["duration_seconds"] > baseline * mult:
                alerts.append(Alert(
                    level="WARNING",
                    metric="duration",
                    message=(
                        f"Duration {metrics['duration_seconds']:.0f}s is "
                        f"{metrics['duration_seconds']/baseline:.1f}x "
                        "recent average"
                    ),
                    threshold=baseline * mult,
                    actual_value=metrics["duration_seconds"],
                ))

        # 5. Null rate shifts
        shift_threshold = self.THRESHOLDS["null_rate_shift_pct"]
        for field_name in ("app_version", "reply_content"):
            shift = data_quality[f"{field_name}_null_rate_shift_pct"]
            if abs(shift) > shift_threshold:
                direction = "increased" if shift > 0 else "decreased"
                alerts.append(Alert(
                    level="INFO",
                    metric=f"{field_name}_null_rate",
                    message=(
                        f"{field_name} null rate {direction} by "
                        f"{abs(shift):.1f} percentage points vs baseline"
                    ),
                    threshold=shift_threshold,
                    actual_value=abs(shift),
                ))

        # 6. Z-score outlier
        if "reviews_inserted" in avg5:
            z = avg5["reviews_inserted"].get("z_score")
            if z is not None and abs(z) > 2.0:
                alerts.append(Alert(
                    level="INFO",
                    metric="reviews_inserted_z_score",
                    message=(
                        f"Reviews inserted is {abs(z):.1f} standard "
                        "deviations from recent mean"
                    ),
                    threshold=2.0,
                    actual_value=abs(z),
                ))

        return alerts

    # -----------------------------------------------------------------
    # App health
    # -----------------------------------------------------------------

    def _build_app_health(
        self, app_results: List[AppRunResult]
    ) -> List[Dict[str, Any]]:
        health = []
        for ar in app_results:
            if ar.error:
                status = "error"
            elif ar.reviews_inserted == 0 and ar.reviews_fetched > 0:
                status = "stale"
            else:
                status = "ok"

            health.append({
                "app_id": ar.app_id,
                "app_title": ar.app_title,
                "status": status,
                "reviews_fetched": ar.reviews_fetched,
                "reviews_inserted": ar.reviews_inserted,
                "reviews_skipped": ar.reviews_skipped,
                "duration_seconds": round(ar.duration_seconds, 2),
                "error": ar.error,
            })
        return health

    # -----------------------------------------------------------------
    # Storage & retrieval
    # -----------------------------------------------------------------

    def store_report(self, report: HealthReport) -> None:
        """Persist health report to ingestion_metrics table."""
        conn = self.db.connect()
        m = report.metrics
        dq = report.data_quality

        try:
            conn.execute("""
                INSERT OR REPLACE INTO ingestion_metrics (
                    run_id, report_json,
                    reviews_inserted, reviews_fetched, reviews_skipped,
                    dedup_rate, error_rate, duration_seconds,
                    ingestion_rate_per_min, apps_processed, apps_failed,
                    app_version_null_rate, reply_content_null_rate,
                    empty_content_rate, alerts_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report.run_id,
                json.dumps(report.to_dict(), indent=2),
                m["reviews_inserted"],
                m["reviews_fetched"],
                m["reviews_skipped"],
                m["dedup_rate"],
                m["error_rate"],
                m["duration_seconds"],
                m["ingestion_rate_per_min"],
                m["apps_processed"],
                m["apps_failed"],
                dq["app_version_null_rate"],
                dq["reply_content_null_rate"],
                dq["empty_content_rate"],
                len(report.alerts),
            ))
            conn.commit()
            self.logger.info(
                f"Stored health report for run #{report.run_id}"
            )
        except Exception as e:
            self.logger.error(f"Failed to store health report: {e}")

    def get_recent_health_reports(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieve recent health reports from ingestion_metrics."""
        conn = self.db.connect()
        rows = conn.execute("""
            SELECT report_json
            FROM ingestion_metrics
            ORDER BY run_id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [json.loads(row["report_json"]) for row in rows]

    # -----------------------------------------------------------------
    # Console output
    # -----------------------------------------------------------------

    def print_alerts(self, report: HealthReport) -> None:
        """Print alerts to console and log."""
        if not report.alerts:
            self.logger.info(
                f"Run #{report.run_id}: No anomalies detected"
            )
            print(f"\n  Run #{report.run_id}: No anomalies detected.\n")
            return

        divider = "=" * 70
        lines = [
            "",
            divider,
            f"  HEALTH ALERTS - Run #{report.run_id}  "
            f"({len(report.alerts)} alert(s))",
            divider,
        ]
        for a in report.alerts:
            prefix = "[WARNING]" if a.level == "WARNING" else "[INFO   ]"
            lines.append(f"  {prefix} {a.message}")
        lines.extend([divider, ""])

        output = "\n".join(lines)
        print(output)
        self.logger.info(output)

    # -----------------------------------------------------------------
    # Backfill
    # -----------------------------------------------------------------

    def backfill_metrics(self) -> int:
        """
        Backfill monitoring metrics for historical runs that don't
        have an ingestion_metrics entry yet.

        Reconstructs RunResult from scrape_runs + review_scrape_log.
        Limitation: fetched/skipped counts unknown for historical runs.
        """
        conn = self.db.connect()

        runs = conn.execute("""
            SELECT sr.run_id, sr.started_at, sr.completed_at, sr.status,
                   sr.total_reviews_collected, sr.total_apps_processed,
                   sr.error_message,
                   CAST(
                       (julianday(sr.completed_at) - julianday(sr.started_at))
                       * 86400 AS REAL
                   ) AS duration_sec
            FROM scrape_runs sr
            LEFT JOIN ingestion_metrics im ON sr.run_id = im.run_id
            WHERE im.run_id IS NULL AND sr.completed_at IS NOT NULL
            ORDER BY sr.run_id
        """).fetchall()

        backfilled = 0
        for row in runs:
            try:
                result = self._reconstruct_run_result(row)
                report = self.evaluate_run(result)
                self.store_report(report)
                backfilled += 1
                self.logger.info(
                    f"  Backfilled run #{row['run_id']}"
                )
            except Exception as e:
                self.logger.error(
                    f"  Failed to backfill run #{row['run_id']}: {e}"
                )

        self.logger.info(f"Backfill complete: {backfilled} runs processed")
        return backfilled

    def _reconstruct_run_result(self, row) -> RunResult:
        """Rebuild a RunResult from historical DB data."""
        conn = self.db.connect()
        run_id = row["run_id"]

        # Per-app breakdown from review_scrape_log
        apps = conn.execute("""
            SELECT r.app_id, a.title, COUNT(*) AS cnt
            FROM review_scrape_log rsl
            JOIN reviews r ON rsl.review_id = r.review_id
            LEFT JOIN apps a ON r.app_id = a.app_id
            WHERE rsl.run_id = ?
            GROUP BY r.app_id
        """, (run_id,)).fetchall()

        app_results = []
        for a in apps:
            app_results.append(AppRunResult(
                app_id=a["app_id"],
                app_title=a["title"],
                reviews_fetched=a["cnt"],   # best guess
                reviews_inserted=a["cnt"],
                reviews_skipped=0,          # unknown
                duration_seconds=0,         # unknown
            ))

        # Parse error_message to find failed apps
        failed_apps = []
        if row["error_message"] and "apps failed:" in row["error_message"]:
            parts = row["error_message"].split("apps failed:")[1].strip()
            failed_apps = [x.strip() for x in parts.split(",")]
            for fid in failed_apps:
                app_results.append(AppRunResult(
                    app_id=fid,
                    reviews_fetched=0,
                    reviews_inserted=0,
                    reviews_skipped=0,
                    duration_seconds=0,
                    error="historical_failure",
                ))

        total_inserted = row["total_reviews_collected"] or 0

        return RunResult(
            run_id=run_id,
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"] else None
            ),
            status=row["status"],
            app_results=app_results,
            total_reviews_inserted=total_inserted,
            total_reviews_fetched=total_inserted,  # best guess
            total_reviews_skipped=0,
            total_apps_processed=row["total_apps_processed"] or 0,
            total_apps_failed=len(failed_apps),
            duration_seconds=row["duration_sec"] or 0,
            error_message=row["error_message"],
        )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _change(previous: float, current: float) -> Dict[str, Any]:
        pct = (current - previous) / previous * 100 if previous else 0
        return {
            "previous": round(previous, 2),
            "current": round(current, 2),
            "change": round(current - previous, 2),
            "change_pct": round(pct, 2),
        }

    @staticmethod
    def _deviation(
        baseline: float, current: float, std_dev: float
    ) -> Dict[str, Any]:
        dev = current - baseline
        pct = dev / baseline * 100 if baseline else 0
        z = dev / std_dev if std_dev > 0 else None
        return {
            "baseline": round(baseline, 2),
            "current": round(current, 2),
            "deviation": round(dev, 2),
            "deviation_pct": round(pct, 2),
            "z_score": round(z, 2) if z is not None else None,
        }
