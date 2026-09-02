# Deploying to Hugging Face Spaces (Docker)

This repo is ready to deploy as-is — `Dockerfile`, `.dockerignore`, and the
Space config block at the top of `README.md` are already in place. The one
part that needs a human with Hugging Face account access:

## 1. Create the Space

1. Go to https://huggingface.co/new-space
2. Owner: your account. Space name: anything (e.g. `psx-intelligence`).
3. **SDK: Docker**. License: whatever you prefer. Visibility: Private
   recommended (this app has no login of its own — the backend's
   `PSX_ADMIN_TOKEN` gate is the only access control on write endpoints).
4. Click "Create Space" — it creates an empty git repo at
   `https://huggingface.co/spaces/<you>/<space-name>`.

## 2. Push this repo to it

From your local clone of this GitHub repo:

```bash
git remote add hf https://huggingface.co/spaces/<you>/<space-name>
git push hf claude/streamlit-tabs-data-refresh-wvk74c:main
```

(You'll be prompted for a Hugging Face access token as the password — create
one at https://huggingface.co/settings/tokens with "write" scope.)

The Space will start building automatically on push — first build takes a
few minutes (installing pandas/numpy/streamlit/deap/etc. from scratch).
Watch progress under the Space's "Logs" tab.

## 3. Add secrets

Same two values this project's GitHub Actions workflows already use:
Space Settings → "Variables and secrets" → add as **secrets** (not public
variables, since these are credentials):

- `LIBSQL_URL`
- `LIBSQL_AUTH_TOKEN`

Without these the backend falls back to an empty local SQLite file (same
behavior as everywhere else in this project — see `backend/turso_db.py`).

Optional: `PSX_ADMIN_TOKEN` if you want the admin-gated endpoints
(force-refresh scans, backfill triggers) reachable from this deployment.

## 4. Keeping it updated

Re-run the `git push hf ...` command above whenever you want the Space to
pick up new commits — there's no automatic sync from GitHub without a paid
Spaces plan or a small GitHub Action (mirror push) you'd add yourself.

## Why this instead of / alongside Streamlit Community Cloud

Same app, same `PSX_EMBED_BACKEND=1` single-process mode Streamlit Cloud
already uses — nothing about the code changes. The difference is
container resources: Spaces' free CPU tier (2 vCPU / 16GB RAM) is
substantially larger than Streamlit Community Cloud's free tier, and
Spaces doesn't share that container with anyone else's app the way some
shared free hosts do. You can run both deployments off the same repo at
once if you want to compare.
