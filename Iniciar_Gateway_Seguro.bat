@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ===============================================================================
echo      OPEN HYBRID RAG GATEWAY - SECURE PRE-FLIGHT INITIALIZER
echo ===============================================================================
echo.

:: 1. Verificación de Entorno Virtual
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo [OK] Entorno virtual detectado en .venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [OK] Entorno virtual detectado en venv
) else (
    echo [AVISO] Usando interprete de Python global del sistema.
)

:: 2. Ejecutar Auditoría Pre-Flight Automatizada
echo.
echo [1/2] Ejecutando Auditoría de Seguridad Pre-Flight (OWASP API Top 10 / CIS)...
echo -------------------------------------------------------------------------------
%PYTHON_EXE% scripts\audit_gateway_security.py
set AUDIT_EXIT_CODE=%ERRORLEVEL%
echo -------------------------------------------------------------------------------

if not %AUDIT_EXIT_CODE%==0 (
    echo.
    echo ❌ [BLOQUEO DE SEGURIDAD CRÍTICO]
    echo La auditoría pre-flight detectó fallos en los controles de seguridad obligatorios.
    echo Por política perimetral estricta, el Gateway NO será inicializado.
    echo.
    echo Revise los fallos listados arriba y corríjalos antes de encender el servidor.
    pause
    exit /b %AUDIT_EXIT_CODE%
)

echo.
echo ✅ [AUDITORÍA APROBADA] 11/11 Controles de seguridad verificados al 100%%.

:: 3. Configuración de Enlace Seguro a Loopback
set HOST=127.0.0.1
set PORT=8000

echo.
echo [2/2] Iniciando Open Hybrid RAG Gateway...
echo Enlace perimetral: http://%HOST%:%PORT% (Loopback aislado)
echo Telemetría Prometheus activa en: http://%HOST%:%PORT%/metrics
echo Presione Ctrl+C para detener el servicio de forma segura.
echo.

%PYTHON_EXE% -m uvicorn src.main:app --host %HOST% --port %PORT% --log-level info

endlocal
