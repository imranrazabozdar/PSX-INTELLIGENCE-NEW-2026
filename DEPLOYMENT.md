# Deploying PSX Intelligence to the browser

Two pieces, two hosts:

- **Backend** (`backend/app.py`, FastAPI + its background refresh loops + `psx_v2.db`) → a host with a persistent disk. These instructions use **Render**.
- **Frontend** (`streamlit_app.py`) → **Streamlit Community Cloud**, pointed at the backend's public URL.

## Why not free-tier everything

The backend's whole value is `psx_v2.db` — 542K+ backfilled OHLCV rows built up over time. Render's free web-service tier has **no persistent disk**: every redeploy/restart wipes the filesystem, so the database would be gone the first time the service restarts (which happens often on the free tier — it sleeps after inactivity). Render's **Starter** plan (paid, ~$7/mo at time of writing) with a disk attached is the cheapest tier that actually keeps your data. `render.yaml` in this repo is already configured for that.

## 1. Push to GitHub

Both Render (via a GitHub-connected Blueprint) and Streamlit Community Cloud deploy from a GitHub repo.

```bash
git init
git add -A
git commit -m "Initial commit"
```

Then create a repo on GitHub (public — Streamlit Community Cloud's free tier needs a public repo unless you're on a paid plan) and push:

```bash
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

## 2. Deploy the backend (Render)

1. Sign in at [render.com](https://render.com), **New → Blueprint**, pick this repo. Render reads `render.yaml` and proposes the `psx-intelligence-backend` service with its disk already configured.
2. Before the first deploy finishes, set the **`PSX_ADMIN_TOKEN`** environment variable in the Render dashboard (Environment tab) — pick any long random string. This is required: once the backend has a public URL, `_require_admin()`'s "trust localhost" fallback no longer applies to anyone (including you), so without a token nobody — including you, from the deployed Streamlit app — can trigger force-rescans or backfills.
3. Once live, note the backend's URL (`https://psx-intelligence-backend.onrender.com` or similar) and confirm `https://<that-url>/health` returns `{"ok": true, ...}`.
4. **Seed the database.** A fresh disk starts empty — either:
   - Upload your local `backend/psx_v2.db` to the persistent disk via Render's shell (`render ssh` / dashboard shell, then `scp` or a one-off upload), or
   - Let it rebuild from scratch by calling the backfill endpoints (`/backfill-ohlc-bulk`, then wait for the daily heavy-refresh loop to populate backtests/DSS caches) — works, but takes real time and hits PSX/Yahoo repeatedly for months of history.
   Copying the existing file is faster and avoids re-hammering PSX's portal.

## 3. Deploy the frontend (Streamlit Community Cloud)

1. Sign in at [share.streamlit.io](https://share.streamlit.io), **New app**, point it at this repo, main file `streamlit_app.py`.
2. In the app's **Settings → Secrets**, add:
   ```toml
   PSX_BACKEND = "https://psx-intelligence-backend.onrender.com"
   ```
   (`streamlit_app.py` already reads this via `os.getenv("PSX_BACKEND", ...)` — no code change needed.)
3. Deploy. The app is now a public URL anyone can open in a browser.
4. To use the "Force rescan" / "Force re-run" buttons yourself, paste the same `PSX_ADMIN_TOKEN` you set on Render into the token field next to each button in the UI — those fields already exist (`_admin_token_input`). Without it, force-actions are correctly refused for everyone, including you — that's the point.

## Checklist before calling it live

- [ ] `PSX_ADMIN_TOKEN` set on the backend (Render), matching the token you'll enter in Streamlit's admin-token fields
- [ ] `psx_v2.db` actually has data on the deployed disk (not a fresh empty one)
- [ ] `PSX_BACKEND` secret in Streamlit Cloud points at the live Render URL, `/health` returns ok
- [ ] `.streamlit/config.toml`'s `address = "127.0.0.1"` is fine to leave as-is — Streamlit Cloud ignores it and binds however its own platform requires; that setting only matters for a self-hosted `streamlit run`
