#!/usr/bin/env python3
"""Train a simple text classifier for voice intents using collected samples."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

from loguru import logger

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    import joblib
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "scikit-learn y joblib son necesarios para entrenar. instala con 'pip install scikit-learn joblib'"
    ) from exc


DEFAULT_DATA_DIR = Path("embedded/app/data/training/voice")
DEFAULT_MODEL_PATH = Path("embedded/app/data/models/voice_intent.joblib")


def load_samples(data_dir: Path) -> Tuple[List[str], List[str]]:
    transcripts: List[str] = []
    intents: List[str] = []
    if not data_dir.exists():
        raise SystemExit(f"No se encuentra el directorio de datos {data_dir}")
    files = sorted(data_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No hay samples en {data_dir}. Usa record_and_register_voice.py primero.")
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("No se pudo leer {}: {}", file, exc)
            continue
        transcript = (payload.get("transcript") or "").strip()
        intent = payload.get("intent")
        if not transcript or not intent:
            logger.warning("Sample {} carece de transcript o intent", file)
            continue
        transcripts.append(transcript)
        intents.append(intent)
    if not transcripts:
        raise SystemExit("No se cargaron muestras validas.")
    logger.info("Cargadas {} muestras de {}", len(transcripts), data_dir)
    return transcripts, intents


def train_model(transcripts: List[str], intents: List[str], *, test_size: float = 0.2, random_state: int = 42) -> Dict[str, object]:
    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
    X = vectorizer.fit_transform(transcripts)
    model = LogisticRegression(max_iter=1000, multi_class="auto")
    if len(set(intents)) < 2:
        logger.warning("Solo hay un intent en el dataset; entrenando sin conjunto de prueba.")
        model.fit(X, intents)
        report = None
    else:
        X_train, X_test, y_train, y_test = train_test_split(X, intents, test_size=test_size, random_state=random_state, stratify=intents)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        report = classification_report(y_test, y_pred)
        logger.info("Reporte de clasificacion:\n{}", report)
    return {"vectorizer": vectorizer, "model": model}


def save_model_artifacts(artifacts: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifacts, path)
    logger.info("Modelo guardado en {}", path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrenar clasificador de intents de voz")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path, help="Directorio con JSON de voz (default: %(default)s)")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH, type=Path, help="Ruta donde guardar el modelo (default: %(default)s)")
    parser.add_argument("--test-size", default=0.2, type=float, help="Proporcion de datos para prueba (default: %(default)s)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transcripts, intents = load_samples(args.data_dir)
    artifacts = train_model(transcripts, intents, test_size=args.test_size)
    save_model_artifacts(artifacts, args.output)
    logger.info("Entrenamiento completado.")


if __name__ == "__main__":
    main()
