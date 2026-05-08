@echo off
chcp 65001 >nul
title Wallet Generator - port 5013

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo   WALLET GENERATOR
echo   Dashboard: http://localhost:5013
echo ============================================================
echo.

echo [*] Kiem tra port 5013...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5013 "') do (
    if not "%%a"=="0" (
        echo [!] Dang tat process cu tren port 5013 ^(PID %%a^)...
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

if not exist "%SCRIPT_DIR%wallet_server.py" (
    echo [!] KHONG TIM THAY wallet_server.py
    echo     %SCRIPT_DIR%
    echo.
    pause
    exit /b 1
)

echo [*] Khoi dong... Mo browser sau 2 giay.
start "" cmd /c "timeout /t 2 >nul && start http://localhost:5013"

echo [*] Chay: python wallet_server.py
echo.
python wallet_server.py

echo.
echo [!] Server da dung. Nhan phim bat ky de dong...
pause >nul
