#!/data/data/com.termux/files/usr/bin/bash
set -e
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
