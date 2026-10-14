import unittest
import asyncio
import json
from starlette.testclient import TestClient
import httpx
from src.main import app, vector_guard, local_engine
from src import config
from sdk.client import OpenHybridRAGClient, AsyncOpenHybridRAGClient

class TestStreamingSSE(unittest.TestCase):
    """
    Pruebas unitarias de streaming de tokens Server-Sent Events (SSE)
    en el endpoint /api/v1/orchestrate/stream y en el cliente SDK.
    """

    @classmethod
    def setUpClass(cls):
        cls.api_key = config.API_KEY or "test_key"
        cls.headers = {"X-API-Key": cls.api_key}
        cls.client = TestClient(app, headers=cls.headers)

        # Ingestar documento de prueba en memoria
        async def init_doc():
            vec = await local_engine.get_embedding("Docker CIS Hardening: ejecutar como usuario no-root y sistema de solo lectura.")
            if not vec:
                vec = [0.05] * 1024
            vector_guard.add_document(
                doc_id="DOC-STREAM-TEST",
                text="Docker CIS Hardening: ejecutar como usuario no-root y sistema de solo lectura.",
                vector=vec,
                doc_type="document"
            )
        asyncio.run(init_doc())

    def test_sse_endpoint_direct_streaming(self):
        """Verifica que /api/v1/orchestrate/stream emita eventos SSE válidos ('meta', 'token', 'done')."""
        payload = {
            "query": "Docker CIS Hardening usuario no-root",
            "allow_cloud_fallback": False
        }
        response = self.client.post("/api/v1/orchestrate/stream", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))

        events = []
        current_event = None
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            line = line.strip()
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:].strip()
                parsed_data = json.loads(data_str)
                events.append({"event": current_event, "data": parsed_data})

        event_types = [e["event"] for e in events]
        self.assertIn("meta", event_types)
        self.assertIn("done", event_types)

        # Verificar evento meta
        meta_ev = next(e for e in events if e["event"] == "meta")
        self.assertIn("route_taken", meta_ev["data"])
        self.assertIn("similarity_score", meta_ev["data"])

        # Verificar evento done
        done_ev = next(e for e in events if e["event"] == "done")
        self.assertIn("answer", done_ev["data"])
        self.assertIn("telemetry", done_ev["data"])

    def test_sync_sdk_stream_query(self):
        """Verifica que OpenHybridRAGClient.stream_query() consuma y estructure el stream SSE."""
        sdk_client = OpenHybridRAGClient(app=app, api_key=self.api_key)
        events = list(sdk_client.stream_query("Docker CIS Hardening", allow_cloud_fallback=False))
        sdk_client.close()

        self.assertGreater(len(events), 0)
        event_names = [e["event"] for e in events]
        self.assertIn("meta", event_names)
        self.assertIn("done", event_names)

        tokens = [e["data"]["token"] for e in events if e["event"] == "token"]
        full_text = "".join(tokens)
        self.assertIsInstance(full_text, str)

    def test_async_sdk_stream_query(self):
        """Verifica que AsyncOpenHybridRAGClient.stream_query() opere de forma asincrónica."""
        async def run_async():
            async with AsyncOpenHybridRAGClient(app=app, api_key=self.api_key) as client:
                events = []
                async for event in client.stream_query("Docker CIS Hardening", allow_cloud_fallback=False):
                    events.append(event)
                return events

        events = asyncio.run(run_async())
        self.assertGreater(len(events), 0)
        event_names = [e["event"] for e in events]
        self.assertIn("meta", event_names)
        self.assertIn("done", event_names)

    def test_qa_cache_hit_streaming(self):
        """Verifica que las respuestas cacheadas en alta certeza también se transmitan vía SSE."""
        qa_vec = [0.1] * 1024
        vector_guard.add_document(
            doc_id="QA-STREAM-CACHE",
            text="Respuesta inmediata desde memoria cache.",
            vector=qa_vec,
            doc_type="qa_cache"
        )
        payload = {
            "query": "Consulta para probar streaming de QA Cache",
            "allow_cloud_fallback": False
        }
        response = self.client.post("/api/v1/orchestrate/stream", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
