#!/usr/bin/env python3
"""
Analyze voice control accuracy for Table 4.3 and Figure 4.8.

Parses Loguru app log (embedded/app/data/logs/app.log) and computes for each intent (start, pause, stop, next):
- accuracy_pct = intents_correctos / intents_totales
- latency_ms (median) between "Intent 'X' reconocido" and "Intent 'X' ejecutado"

Exports voice_accuracy.csv with columns: intent, accuracy_pct, latency_ms

Usage:
  python scripts/analyze_voice_accuracy.py --log embedded/app/data/logs/app.log --out embedded/app/data/exports
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

# Patterns for Loguru default format (best-effort)
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3,6})?)")
REC_RE = re.compile(r"Intent '([a-z]+)' reconocido(?: \(texto='.*'\))?")
EXEC_RE = re.compile(r"Intent '([a-z]+)' ejecutado")


def parse_time_prefix(line: str) -> datetime | None:
    m = TIME_RE.match(line)
    if not m:
        return None
    ts = m.group(1)
    # Try multiple precisions
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            continue
    return None


def analyze(log_path: Path) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (accuracy_pct_by_intent, median_latency_ms_by_intent)."""
    # For accuracy: count recognized vs executed
    recognized: Dict[str, int] = {}
    executed: Dict[str, int] = {}
    # For latency: map last recognized time per intent to next executed time for same intent
    last_rec: Dict[str, List[datetime]] = {}
    latencies: Dict[str, List[float]] = {}

    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            t = parse_time_prefix(line)
            # Recognized
            m = REC_RE.search(line)
            if m:
                intent = m.group(1)
                recognized[intent] = recognized.get(intent, 0) + 1
                last_rec.setdefault(intent, []).append(t or datetime.min)
                continue
            # Executed
            m = EXEC_RE.search(line)
            if m:
                intent = m.group(1)
                executed[intent] = executed.get(intent, 0) + 1
                # Pair with earliest unmatched recognized
                if last_rec.get(intent):
                    tr = last_rec[intent].pop(0)
                    if t and tr and tr != datetime.min:
                        lat_ms = (t - tr).total_seconds() * 1000.0
                        latencies.setdefault(intent, []).append(lat_ms)
                continue

    intents = sorted(set(list(recognized.keys()) + list(executed.keys())))
    acc: Dict[str, float] = {}
    meds: Dict[str, float] = {}
    for it in intents:
        r = recognized.get(it, 0)
        e = executed.get(it, 0)
        acc[it] = 100.0 * (e / r) if r else 0.0
        lats = latencies.get(it, [])
        meds[it] = median(lats) if lats else 0.0
    return acc, meds


def write_csv(path: Path, acc: Dict[str, float], meds: Dict[str, float]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["intent", "accuracy_pct", "latency_ms"])
        for it in sorted(set(list(acc.keys()) + list(meds.keys()))):
            w.writerow([it, f"{acc.get(it, 0.0):.2f}", f"{meds.get(it, 0.0):.0f}"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="embedded/app/data/logs/app.log")
    ap.add_argument("--out", default="embedded/app/data/exports")
    args = ap.parse_args()

    log_path = Path(args.log)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    acc, meds = analyze(log_path)
    out_csv = out_dir / "voice_accuracy.csv"
    write_csv(out_csv, acc, meds)

    # Summary JSON
    import json
    summary = {
        "per_intent": {it: {"accuracy_pct": round(acc.get(it, 0.0), 2), "latency_ms": round(meds.get(it, 0.0), 0)} for it in sorted(set(list(acc.keys()) + list(meds.keys())))}
    }
    with (out_dir / "voice_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print({"csv": str(out_csv), **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
