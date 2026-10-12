@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python battaglia_navale.py %*
    goto fine
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 battaglia_navale.py %*
    goto fine
)

echo.
echo Python 3.10+ non trovato nel PATH.
echo Scaricalo da https://www.python.org/downloads/ e ricorda di spuntare
echo "Add python.exe to PATH" durante l'installazione.
echo.
pause
exit /b 1

:fine
if errorlevel 1 pause
endlocal
