@echo off
REM run_dashboard.bat — launches the PSX Intelligence backend (FastAPI/
REM uvicorn) and frontend (Streamlit) each in their own terminal window,
REM and prints the phone-accessible URL. Double-click this file to start
REM both servers.
REM
REM Backend stays on localhost only (Streamlit talks to it server-side,
REM not from the phone's browser, so it never needs to be LAN-exposed).
REM Frontend is bound to 0.0.0.0 so your phone (same Wi-Fi network) can
REM reach it at your PC's LAN IPv4 address on port 8501.

setlocal

set "PROJECT_ROOT=%~dp0"
set "LAN_IP=192.168.100.4"

echo Starting backend (FastAPI/uvicorn) on http://localhost:8000 ...
start "PSX Backend (uvicorn)" cmd /k "cd /d "%PROJECT_ROOT%backend" && python -m uvicorn app:app --reload"

echo Starting frontend (Streamlit) on port 8501, bound to 0.0.0.0 ...
start "PSX Dashboard (Streamlit)" cmd /k "cd /d "%PROJECT_ROOT%" && python -m streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=8501"

echo.
echo ============================================================
echo   TO VIEW ON YOUR PHONE, OPEN YOUR BROWSER AND GO TO:
echo   http://%LAN_IP%:8501
echo ============================================================
echo.
echo (Your phone must be on the SAME Wi-Fi network as this PC.)
echo (If it does not load, Windows Firewall may be blocking the
echo  connection — allow Python/Streamlit through the firewall when
echo  prompted, or add an inbound rule for port 8501.)
echo.
pause
