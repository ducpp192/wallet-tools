@echo off
chcp 65001 >nul
title ETH Sweeper - port 5015

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo   ETH SWEEPER - Base network
echo   Dashboard: http://localhost:5015
echo ============================================================
echo.

echo [*] Kiem tra port 5015...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5015 "') do (
    if not "%%a"=="0" (
        echo [!] Dang tat process cu tren port 5015 ^(PID %%a^)...
        taskkill /PID %%a /F >nul 2>&1
    )
)

if exist "%SCRIPT_DIR%venv\Scripts\activate.bat" (
    echo [*] Dang kich hoat virtual environment...
    call "%SCRIPT_DIR%venv\Scripts\activate.bat"
) else if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    echo [*] Dang kich hoat virtual environment...
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
) else (
    echo [i] Khong tim thay venv, dung Python he thong.
)

echo.

echo [*] Khoi dong... Mo browser sau 2 giay.
start "" cmd /c "timeout /t 2 >nul && start http://localhost:5015"

echo [*] Chay: python sweep_server.py
echo.
python sweep_server.py

echo.
echo [!] Server da dung. Nhan phim bat ky de dong...
pause >nul
