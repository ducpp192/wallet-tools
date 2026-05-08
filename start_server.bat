@echo off
chcp 65001 >nul
title Token Scanner - port 5012

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo   TOKEN SCANNER - Holdings ^& LP Checker
echo   Dashboard: http://localhost:5012
echo ============================================================
echo.

echo [*] Kiem tra port 5012...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5012 "') do (
    if not "%%a"=="0" (
        echo [!] Dang tat process cu tren port 5012 ^(PID %%a^)...
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

if not exist "%SCRIPT_DIR%main.py" (
    echo [!] KHONG TIM THAY main.py
    echo     %SCRIPT_DIR%
    echo.
    pause
    exit /b 1
)

echo [*] Khoi dong... Mo browser sau 3 giay.
start "" cmd /c "timeout /t 3 >nul && start http://localhost:5012"

echo [*] Chay: python main.py
echo.
python main.py

echo.
echo [!] Server da dung. Nhan phim bat ky de dong...
pause >nul
