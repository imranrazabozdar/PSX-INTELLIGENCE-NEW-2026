# PSX Intelligence — single-container deploy (Streamlit UI + embedded
# FastAPI backend, same PSX_EMBED_BACKEND=1 mode Streamlit Community Cloud
# uses since that platform only runs one process per app). Built for
# Hugging Face Spaces' Docker SDK (expects the app on $PORT, default 7860),
# but works on any container host (Render, Fly.io, Cloud Run) the same way.
FROM python:3.12-slim

WORKDIR /app

# libxml2/libxslt: lxml (used by a couple of backend scraping paths) needs
# these at build time to compile from source on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt lxml

COPY . .

ENV PSX_EMBED_BACKEND=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true

# Hugging Face Spaces injects $PORT (defaults to 7860 for Docker Spaces);
# every other host in the module docstring above either respects $PORT too
# or lets you set one explicitly, so this stays portable across all of them.
ENV PORT=7860
EXPOSE 7860

CMD streamlit run streamlit_app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.fileWatcherType=none
