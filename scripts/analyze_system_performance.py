#!/usr/bin/env python3
"""
Aggregate system performance for Table 4.4 and Figure 4.9.

- Vision: from /debug/metrics (fps avg, p50/p95 latency)
- Biometrics: from SQLite biometric_sample (p50/p95 of inter-sample gaps in ms; fps ~ 1/avg_gap)
- Voice: from app.log latencies (median/p95 in ms); fps N/A
- HUD: fps assumed equal to Vision fps; latency N/A (no direct metric)

Exports:
  - comparativo_desempeno.csv: modulo, fps, lat_p50, lat_p95
  - performance_summary.json: p50_total, p95_total, fps_total (averaged over available modules)

Usage:
  python scripts/analyze_system_performance.py --base-url http://127.0.0.1:8000 --db embedded/app/data/smartmirror.db --log embedded/app/data/logs/app.log --out embedded/app/data/exports
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Tuple

import requests

# Reuse analyzer from voice script for latencies
import re
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3,6})?)")
REC_RE = re.compile(r"Intent '([a-z]+)' reconocido(?: \(texto='.*'\))?")
EXEC_RE = re.compile(r"Intent '([a-z]+)' ejecutado")


def parse_time_prefix(line: str) -> datetime | None:
    m = TIME_RE.match(line)
    if not m:
        return None
    ts = m.group(1)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            continue
    return None


def voice_latencies_ms(log_path: Path) -> List[float]:
    lats: List[float] = []
    last_rec: Dict[str, List[datetime]] = {}
    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            t = parse_time_prefix(line)
            m = REC_RE.search(line)
            if m:
                it = m.group(1)
                last_rec.setdefault(it, []).append(t or datetime.min)
                continue
            m = EXEC_RE.search(line)
            if m:
                it = m.group(1)
                if last_rec.get(it):
                    tr = last_rec[it].pop(0)
                    if t and tr and tr != datetime.min:
                        lats.append((t - tr).total_seconds() * 1000.0)
    return lats


def debug_metrics(base_url: str) -> Tuple[float, float, float]:
    r = requests.get(f"{base_url}/debug/metrics", timeout=3)
    r.raise_for_status()
    d = r.json() or {}
    fps = float(((d.get("fps") or {}).get("avg")) or 0.0)
    lat = (d.get("latency_ms") or {})
    p50 = float(lat.get("p50") or 0.0)
    p95 = float(lat.get("p95") or 0.0)
    return fps, p50, p95


def biometrics_gaps_ms(db_path: Path) -> List[float]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT timestamp_utc FROM biometric_sample ORDER BY timestamp_utc ASC")
        ts: List[datetime] = []
        for (t,) in cur.fetchall():
            try:
                if isinstance(t, str):
                    ts.append(datetime.fromisoformat(t))
                else:
                    ts.append(datetime.utcfromtimestamp(float(t)))
            except Exception:
                continue
        gaps: List[float] = []
        for i in range(1, len(ts)):
            gaps.append((ts[i] - ts[i-1]).total_seconds() * 1000.0)
        return gaps
    finally:
        conn.close()


def write_csv(path: Path, header: List[str], rows: List[List[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--db", default="embedded/app/data/smartmirror.db")
    ap.add_argument("--log", default="embedded/app/data/logs/app.log")
    ap.add_argument("--out", default="embedded/app/data/exports")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Vision
    try:
        v_fps, v_p50, v_p95 = debug_metrics(args.base_url.rstrip("/"))
    except Exception:
        v_fps, v_p50, v_p95 = 0.0, 0.0, 0.0

    # Biometrics
    b_gaps = biometrics_gaps_ms(Path(args.db))
    b_p50 = median(b_gaps) if b_gaps else 0.0
    b_p95 = sorted(b_gaps)[int(0.95 * len(b_gaps)) - 1] if b_gaps else 0.0
    b_fps = (1000.0 / (sum(b_gaps) / len(b_gaps))) if b_gaps else 0.0

    # Voice
    v_lats = voice_latencies_ms(Path(args.log))
    voice_p50 = median(v_lats) if v_lats else 0.0
    voice_p95 = sorted(v_lats)[int(0.95 * len(v_lats)) - 1] if v_lats else 0.0

    # HUD (no direct metric): assume fps ~ Vision, no latency
    hud_fps = v_fps

    rows = [
        ["Vision", f"{v_fps:.2f}", f"{v_p50:.0f}", f"{v_p95:.0f}"],
        ["Biometrics", f"{b_fps:.3f}", f"{b_p50:.0f}", f"{b_p95:.0f}"],
        ["Voice", "", f"{voice_p50:.0f}", f"{voice_p95:.0f}"],
        ["HUD", f"{hud_fps:.2f}", "", ""],
    ]
    out_csv = out_dir / "comparativo_desempeno.csv"
    write_csv(out_csv, ["modulo", "fps", "lat_p50", "lat_p95"], rows)

    # Summary across available numbers
    p50_vals = [v for v in (v_p50, b_p50, voice_p50) if v]
    p95_vals = [v for v in (v_p95, b_p95, voice_p95) if v]
    fps_vals = [v for v in (v_fps, b_fps, hud_fps) if v]
    summary = {
        "p50_total": round(sum(p50_vals) / len(p50_vals), 2) if p50_vals else 0.0,
        "p95_total": round(sum(p95_vals) / len(p95_vals), 2) if p95_vals else 0.0,
        "fps_total": round(sum(fps_vals) / len(fps_vals), 2) if fps_vals else 0.0,
    }
    with (out_dir / "performance_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print({"csv": str(out_csv), **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
