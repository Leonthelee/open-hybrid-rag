@echo off
title Open Hybrid RAG Gateway Launcher
echo ============================================================
echo   Iniciando Open Hybrid RAG Gateway (Windows Launcher)
echo ============================================================

if not exist ".env" (
    echo [INFO] Creando archivo .env desde .env.example...
    copy .env.example .env
)

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [INFO] Creando entorno virtual de Python (.venv)...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo [INFO] Instalando dependencias...
    pip install -r requirements.txt
)

echo [OK] Levantando Gateway en http://localhost:8000 ...
python -m src.main
pause
