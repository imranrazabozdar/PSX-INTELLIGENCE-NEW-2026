@echo off
REM start_tunnels.bat -- starts Cloudflare quick tunnels for both the
REM Streamlit dashboard (8501) and FastAPI backend (8000).
REM
REM IMPORTANT: quick tunnels (no Cloudflare account / named tunnel) get a
REM NEW RANDOM trycloudflare.com URL every time they start -- this script
REM does not give you the same URLs as before. Check the log files after
REM running this for the new URLs, and update PSX_BACKEND (see below)
REM before starting Streamlit if the backend URL changed.
REM
REM PSX_ADMIN_TOKEN must be set (see .env) before starting the backend --
REM without it, the admin-token gate falls back to localhost-only trust,
REM which a tunnel defeats (every tunneled request looks like localhost).

set CLOUDFLARED=%~dp0backend\tools\cloudflared.exe

echo Starting backend tunnel (port 8000)...
start "PSX Tunnel - Backend" "%CLOUDFLARED%" tunnel --url http://localhost:8000

echo Starting Streamlit tunnel (port 8501)...
start "PSX Tunnel - Streamlit" "%CLOUDFLARED%" tunnel --url http://localhost:8501

echo.
echo Tunnels started in their own windows -- check those windows (or
echo backend\tools\tunnel_backend.log / tunnel_streamlit.log if redirected)
echo for the new public URLs. Remember: they will be DIFFERENT from any
echo previous run.
