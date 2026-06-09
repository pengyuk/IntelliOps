$env:SKIP_DB_INIT = "1"
$env:SKIP_DATA_LOAD = "1"
python -m uvicorn src.backend.app:app --host 127.0.0.1 --port 8000
