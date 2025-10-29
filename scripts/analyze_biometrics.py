#!/usr/bin/env python3
"""
Analyze biometrics (Fitbit) for Table 4.2 and Figure 4.7.

- Reads SQLite table biometric_sample from embedded/app/data/smartmirror.db
- Computes:
  * freshness_s (average staleness for last sample windows; here defined as p50 of inter-sample gaps)
  * intraday coverage (% of minutes in local day having at least one HR)
  * average update latency (mean seconds between consecutive samples)
- Exports fitbit_intraday.csv with columns: t_min (ISO minute), hr, zone_label (last sample in minute)

Usage:
  python scripts/analyze_biometrics.py --db embedded/app/data/smartmirror.db --out embedded/app/data/exports
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Tuple


def load_samples(db_path: Path) -> List[Tuple[datetime, int, str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT timestamp_utc, heart_rate_bpm, COALESCE(zone_label,'') FROM biometric_sample ORDER BY timestamp_utc ASC")
        rows = []
        for ts, hr, zl in cur.fetchall():
            try:
                # stored as naive UTC
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts)
                else:
                    # assume unix epoch seconds
                    dt = datetime.utcfromtimestamp(float(ts))
                rows.append((dt, int(hr or 0), str(zl or "")))
            except Exception:
                continue
        return rows
    finally:
        conn.close()


def export_intraday(samples: List[Tuple[datetime, int, str]], out_csv: Path) -> None:
    # Bucket by minute (UTC) and take last known value in each minute
    buckets: Dict[datetime, Tuple[int, str]] = {}
    for dt, hr, zl in samples:
        minute = dt.replace(second=0, microsecond=0)
        buckets[minute] = (hr, zl)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_min", "hr", "zone_label"])
        for k in sorted(buckets.keys()):
            hr, zl = buckets[k]
            w.writerow([k.isoformat(), hr, zl])


def compute_metrics(samples: List[Tuple[datetime, int, str]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if len(samples) < 2:
        out.update({"freshness_s": 0.0, "coverage_intraday_pct": 0.0, "avg_update_latency_s": 0.0})
        return out
    # Inter-sample gaps (seconds)
    gaps = []
    for i in range(1, len(samples)):
        gaps.append((samples[i][0] - samples[i-1][0]).total_seconds())
    avg_latency = sum(gaps) / len(gaps)
    # Define freshness as p50 of inter-sample gaps (typical age of last data)
    freshness = float(median(gaps))
    # Intraday coverage: minutes since 00:00 local time that have at least one sample
    now = datetime.now()  # local assumed
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_total = max(1, int((now - day_start).total_seconds() // 60))
    minute_marks = set()
    for dt, _, _ in samples:
        if dt >= day_start:
            minute_marks.add(dt.replace(second=0, microsecond=0))
    coverage = 100.0 * len(minute_marks) / float(minutes_total)
    out.update({
        "freshness_s": round(freshness, 3),
        "coverage_intraday_pct": round(coverage, 2),
        "avg_update_latency_s": round(avg_latency, 3),
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="embedded/app/data/smartmirror.db")
    ap.add_argument("--out", default="embedded/app/data/exports")
    args = ap.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = load_samples(db_path)
    out_csv = out_dir / "fitbit_intraday.csv"
    export_intraday(samples, out_csv)
    metrics = compute_metrics(samples)

    # Write summary JSON alongside CSV
    summary_path = out_dir / "biometrics_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        import json
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print({"csv": str(out_csv), **metrics})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
