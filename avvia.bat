@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [ERRORE] Ambiente .venv mancante e 'uv' non trovato nel PATH.
        echo Installa uv da https://docs.astral.sh/uv/ e riesegui avvia.bat.
        pause
        exit /b 1
    )
    echo Creazione ambiente virtuale con uv...
    uv sync
    if errorlevel 1 (
        echo [ERRORE] Creazione ambiente virtuale fallita.
        pause
        exit /b 1
    )
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
