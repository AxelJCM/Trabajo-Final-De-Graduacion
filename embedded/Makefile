venv:
	python -m venv .venv && .\.venv\Scripts\python.exe -m pip install -r requirements.txt

dev:
	.\.venv\Scripts\python.exe -m pip install -e .
	.\.venv\Scripts\uvicorn app.api.main:app --host 0.0.0.0 --port 8000

test:
	.\.venv\Scripts\pytest -q embedded/tests