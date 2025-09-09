"""GUI module for the mirror display.

In production, render camera feed, pose overlays, and feedback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

try:
    from PyQt5 import QtWidgets
except Exception:  # pragma: no cover
    QtWidgets = None  # type: ignore


class MirrorApp:
    """Minimal Qt app stub with CLI fallback."""

    def run(self) -> None:  # pragma: no cover - GUI
        if QtWidgets is None:
            print("PyQt5 not available. Run CLI: python -m app.gui.mirror_gui --cli")
            return
        app = QtWidgets.QApplication([])
        w = QtWidgets.QLabel("Espejo Interactivo - Listo")
        w.resize(640, 480)
        w.show()
        app.exec_()


async def cli_loop(base_url: str) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=3) as client:
        while True:
            try:
                b = await client.post(f"{base_url}/biometrics", json={})
                p = await client.post(f"{base_url}/posture", json={})
                hr = b.json().get("data", {}).get("heart_rate_bpm")
                feedback = p.json().get("data", {}).get("feedback")
                print(f"HR={hr} | Posture={feedback}")
            except Exception as exc:
                print(f"CLI error: {exc}")
            await asyncio.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run CLI fallback mode")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    args = parser.parse_args()
    if args.cli:
        asyncio.run(cli_loop(args.base_url))
    else:
        MirrorApp().run()


if __name__ == "__main__":
    main()
