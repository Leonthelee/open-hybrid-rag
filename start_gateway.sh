#!/usr/bin/env bash
echo "============================================================"
echo "  Starting Open Hybrid RAG Gateway (Linux / macOS)"
echo "============================================================"

if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "[INFO] Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "[OK] Starting Gateway at http://localhost:8000 ..."
python3 -m src.main
