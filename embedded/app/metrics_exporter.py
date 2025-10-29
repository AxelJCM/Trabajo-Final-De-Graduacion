"""
metrics_exporter: orchestrates data exports for Chapter 4 validation artifacts.

Generates:
- angulo_tiempo.csv (if a live sampling is requested) and posture_metrics.json
- fitbit_intraday.csv and biometrics_summary.json
- voice_accuracy.csv and voice_summary.json
- comparativo_desempeno.csv and performance_summary.json

This module exposes generate_all_exports(), which can be invoked on session stop.
It is designed to be safe and best-effort: failures in one export won't stop others.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable, Any

from loguru import logger

# Local imports of scripts (as modules) to reuse logic
# Note: these imports are runtime-local to avoid import overhead on server start


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _timestamp_dir(root: Path) -> Path:
    now = datetime.now()
    sub = now.strftime("%Y%m%d_%H%M%S")
    out = root / sub
    _ensure_dir(out)
    return out


def export_posture(base_url: str, out_dir: Path, *, duration_min: float = 0.0, posture_series: Optional[Iterable[Any]] = None) -> None:
    """Export posture metrics.

    If duration_min > 0, it will sample live /posture for that duration to produce angulo_tiempo.csv.
    Otherwise it will only export a posture_metrics.csv and posture_metrics.json with current summary.
    """
    try:
        # Always fetch summary first
        import requests
        base = base_url.rstrip("/")
        # Vision metrics: prefer posture_series values if provided, else /debug/metrics
        fps, p50, p95 = 0.0, 0.0, 0.0
        if posture_series:
            try:
                lats = []
                fps_vals = []
                for s in posture_series:
                    lat_v = getattr(s, "latency_ms", None) if hasattr(s, "latency_ms") else (s.get("latency_ms") if isinstance(s, dict) else None)
                    fps_v = getattr(s, "fps", None) if hasattr(s, "fps") else (s.get("fps") if isinstance(s, dict) else None)
                    if lat_v is not None:
                        lats.append(float(lat_v))
                    if fps_v is not None:
                        fps_vals.append(float(fps_v))
                if lats:
                    from statistics import median
                    p50 = median(lats)
                    p95 = sorted(lats)[int(0.95 * len(lats)) - 1] if len(lats) > 1 else p50
                if fps_vals:
                    fps = sum(fps_vals) / len(fps_vals)
            except Exception as exc:
                logger.warning("export_posture: fallo al calcular lat/fps desde series: {}", exc)
        if fps == 0.0 and p50 == 0.0 and p95 == 0.0:
            try:
                r = requests.get(f"{base}/debug/metrics", timeout=3)
                r.raise_for_status()
                d = r.json() or {}
                fps = float(((d.get("fps") or {}).get("avg")) or 0.0)
                lat = (d.get("latency_ms") or {})
                p50 = float(lat.get("p50") or 0.0)
                p95 = float(lat.get("p95") or 0.0)
            except Exception as exc:
                logger.warning("export_posture: no metrics: {}", exc)
        # /session/status
        quality_avg, rep_totals = 0.0, {}
        try:
            s = requests.get(f"{base}/session/status", timeout=3)
            s.raise_for_status()
            sd = (s.json() or {}).get("data") or {}
            # Prefer windowed session summary (set on stop) to avoid reading reset live totals
            summary = sd.get("session_summary") or {}
            if isinstance(summary, dict):
                rep_totals = summary.get("rep_breakdown") or {}
                qa = summary.get("avg_quality")
                if qa is not None:
                    quality_avg = float(qa)
            # Fallbacks if summary missing
            if not rep_totals:
                rep_totals = sd.get("rep_totals") or {}
            if quality_avg == 0.0:
                quality_avg = float(sd.get("avg_quality") or 0.0)
        except Exception as exc:
            logger.warning("export_posture: no session status: {}", exc)
        # Write CSV and JSON summary
        from csv import writer
        csv_path = out_dir / "posture_metrics.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = writer(f)
            w.writerow(["fps", "latency_ms_p50", "latency_ms_p95", "rep_totals", "quality_avg"])
            w.writerow([f"{fps:.2f}", f"{p50:.2f}", f"{p95:.2f}", json.dumps(rep_totals, ensure_ascii=False), f"{quality_avg:.2f}"])
        with (out_dir / "posture_metrics.json").open("w", encoding="utf-8") as f:
            json.dump({"fps": fps, "latency_ms_p50": p50, "latency_ms_p95": p95, "rep_totals": rep_totals, "quality_avg": quality_avg}, f, ensure_ascii=False, indent=2)
        # If series provided (session window), write angulo_tiempo.csv
        if posture_series:
            try:
                from csv import writer as _writer
                ang_csv = out_dir / "angulo_tiempo.csv"
                with ang_csv.open("w", newline="", encoding="utf-8") as f:
                    w = _writer(f)
                    w.writerow(["t", "angulo", "is_rep"])
                    for s in posture_series:
                        # s can be dataclass PostureSample or dict
                        t = getattr(s, "t", None) if hasattr(s, "t") else s.get("t")
                        a = getattr(s, "angle", None) if hasattr(s, "angle") else s.get("angle")
                        rep = getattr(s, "is_rep", 0) if hasattr(s, "is_rep") else int(s.get("is_rep", 0))
                        if t is None:
                            continue
                        w.writerow([f"{float(t):.3f}", ("" if a is None else f"{float(a):.3f}"), int(rep)])
            except Exception as exc:
                logger.warning("No se pudo escribir angulo_tiempo.csv: {}", exc)
    except Exception as exc:
        logger.warning("export_posture fallo: {}", exc)


def export_biometrics(db_path: Path, out_dir: Path, *, window_start_utc: Optional[datetime] = None, window_end_utc: Optional[datetime] = None) -> None:
    """Inline export to avoid cross-package imports in production."""
    try:
        import sqlite3
        from collections import defaultdict
        from statistics import median
        import csv as _csv

        # Load samples
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            if window_start_utc and window_end_utc:
                cur.execute(
                    "SELECT timestamp_utc, heart_rate_bpm, COALESCE(zone_label,'') FROM biometric_sample WHERE timestamp_utc BETWEEN ? AND ? ORDER BY timestamp_utc ASC",
                    (window_start_utc.replace(tzinfo=None), window_end_utc.replace(tzinfo=None)),
                )
            else:
                cur.execute(
                    "SELECT timestamp_utc, heart_rate_bpm, COALESCE(zone_label,'') FROM biometric_sample ORDER BY timestamp_utc ASC"
                )
            samples = []
            from datetime import datetime as _dt
            for ts, hr, zl in cur.fetchall():
                try:
                    if isinstance(ts, str):
                        dt = _dt.fromisoformat(ts)
                    else:
                        dt = _dt.utcfromtimestamp(float(ts))
                    samples.append((dt, int(hr or 0), str(zl or "")))
                except Exception:
                    continue
        finally:
            conn.close()

        # Export intraday minute buckets
        buckets = {}
        for dt, hr, zl in samples:
            minute = dt.replace(second=0, microsecond=0)
            buckets[minute] = (hr, zl)
        with (out_dir / "fitbit_intraday.csv").open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["t_min", "hr", "zone_label"])
            for k in sorted(buckets.keys()):
                hr, zl = buckets[k]
                w.writerow([k.isoformat(), hr, zl])

        # Metrics
        if len(samples) < 2:
            metrics = {"freshness_s": 0.0, "coverage_intraday_pct": 0.0, "avg_update_latency_s": 0.0}
        else:
            # Gaps seconds
            gaps = []
            for i in range(1, len(samples)):
                gaps.append((samples[i][0] - samples[i - 1][0]).total_seconds())
            avg_latency = sum(gaps) / len(gaps)
            freshness = float(median(gaps))
            # Intraday coverage
            from datetime import datetime as _ldt
            now = _ldt.now()
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            minutes_total = max(1, int((now - day_start).total_seconds() // 60))
            minute_marks = set()
            for dt, _, _ in samples:
                if dt >= day_start:
                    minute_marks.add(dt.replace(second=0, microsecond=0))
            coverage = 100.0 * len(minute_marks) / float(minutes_total)
            metrics = {
                "freshness_s": round(freshness, 3),
                "coverage_intraday_pct": round(coverage, 2),
                "avg_update_latency_s": round(avg_latency, 3),
            }

        with (out_dir / "biometrics_summary.json").open("w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("export_biometrics fallo: {}", exc)


def export_voice(log_path: Path, out_dir: Path, *, window_start_utc: Optional[datetime] = None, window_end_utc: Optional[datetime] = None, voice_recognized: Optional[list] = None, voice_executed: Optional[list] = None) -> None:
    try:
        import re
        import csv as _csv
        from statistics import median
        from datetime import datetime as _dt

        TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3,6})?)")
        REC_RE = re.compile(r"Intent '([a-z]+)' reconocido(?: \(texto='.*'\))?")
        EXEC_RE = re.compile(r"Intent '([a-z]+)' ejecutado")

        def parse_time_prefix(line: str):
            m = TIME_RE.match(line)
            if not m:
                return None
            ts = m.group(1)
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    return _dt.strptime(ts, fmt)
                except Exception:
                    continue
            return None

        recognized = {}
        executed = {}
        last_rec = {}
        latencies = {}

        if voice_recognized is not None and voice_executed is not None:
            # Compute accuracy/latency from session-scoped arrays
            def parse_iso(t: str) -> _dt:
                try:
                    return _dt.fromisoformat(t)
                except Exception:
                    return _dt.min
            # Build queues
            rec_map = {}
            for ev in voice_recognized:
                it = str(ev.get("intent") or "")
                tt = parse_iso(str(ev.get("timestamp") or ""))
                if window_start_utc and tt < window_start_utc:
                    continue
                if window_end_utc and tt > window_end_utc:
                    continue
                recognized[it] = recognized.get(it, 0) + 1
                rec_map.setdefault(it, []).append(tt)
            for ev in voice_executed:
                it = str(ev.get("intent") or "")
                tt = parse_iso(str(ev.get("timestamp") or ""))
                if window_start_utc and tt < window_start_utc:
                    continue
                if window_end_utc and tt > window_end_utc:
                    continue
                executed[it] = executed.get(it, 0) + 1
                if rec_map.get(it):
                    tr = rec_map[it].pop(0)
                    if tt and tr and tr != _dt.min:
                        latencies.setdefault(it, []).append((tt - tr).total_seconds() * 1000.0)
        else:
            # Fallback: parse logs and filter by window. Try both app.log and voice.log
            logs_to_parse = [log_path]
            try:
                alt = log_path.parent / "voice.log"
                if alt.exists():
                    logs_to_parse.append(alt)
            except Exception:
                pass

            def _parse_file(p: Path) -> None:
                try:
                    with p.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            t = parse_time_prefix(line)
                            if window_start_utc and t and t < window_start_utc:
                                continue
                            if window_end_utc and t and t > window_end_utc:
                                continue
                            m = REC_RE.search(line)
                            if m:
                                it = m.group(1)
                                recognized[it] = recognized.get(it, 0) + 1
                                last_rec.setdefault(it, []).append(t or _dt.min)
                                continue
                            m = EXEC_RE.search(line)
                            if m:
                                it = m.group(1)
                                executed[it] = executed.get(it, 0) + 1
                                if last_rec.get(it):
                                    tr = last_rec[it].pop(0)
                                    if t and tr and tr != _dt.min:
                                        lat = (t - tr).total_seconds() * 1000.0
                                        latencies.setdefault(it, []).append(lat)
                            # Support external listener prints: Text lines -> map to intents
                            if "Text:" in line and "[VOICE]" in line:
                                try:
                                    import re as __re
                                    mm = __re.search(r"Text:\s*'([^']+)'", line)
                                    if mm:
                                        txt = mm.group(1)
                                        try:
                                            from app.voice.recognizer import map_utterance_to_intent as __map
                                            it2 = __map(txt) or None
                                        except Exception:
                                            it2 = None
                                        if it2:
                                            recognized[it2] = recognized.get(it2, 0) + 1
                                            last_rec.setdefault(it2, []).append(t or _dt.min)
                                except Exception:
                                    pass
                except Exception:
                    pass

            for p in logs_to_parse:
                _parse_file(p)

        intents = sorted(set(list(recognized.keys()) + list(executed.keys())))
        acc = {}
        meds = {}
        for it in intents:
            r = recognized.get(it, 0)
            e = executed.get(it, 0)
            acc[it] = 100.0 * (e / r) if r else 0.0
            lats = latencies.get(it, [])
            meds[it] = median(lats) if lats else 0.0

        # Write CSV
        with (out_dir / "voice_accuracy.csv").open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["intent", "accuracy_pct", "latency_ms"])
            for it in intents:
                w.writerow([it, f"{acc.get(it, 0.0):.2f}", f"{meds.get(it, 0.0):.0f}"])

        summary = {"per_intent": {it: {"accuracy_pct": round(acc.get(it, 0.0), 2), "latency_ms": round(meds.get(it, 0.0), 0)} for it in intents}}
        with (out_dir / "voice_summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("export_voice fallo: {}", exc)


def export_performance(base_url: str, db_path: Path, log_path: Path, out_dir: Path, *, window_start_utc: Optional[datetime] = None, window_end_utc: Optional[datetime] = None, posture_series: Optional[Iterable[Any]] = None, voice_recognized: Optional[list] = None, voice_executed: Optional[list] = None) -> None:
    try:
        import requests
        import sqlite3
        from statistics import median
        import re
        from datetime import datetime as _dt
        from csv import writer as _writer

        # Vision (/debug/metrics)
        v_fps, v_p50, v_p95 = 0.0, 0.0, 0.0
        # If posture_series present, compute vision latency and fps from it
        if posture_series:
            lats = []
            fps_vals = []
            for s in posture_series:
                lat_v = getattr(s, "latency_ms", None) if hasattr(s, "latency_ms") else s.get("latency_ms")
                fps_v = getattr(s, "fps", None) if hasattr(s, "fps") else s.get("fps")
                if lat_v is not None:
                    lats.append(float(lat_v))
                if fps_v is not None:
                    fps_vals.append(float(fps_v))
            v_p50 = median(lats) if lats else 0.0
            v_p95 = sorted(lats)[int(0.95 * len(lats)) - 1] if lats else 0.0
            v_fps = (sum(fps_vals) / len(fps_vals)) if fps_vals else 0.0
        else:
            try:
                r = requests.get(f"{base_url.rstrip('/')}/debug/metrics", timeout=3)
                r.raise_for_status()
                d = r.json() or {}
                v_fps = float(((d.get("fps") or {}).get("avg")) or 0.0)
                lat = (d.get("latency_ms") or {})
                v_p50 = float(lat.get("p50") or 0.0)
                v_p95 = float(lat.get("p95") or 0.0)
            except Exception:
                pass

        # Biometrics (gaps from SQLite)
        conn = sqlite3.connect(str(db_path))
        ts = []
        try:
            cur = conn.cursor()
            if window_start_utc and window_end_utc:
                cur.execute("SELECT timestamp_utc FROM biometric_sample WHERE timestamp_utc BETWEEN ? AND ? ORDER BY timestamp_utc ASC",
                            (window_start_utc.replace(tzinfo=None), window_end_utc.replace(tzinfo=None)))
            else:
                cur.execute("SELECT timestamp_utc FROM biometric_sample ORDER BY timestamp_utc ASC")
            for (t,) in cur.fetchall():
                try:
                    if isinstance(t, str):
                        ts.append(_dt.fromisoformat(t))
                    else:
                        ts.append(_dt.utcfromtimestamp(float(t)))
                except Exception:
                    continue
        finally:
            conn.close()
        b_gaps = []
        for i in range(1, len(ts)):
            b_gaps.append((ts[i] - ts[i - 1]).total_seconds() * 1000.0)
        b_p50 = median(b_gaps) if b_gaps else 0.0
        b_p95 = sorted(b_gaps)[int(0.95 * len(b_gaps)) - 1] if b_gaps else 0.0
        b_fps = (1000.0 / (sum(b_gaps) / len(b_gaps))) if b_gaps else 0.0

        # Voice latencies: prefer session arrays if provided; else fallback to log parsing
        lats = []
        if voice_recognized is not None and voice_executed is not None:
            from datetime import datetime as __dt
            def _parse_iso(ts: str) -> __dt:
                try:
                    return __dt.fromisoformat(ts)
                except Exception:
                    return __dt.min
            rec_map: dict[str, list[__dt]] = {}
            for ev in voice_recognized:
                it = str(ev.get("intent") or "")
                tt = _parse_iso(str(ev.get("timestamp") or ""))
                if window_start_utc and tt < window_start_utc:
                    continue
                if window_end_utc and tt > window_end_utc:
                    continue
                rec_map.setdefault(it, []).append(tt)
            for ev in voice_executed:
                it = str(ev.get("intent") or "")
                tt = _parse_iso(str(ev.get("timestamp") or ""))
                if window_start_utc and tt < window_start_utc:
                    continue
                if window_end_utc and tt > window_end_utc:
                    continue
                if rec_map.get(it):
                    tr = rec_map[it].pop(0)
                    if tt and tr and tr != __dt.min:
                        lats.append((tt - tr).total_seconds() * 1000.0)
        else:
            TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3,6})?)")
            REC_RE = re.compile(r"Intent '([a-z]+)' reconocido(?: \(texto='.*'\))?")
            EXEC_RE = re.compile(r"Intent '([a-z]+)' ejecutado")
            def parse_time_prefix(line: str):
                m = TIME_RE.match(line)
                if not m:
                    return None
                ts = m.group(1)
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return _dt.strptime(ts, fmt)
                    except Exception:
                        continue
                return None
            last_rec = {}
            def _parse_file(p: Path) -> None:
                try:
                    with p.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            t = parse_time_prefix(line)
                            m = REC_RE.search(line)
                            if m:
                                it = m.group(1)
                                last_rec.setdefault(it, []).append(t or _dt.min)
                                continue
                            m = EXEC_RE.search(line)
                            if m:
                                it = m.group(1)
                                if last_rec.get(it):
                                    tr = last_rec[it].pop(0)
                                    if t and tr and tr != _dt.min:
                                        lats.append((t - tr).total_seconds() * 1000.0)
                            # Support external listener prints
                            if "Text:" in line and "[VOICE]" in line:
                                try:
                                    import re as __re
                                    mm = __re.search(r"Text:\s*'([^']+)'", line)
                                    if mm:
                                        txt = mm.group(1)
                                        try:
                                            from app.voice.recognizer import map_utterance_to_intent as __map
                                            it2 = __map(txt) or None
                                        except Exception:
                                            it2 = None
                                        if it2:
                                            last_rec.setdefault(it2, []).append(t or _dt.min)
                                except Exception:
                                    pass
                except Exception:
                    pass
            # Parse both app.log and voice.log if present
            logs_to_parse = [log_path]
            try:
                alt = log_path.parent / "voice.log"
                if alt.exists():
                    logs_to_parse.append(alt)
            except Exception:
                pass
            for p in logs_to_parse:
                _parse_file(p)
        voice_p50 = median(lats) if lats else 0.0
        voice_p95 = sorted(lats)[int(0.95 * len(lats)) - 1] if lats else 0.0

        hud_fps = v_fps

        with (out_dir / "comparativo_desempeno.csv").open("w", newline="", encoding="utf-8") as f:
            w = _writer(f)
            w.writerow(["modulo", "fps", "lat_p50", "lat_p95"])
            w.writerow(["Vision", f"{v_fps:.2f}", f"{v_p50:.0f}", f"{v_p95:.0f}"])
            w.writerow(["Biometrics", f"{b_fps:.3f}", f"{b_p50:.0f}", f"{b_p95:.0f}"])
            w.writerow(["Voice", "", f"{voice_p50:.0f}", f"{voice_p95:.0f}"])
            w.writerow(["HUD", f"{hud_fps:.2f}", "", ""])

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
    except Exception as exc:
        logger.warning("export_performance fallo: {}", exc)


def generate_all_exports(*, base_url: str = "http://127.0.0.1:8000", db_path: Optional[Path] = None, log_path: Optional[Path] = None, out_root: Optional[Path] = None, sample_posture_minutes: float = 0.0, window_start_utc: Optional[datetime] = None, window_end_utc: Optional[datetime] = None, posture_series: Optional[Iterable[Any]] = None, voice_recognized: Optional[list] = None, voice_executed: Optional[list] = None) -> Path:
    """Generate all artifacts and return the output directory path.

    sample_posture_minutes > 0 will attempt to live-sample /posture for that duration.
    """
    from app.core.db import DB_PATH
    db = db_path or DB_PATH
    logs = log_path or (Path(__file__).resolve().parent / "data" / "logs" / "app.log")
    out_root = out_root or (Path(__file__).resolve().parent / "data" / "exports")
    _ensure_dir(out_root)
    out_dir = _timestamp_dir(out_root)

    logger.info("Exportando métricas a {}", out_dir)
    export_posture(base_url, out_dir, duration_min=sample_posture_minutes, posture_series=posture_series)
    export_biometrics(db, out_dir, window_start_utc=window_start_utc, window_end_utc=window_end_utc)
    export_voice(logs, out_dir, window_start_utc=window_start_utc, window_end_utc=window_end_utc, voice_recognized=voice_recognized, voice_executed=voice_executed)
    export_performance(base_url, db, logs, out_dir, window_start_utc=window_start_utc, window_end_utc=window_end_utc, posture_series=posture_series, voice_recognized=voice_recognized, voice_executed=voice_executed)

    logger.info("Exportación completada: {}", out_dir)
    return out_dir


def generate_all_exports_async(**kwargs) -> None:
    def _run():
        try:
            generate_all_exports(**kwargs)
        except Exception as exc:
            logger.warning("metrics_exporter async fallo: {}", exc)
    t = threading.Thread(target=_run, name="MetricsExporter", daemon=True)
    t.start()
