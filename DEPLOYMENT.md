# Deploying PSX Intelligence to the browser

One piece, one host: **Streamlit Community Cloud**, running both the frontend
(`streamlit_app.py`) and the backend (`backend/app.py`, FastAPI + its
background refresh loops) in the same process. There's no separate Render
service — `streamlit_app.py` starts the FastAPI app itself in a background
thread (`PSX_EMBED_BACKEND=1`, see `_ensure_embedded_backend()` near the top
of the file) before rendering anything.

## Why a database migration is needed

Streamlit Community Cloud has **no persistent disk** — every redeploy/restart
wipes the filesystem. The backend's whole value is `psx_v2.db` (542K+
backfilled OHLCV rows built up over time), so a plain local SQLite file would
lose everything the first time the app restarts, which happens often
(redeploys, Cloud's own maintenance restarts, resource-based restarts on the
free tier).

The fix: [Turso](https://turso.tech), a free-tier hosted SQLite-compatible
database. `backend/turso_db.py` connects to it in **embedded replica** mode —
a local file used for fast reads, transparently kept in sync with the real
database living in Turso's cloud — so every other backend module keeps using
the exact same `execute()`/`commit()` calls as before; only the connection
setup changed. Free tier: 5GB storage, 500M row reads/month — comfortably
enough for this dataset.

**Caveat (stated plainly, not glossed over):** this integration is written
against Turso's documented API but could not be exercised end-to-end in this
project's dev environment (`pip install libsql` fails to build its native
extension on this machine's Python 3.14/Windows combo — a local-sandbox
limitation, not expected to recur on Streamlit Cloud's own Linux runtime,
which ships prebuilt wheels). **Smoke-test steps 2-3 below before trusting it
with the only copy of your data** — keep your local `psx_v2.db` as a backup
until you've confirmed reads and writes round-trip correctly.

## 1. Create a Turso database and migrate your existing data

Install the Turso CLI and sign up (free, no credit card):

```bash
curl -sSfL https://get.tur.so/install.sh | bash
turso auth signup
```

Create a database seeded directly from your existing local file — this
uploads `backend/psx_v2.db` as-is, so your 542K+ rows come along for free
instead of rebuilding from scratch:

```bash
turso db create psx-intelligence --from-file backend/psx_v2.db
```

Get the two values `turso_db.py` needs:

```bash
turso db show psx-intelligence --url
turso db tokens create psx-intelligence
```

The first is `LIBSQL_URL` (starts with `libsql://`), the second is
`LIBSQL_AUTH_TOKEN`. Keep both handy for step 3.

**Smoke test before going further:** run the backend locally against this
real Turso database to confirm the integration actually works, before
deploying:

```bash
cd backend
LIBSQL_URL="libsql://..." LIBSQL_AUTH_TOKEN="..." python -m uvicorn app:app --port 8000
```

Check `http://localhost:8000/health` — the `database` field should read
`"backend": "turso (libsql embedded replica)"`, `"connected": true`,
`"init_error": null`. Click around the Streamlit app (`streamlit run
streamlit_app.py` in another terminal, pointed at this backend) to confirm a
few reads work, then trigger one write (e.g. a force-rescan) and restart the
backend to confirm the write is still there after restart — that's the part
that actually proves persistence, which is the entire point of this
migration.

## 2. Push to GitHub

Streamlit Community Cloud deploys from a GitHub repo.

```bash
git add -A
git commit -m "Prepare for Streamlit Cloud deployment"
```

Then create a repo on GitHub (public — Streamlit Community Cloud's free tier
needs a public repo unless you're on a paid plan) and push:

```bash
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

## 3. Deploy on Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io), **New app**,
   point it at this repo, main file `streamlit_app.py`.
2. In the app's **Settings → Secrets**, add:
   ```toml
   PSX_EMBED_BACKEND = "1"
   LIBSQL_URL = "libsql://..."
   LIBSQL_AUTH_TOKEN = "..."
   PSX_ADMIN_TOKEN = "<pick any long random string>"
   ```
   `PSX_ADMIN_TOKEN` is required once this is public: `_require_admin()`'s
   "trust localhost" fallback no longer applies to anyone (including you) the
   moment this has a public URL — without a token, nobody can trigger
   force-rescans or backfills, including you from the deployed app itself.
   Leave `PSX_BACKEND` unset — it defaults to `http://localhost:8000`, which
   is correct here since the backend now runs in the same process.
3. Deploy. First boot will be slower than usual — the embedded backend starts
   up, connects to Turso, and does its initial sync before the first page
   renders.
4. To use the "Force rescan" / "Force re-run" buttons yourself, paste the
   same `PSX_ADMIN_TOKEN` into the token field next to each button in the UI.

## Checklist before calling it live

- [ ] Smoke-tested the Turso connection locally (step 1) — `/health` shows
      `"backend": "turso (libsql embedded replica)"`, a write survives a
      backend restart
- [ ] `turso db create ... --from-file` actually carried over your existing
      rows (spot-check a symbol's history in the deployed app, not just row
      counts)
- [ ] `PSX_EMBED_BACKEND`, `LIBSQL_URL`, `LIBSQL_AUTH_TOKEN`, `PSX_ADMIN_TOKEN`
      all set in Streamlit Cloud's Secrets
- [ ] Kept your local `backend/psx_v2.db` as a backup until the above is
      confirmed — don't delete your only other copy of 542K+ rows until
      Turso has proven it round-trips correctly
