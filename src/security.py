"""
src/security.py
Capa de Seguridad de Red, Endurecimiento Criptográfico y Defensa en Profundidad:
1. Rate Limiting por Token Bucket (Memoria segura, anti-DoS por IP y API Key).
2. Middleware de Cabeceras de Endurecimiento HTTP (CSP, HSTS, X-Frame-Options, no-sniff).
3. Sanitizador de Payloads (Detección de Null Bytes, BiDi Unicode Override y caracteres de control).
"""
import time
import math
import re
import hashlib
import threading
from typing import Dict, Tuple, Optional, Any
from fastapi import Request, HTTPException, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

try:
    from . import config
except (ImportError, ValueError):
    import config

class TokenBucket:
    """
    Estructura de cubeta de tokens con reposición continua en función del tiempo.
    Capacidad (burst) y tasa de reposición (refill_rate en tokens/segundo).
    """
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_refill = time.perf_counter()
        self.last_seen = time.time()

    def consume(self, cost: float = 1.0) -> Tuple[bool, int, float, float]:
        """
        Calcula reposición y descuenta tokens de forma atómica.
        Retorna: (permitido, tokens_restantes, reset_segundos, retry_after)
        """
        now = time.perf_counter()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.last_seen = time.time()

        # Reposición lineal continua limitada por la capacidad máxima
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))

        reset_seconds = max(0.0, (self.capacity - self.tokens) / self.refill_rate) if self.refill_rate > 0 else 0.0

        if self.tokens >= cost:
            self.tokens -= cost
            remaining = int(math.floor(self.tokens))
            return True, remaining, round(reset_seconds, 2), 0.0
        else:
            needed = cost - self.tokens
            retry_after = math.ceil(needed / self.refill_rate) if self.refill_rate > 0 else 60.0
            return False, 0, round(reset_seconds, 2), float(retry_after)


class TokenBucketRateLimiter:
    """
    Administrador multi-inquilino de cubetas con bloqueo por concurrencia y limpieza periódica.
    Distingue clientes por Hash SHA-256 de API Key o por IP de origen.
    """
    def __init__(
        self,
        capacity: int = config.RATE_LIMIT_CAPACITY,
        refill_rate: float = config.RATE_LIMIT_REFILL_RATE,
        max_buckets: int = 10000
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_buckets = max_buckets
        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = threading.Lock()
        self._last_cleanup = time.time()

    @staticmethod
    def derive_client_identifier(request: Request) -> str:
        """
        Deriva un identificador seguro para el cliente:
        - Si presenta X-API-Key: usa el prefijo SHA-256 para evitar colisiones y proteger el secreto en logs.
        - De lo contrario: usa la IP remota del socket de conexión.
        """
        api_key = request.headers.get("x-api-key")
        if api_key:
            hashed = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:16]
            return f"key:{hashed}"

        client_ip = request.client.host if request.client else "127.0.0.1"
        return f"ip:{client_ip}"

    def check_rate_limit(self, identifier: str, cost: float = 1.0) -> Tuple[bool, int, float, float]:
        with self.lock:
            # Limpieza periódica cada 10 minutos o si la memoria de buckets supera max_buckets
            now_ts = time.time()
            if len(self.buckets) > self.max_buckets or (now_ts - self._last_cleanup > 600):
                self._purge_stale_buckets(ttl_seconds=3600)
                self._last_cleanup = now_ts

            if identifier not in self.buckets:
                self.buckets[identifier] = TokenBucket(self.capacity, self.refill_rate)

            bucket = self.buckets[identifier]
            return bucket.consume(cost)

    def _purge_stale_buckets(self, ttl_seconds: float = 3600.0):
        now = time.time()
        to_delete = [k for k, b in self.buckets.items() if (now - b.last_seen) > ttl_seconds]
        for k in to_delete:
            del self.buckets[k]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Inyecta cabeceras de endurecimiento HTTP en cada respuesta del Gateway
    (OWASP Secure Headers Project / CIS Hardening).
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # 1. Protección contra Clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # 2. Protección contra MIME Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 3. Content Security Policy estricto (API Gateway no ejecuta scripts ni marcos ajenos)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"

        # 4. Strict Transport Security (HSTS para forzar canales HTTPS seguros)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # 5. Política de Referrer para evitar fuga de tokens en URLs
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 6. Deshabilitar APIs de sensores de hardware y permisos innecesarios
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        # 7. Máscara de Servidor para ocultar banners de Uvicorn / Python
        response.headers["Server"] = "OpenHybridRAG-Guard/1.0"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware de Rate Limiting por Token Bucket.
    Añade cabeceras X-RateLimit-* y bloquea ráfagas abusivas con HTTP 429.
    """
    def __init__(self, app, limiter: TokenBucketRateLimiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Permitir rutas de sondeo de salud, métricas y documentación sin agotar cuota principal
        exempt_paths = ("/", "/health", "/metrics", "/docs", "/openapi.json", "/redoc")
        if request.url.path in exempt_paths:
            return await call_next(request)

        client_id = self.limiter.derive_client_identifier(request)
        allowed, remaining, reset_secs, retry_after = self.limiter.check_rate_limit(client_id, cost=1.0)

        if not allowed:
            try:
                from .telemetry import metrics_collector
            except (ImportError, ValueError):
                from telemetry import metrics_collector
            metrics_collector.inc_counter("rate_limit_exceeded_total")

            # Respuesta HTTP 429 Too Many Requests estándar
            content = (
                f'{{"error": "Too Many Requests", '
                f'"detail": "Límite de tasa excedido. Por favor intente más tarde.", '
                f'"retry_after": {retry_after}}}'
            )
            resp = Response(content=content, status_code=429, media_type="application/json")
            resp.headers["Retry-After"] = str(int(retry_after))
            resp.headers["X-RateLimit-Limit"] = str(self.limiter.capacity)
            resp.headers["X-RateLimit-Remaining"] = "0"
            resp.headers["X-RateLimit-Reset"] = str(int(reset_secs))
            return resp

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limiter.capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(reset_secs))
        return response


class PayloadSanitizer:
    """
    Defensa en Profundidad: Detección y rechazo de vectores de ataque por inyección en payloads.
    Bloquea Null Bytes, Unicode BiDi Override y caracteres de control dañinos.
    """
    # Caracteres de control ASCII no imprimibles peligrosos (excluyendo newline, retorno de carro y tabulador)
    DANGEROUS_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
    
    # Bi-directional Unicode Override que ocultan extensiones o código malicioso en terminales y editores
    BIDI_OVERRIDE_CHARS = re.compile(r"[\u202A-\u202E\u2066-\u2069]")

    @classmethod
    def sanitize_text(cls, text: str, field_name: str = "payload") -> str:
        """
        Analiza el texto de entrada. Lanza ValueError si detecta secuencias de ataque.
        """
        if not text:
            return text

        # 1. Null Byte Injection (\x00)
        if "\x00" in text or "\\x00" in text or "%00" in text:
            raise ValueError(
                f"Payload malicioso detectado en campo '{field_name}': Intento de Null Byte Injection."
            )

        # 2. Caracteres de control dañinos
        if cls.DANGEROUS_CONTROL_CHARS.search(text):
            raise ValueError(
                f"Payload malicioso detectado en campo '{field_name}': Contiene caracteres de control no permitidos."
            )

        # 3. Unicode BiDi Override (CVE-2021-42574 Trojan Source)
        if cls.BIDI_OVERRIDE_CHARS.search(text):
            raise ValueError(
                f"Payload malicioso detectado en campo '{field_name}': Intento de Unicode BiDi Override (Trojan Source)."
            )

        return text
