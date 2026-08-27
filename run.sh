#!/usr/bin/env bash
# run.sh — start the whole combined project with one command:
#   backend/app.py (FastAPI, port 8000) + streamlit_app.py (port 8501)
#
# Usage:
#   ./run.sh                 # start both, Ctrl+C stops both
#   PSX_ADMIN_TOKEN=... ./run.sh    # enables /scan, /refresh-news, /backfill-* from non-localhost
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BACKEND_PORT="${BACKEND_PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

echo "[run.sh] starting backend on :$BACKEND_PORT ..."
(cd backend && python3 -m uvicorn app:app --host 127.0.0.1 --port "$BACKEND_PORT") &
BACKEND_PID=$!

cleanup() {
    echo
    echo "[run.sh] stopping backend (pid $BACKEND_PID) ..."
    kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[run.sh] waiting for backend health check ..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
        echo "[run.sh] backend is up."
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[run.sh] backend process died — check backend/requirements.txt is installed." >&2
        exit 1
    fi
    sleep 1
done

export PSX_BACKEND="http://127.0.0.1:${BACKEND_PORT}"
echo "[run.sh] starting Streamlit on :$STREAMLIT_PORT (backend=$PSX_BACKEND) ..."
python3 -m streamlit run streamlit_app.py --server.port "$STREAMLIT_PORT"
