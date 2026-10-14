import unittest
import asyncio
from unittest.mock import patch
import httpx

from src.main import app, vector_guard
from src import config
from sdk import (
    OpenHybridRAGClient,
    AsyncOpenHybridRAGClient,
    QueryResponse,
    RateLimitError
)

class TestPythonSDK(unittest.TestCase):
    def setUp(self):
        self.save_patcher = patch.object(vector_guard, "save_to_disk")
        self.save_patcher.start()
        self.api_key = config.API_KEY or "test_key"
        self.client = OpenHybridRAGClient(
            base_url="http://testserver",
            api_key=self.api_key,
            app=app,
            max_retries=2
        )

    def tearDown(self):
        self.save_patcher.stop()
        self.client.close()

    def test_sdk_health_and_metrics(self):
        health = self.client.health()
        self.assertIn("status", health)
        self.assertEqual(health["status"], "online")

        metrics_text = self.client.get_metrics()
        self.assertIn("open_hybrid_rag_build_info", metrics_text)

    def test_sdk_query_orchestration(self):
        res = self.client.query(
            prompt="¿Qué mitigaciones propone CIS Benchmarks para Docker?",
            allow_cloud_fallback=True
        )
        self.assertIsInstance(res, QueryResponse)
        self.assertTrue(len(res.query) > 0)
        self.assertIn(res.route_taken, ["RESOLVE_LOCAL_HIGH", "RESOLVE_LOCAL_MED", "RESOLVE_LOCAL_ZERO_SHOT", "ESCALATE_TO_CLOUD", "LOCAL_ABSTENTION"])
        self.assertIsInstance(res.telemetry, dict)

    def test_sdk_automatic_429_retry_success(self):
        """Simula una respuesta 429 temporal y valida que el SDK reintente automáticamente."""
        real_request = self.client._client.request

        attempt = 0
        def mocked_request(method, url, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                # Primer intento: simular 429 Too Many Requests con Retry-After de 0.05s
                resp = httpx.Response(
                    status_code=429,
                    headers={"Retry-After": "0.05", "Content-Type": "application/json"},
                    json={"error": "Too Many Requests", "detail": "Límite excedido"}
                )
                return resp
            # Segundo intento: devolver respuesta real
            return real_request(method=method, url=url, **kwargs)

        with patch.object(self.client._client, "request", side_effect=mocked_request):
            res = self.client.query("Consulta de prueba con reintento 429")
            self.assertIsInstance(res, QueryResponse)
            self.assertEqual(res.retries_made, 1)
            self.assertEqual(attempt, 2)

    def test_sdk_429_exhaustion_raises_ratelimiterror(self):
        """Simula 429 continuo y valida que se lance RateLimitError tras max_retries."""
        def persistent_429_request(method, url, **kwargs):
            return httpx.Response(
                status_code=429,
                headers={"Retry-After": "0.02", "Content-Type": "application/json"},
                json={"error": "Too Many Requests", "retry_after": 0.02}
            )

        with patch.object(self.client._client, "request", side_effect=persistent_429_request):
            with self.assertRaises(RateLimitError) as ctx:
                self.client.query("Esta consulta debe fallar por rate limit")
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertEqual(ctx.exception.retry_after, 0.02)

    def test_async_sdk_health_and_query(self):
        """Prueba las capacidades del cliente asíncrono AsyncOpenHybridRAGClient."""
        async def run_async():
            async with AsyncOpenHybridRAGClient(
                base_url="http://testserver",
                api_key=self.api_key,
                app=app
            ) as aclient:
                h = await aclient.health()
                self.assertEqual(h["status"], "online")

                q = await aclient.query("Consulta asíncrona de prueba")
                self.assertIsInstance(q, QueryResponse)

        asyncio.run(run_async())

if __name__ == "__main__":
    unittest.main()
