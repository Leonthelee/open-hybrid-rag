import time
import unittest
from fastapi.testclient import TestClient

from src.main import app
from src.security import (
    TokenBucket,
    TokenBucketRateLimiter,
    PayloadSanitizer
)
from src import config

class TestSecurityHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_security_headers_present_on_all_responses(self):
        """Valida que todas las cabeceras de endurecimiento CIS/OWASP estén activas."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)

        # 1. Clickjacking
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        # 2. MIME sniffing
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        # 3. Content Security Policy
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy", ""))
        # 4. HSTS
        self.assertIn("max-age=31536000", res.headers.get("Strict-Transport-Security", ""))
        # 5. Referrer Policy
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        # 6. Server banner enmascarado
        self.assertEqual(res.headers.get("Server"), "OpenHybridRAG-Guard/1.0")

    def test_token_bucket_math_and_burst_exhaustion(self):
        """Verifica la mecánica matemática de reposición y bloqueo de ráfagas."""
        # Capacidad 3 tokens, recarga 1 token/segundo
        bucket = TokenBucket(capacity=3.0, refill_rate=1.0)

        # Consumir los 3 tokens disponibles
        ok1, rem1, reset1, retry1 = bucket.consume(1.0)
        self.assertTrue(ok1)
        self.assertEqual(rem1, 2)

        ok2, rem2, reset2, retry2 = bucket.consume(1.0)
        self.assertTrue(ok2)
        self.assertEqual(rem2, 1)

        ok3, rem3, reset3, retry3 = bucket.consume(1.0)
        self.assertTrue(ok3)
        self.assertEqual(rem3, 0)

        # Intento de 4to token sin saldo -> Bloqueo HTTP 429 equivalente
        ok4, rem4, reset4, retry4 = bucket.consume(1.0)
        self.assertFalse(ok4)
        self.assertEqual(rem4, 0)
        self.assertGreaterEqual(retry4, 1.0)

    def test_rate_limiter_distinct_client_keys(self):
        """Comprueba que clientes con distintas claves o IPs no compartan cuota."""
        limiter = TokenBucketRateLimiter(capacity=2, refill_rate=1.0)

        ok_a1, _, _, _ = limiter.check_rate_limit("client_alice")
        ok_a2, _, _, _ = limiter.check_rate_limit("client_alice")
        ok_a3, _, _, _ = limiter.check_rate_limit("client_alice")

        self.assertTrue(ok_a1)
        self.assertTrue(ok_a2)
        self.assertFalse(ok_a3) # Alice bloqueada

        # Bob debe tener su cuota completa de 2 intacta
        ok_b1, _, _, _ = limiter.check_rate_limit("client_bob")
        self.assertTrue(ok_b1)

    def test_payload_sanitizer_blocks_null_bytes(self):
        """Detecta y rechaza intentos de Null Byte Injection."""
        # En memoria directa
        with self.assertRaises(ValueError) as ctx:
            PayloadSanitizer.sanitize_text("SELECT * FROM users\x00 WHERE id=1")
        self.assertIn("Null Byte Injection", str(ctx.exception))

        # En endpoint HTTP a través de Pydantic
        headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        res = self.client.post("/api/v1/orchestrate", json={
            "query": "Explica la arquitectura\x00 de seguridad",
            "allow_cloud_fallback": False
        }, headers=headers)
        self.assertEqual(res.status_code, 422)
        self.assertIn("Null Byte Injection", res.text)

    def test_payload_sanitizer_blocks_unicode_bidi_override(self):
        """Detecta y rechaza caracteres de Bi-directional Unicode Override (Trojan Source)."""
        # Carácter Right-to-Left Override (\u202E)
        malicious_input = "valida este script \u202Efd.py"
        with self.assertRaises(ValueError) as ctx:
            PayloadSanitizer.sanitize_text(malicious_input)
        self.assertIn("Unicode BiDi Override", str(ctx.exception))

        headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        res = self.client.post("/api/v1/orchestrate", json={
            "query": malicious_input,
            "allow_cloud_fallback": False
        }, headers=headers)
        self.assertEqual(res.status_code, 422)
        self.assertIn("Unicode BiDi Override", res.text)

    def test_rate_limiting_headers_on_api_endpoints(self):
        """Verifica que endpoints de API incluyan cabeceras X-RateLimit-*."""
        headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        res = self.client.get("/api/v1/config", headers=headers)
        self.assertIn("X-RateLimit-Limit", res.headers)
        self.assertIn("X-RateLimit-Remaining", res.headers)
        self.assertIn("X-RateLimit-Reset", res.headers)

    def test_api_returns_429_when_rate_limit_exceeded(self):
        """Valida que el middleware bloquee con HTTP 429 y Retry-After al agotarse la cubeta."""
        from src.main import rate_limiter
        import hashlib

        headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        if config.API_KEY:
            client_id = f"key:{hashlib.sha256(config.API_KEY.encode()).hexdigest()[:16]}"
        else:
            client_id = "ip:testclient"

        # Simular agotamiento forzado de tokens
        rate_limiter.buckets[client_id] = TokenBucket(capacity=config.RATE_LIMIT_CAPACITY, refill_rate=config.RATE_LIMIT_REFILL_RATE)
        rate_limiter.buckets[client_id].tokens = 0.0

        res = self.client.get("/api/v1/config", headers=headers)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res.headers)
        self.assertEqual(res.headers.get("X-RateLimit-Remaining"), "0")
        self.assertIn("Límite de tasa excedido", res.text)

        # Restaurar tokens para no afectar otros tests
        rate_limiter.buckets[client_id].tokens = float(config.RATE_LIMIT_CAPACITY)

if __name__ == "__main__":
    unittest.main()
