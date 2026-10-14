# ==============================================================================
# Open Hybrid RAG Gateway - Hardened Dockerfile
# Conforme a CIS Docker Benchmark v1.6.0 & OWASP Container Security Guidelines
# ==============================================================================

# ------------------------------------------------------------------------------
# Etapa 1: Builder (Compilación y Resolución de Dependencias)
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# ------------------------------------------------------------------------------
# Etapa 2: Runtime Minimal y Hardened (Sin Compiladores ni Herramientas Innecesarias)
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/appuser/.local/bin:$PATH"

# CIS 4.1: Crear usuario sin privilegios explícito con UID/GID no-root y sin shell interactivo
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /home/appuser -m appuser

# Copiar paquetes instalados desde el builder directamente al home del usuario
COPY --from=builder /root/.local /home/appuser/.local

# Copiar código fuente y directorios necesarios
COPY src/ ./src/
COPY sdk/ ./sdk/
COPY benchmark/ ./benchmark/

# Crear directorios para persistencia atómica y conceder permisos al usuario
RUN mkdir -p /app/data /app/knowledge_base /app/second_brain && \
    chown -R appuser:appgroup /app/data /app/knowledge_base /app/second_brain /home/appuser && \
    chmod -R 750 /app/data /app/knowledge_base /app/second_brain

# CIS 4.6: Verificación de salud interna determinista (Healthcheck)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Activar usuario sin privilegios
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
