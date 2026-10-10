"""
Test Suite Oficial de Producción para Open Hybrid RAG Gateway
Ejecutar con: python -m unittest discover tests
"""
import os
import sys
import shutil
import asyncio
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Asegurar path de importación al root del repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import config
from vector_guard import VectorGuard
from second_brain import SecondBrain
from assert_evaluator import AssertEvaluator
from main import app, vector_guard, local_engine, cloud_bridge, second_brain, assert_evaluator

class TestVectorGuard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.index_path = os.path.join(self.temp_dir, "test_index.npz")
        self.meta_path = os.path.join(self.temp_dir, "test_index_meta.json")
        self.guard = VectorGuard()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_dimension_validation(self):
        vec_768_a = [0.1] * 768
        vec_768_b = [0.2] * 768
        vec_384 = [0.3] * 384

        self.guard.add_document("doc1", "Contenido 1", vec_768_a)
        self.guard.add_document("doc2", "Contenido 2", vec_768_b)
        self.assertEqual(len(self.guard.documents), 2)
        self.assertEqual(self.guard.expected_dim, 768)

        # Vector con dimensión incompatible debe fallar con ValueError
        with self.assertRaises(ValueError):
            self.guard.add_document("doc3", "Contenido 3", vec_384)

    def test_deduplication_and_update_by_doc_id(self):
        vec = [0.5] * 768
        self.guard.add_document("doc_duplicate", "Versión 1", vec)
        self.assertEqual(len(self.guard.documents), 1)
        self.assertEqual(self.guard.documents["doc_duplicate"]["text"], "Versión 1")

        # Reingesta del mismo doc_id debe actualizar, no duplicar
        self.guard.add_document("doc_duplicate", "Versión 2", vec)
        self.assertEqual(len(self.guard.documents), 1)
        self.assertEqual(self.guard.documents["doc_duplicate"]["text"], "Versión 2")

    def test_atomic_persistence_and_reload(self):
        vec1 = [0.1] * 128
        vec2 = [0.9] * 128
        self.guard.add_document("doc_persist_1", "Texto persistente 1", vec1, doc_type="document")
        self.guard.add_document("doc_persist_2", "Texto persistente 2", vec2, doc_type="qa_cache")
        
        # Guardar en disco de forma atómica
        self.guard.save_to_disk(self.index_path)
        self.assertTrue(os.path.exists(self.index_path))
        self.assertTrue(os.path.exists(self.meta_path))

        # Crear nuevo guard y cargar desde disco
        guard_reloaded = VectorGuard()
        loaded = guard_reloaded.load_from_disk(self.index_path)
        
        self.assertTrue(loaded)
        self.assertEqual(len(guard_reloaded.documents), 2)
        self.assertEqual(guard_reloaded.expected_dim, 128)
        self.assertEqual(guard_reloaded.documents["doc_persist_2"]["type"], "qa_cache")

    def test_system_prompt_scoping_in_cache(self):
        vec = [1.0] + [0.0] * 127
        # Guardar caché con prompt en español
        self.guard.add_document(
            "qa_1",
            "Respuesta en español",
            vec,
            doc_type="qa_cache",
            system_prompt="Responde en español técnico"
        )

        # Misma query con el mismo system_prompt -> HIGH bypass
        route, doc, score = self.guard.match(vec, system_prompt="Responde en español técnico")
        self.assertEqual(route, "RESOLVE_LOCAL_HIGH")
        self.assertEqual(doc["text"], "Respuesta en español")

        # Misma query pero con system_prompt en inglés -> Se degrada a MED (contexto) para no devolver idioma incorrecto
        route, doc, score = self.guard.match(vec, system_prompt="Answer in concise English")
        self.assertEqual(route, "RESOLVE_LOCAL_MED")


class TestSecondBrain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.brain = SecondBrain(base_path=self.temp_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_atomic_write_and_collision_prevention(self):
        saved_ids = []
        for i in range(5):
            doc_id = self.brain.save_interaction(
                query=f"Consulta concurrente {i}",
                answer=f"Respuesta generada {i}",
                source="test_suite"
            )
            saved_ids.append(doc_id)
            file_path = os.path.join(self.temp_dir, f"{doc_id}.md")
            self.assertTrue(os.path.exists(file_path))

        # Cero colisiones
        self.assertEqual(len(saved_ids), len(set(saved_ids)))


class TestAssertEvaluator(unittest.TestCase):
    def test_honest_fallback_when_judge_unavailable(self):
        evaluator = AssertEvaluator()
        with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
            res = asyncio.run(evaluator.evaluate("¿Qué es BGP?", "BGP es un protocolo...", "test_source"))
            self.assertEqual(res["evaluation_status"], "unavailable")
            self.assertIsNone(res["passed"])
            self.assertIsNone(res["overall_score"])
            self.assertIn("no estuvo disponible", res["feedback"])

    def test_schema_validation_rejects_out_of_range(self):
        evaluator = AssertEvaluator()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Simular JSON con puntaje fuera de rango (overall_score=999)
        mock_resp.json.return_value = {
            "message": {
                "content": '{"technical_score": 999, "clarity_score": 9, "route_score": 10, "overall_score": 999, "passed": true, "feedback": "fake"}'
            }
        }
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            res = asyncio.run(evaluator.evaluate("Pregunta", "Respuesta", "source"))
            self.assertEqual(res["evaluation_status"], "schema_violation")
            self.assertIsNone(res["passed"])


class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("vector_index", data)
        self.assertIn("cloud_fallback", data)

    def test_auth_rejection_on_ingest(self):
        with patch.object(config, "API_KEY", "secret_key_123"):
            # Sin header -> 401
            resp = self.client.post("/api/v1/ingest", json={"text": "documento secreto"})
            self.assertEqual(resp.status_code, 401)

            # Header incorrecto -> 401
            resp = self.client.post("/api/v1/ingest", json={"text": "documento secreto"}, headers={"X-API-Key": "wrong_key"})
            self.assertEqual(resp.status_code, 401)

            # Header correcto -> 200
            with patch.object(local_engine, "get_embedding", new_callable=AsyncMock) as mock_embed:
                mock_embed.return_value = [0.1] * 768
                resp = self.client.post("/api/v1/ingest", json={"text": "documento secreto"}, headers={"X-API-Key": "secret_key_123"})
                self.assertEqual(resp.status_code, 200)

    def test_privacy_mode_abstention(self):
        with patch.object(config, "PRIVACY_MODE", config.PrivacyMode.LOCAL_ONLY), \
             patch.object(local_engine, "get_embedding", new_callable=AsyncMock, return_value=[0.0] * 768), \
             patch.object(local_engine, "generate", new_callable=AsyncMock, return_value=(False, "Ollama no disponible")):
            
            resp = self.client.post("/api/v1/orchestrate", json={
                "query": "Pregunta confidencial sobre infraestructura interna",
                "audit_assert": False
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["route_taken"], "LOCAL_ABSTENTION")
            self.assertIn("privacidad", data["answer"].lower())

    def test_post_fallback_route_reported_correctly(self):
        # Simular que hay match local MED en vector_guard, pero el SLM local falla y la nube responde
        fake_doc = {"id": "DOC-1", "text": "Contexto técnico", "type": "document", "metadata": {}}
        with patch.object(local_engine, "get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768), \
             patch.object(vector_guard, "match", return_value=("RESOLVE_LOCAL_MED", fake_doc, 0.75)), \
             patch.object(local_engine, "generate", new_callable=AsyncMock, return_value=(False, "CUDA OOM")), \
             patch.object(cloud_bridge, "generate", new_callable=AsyncMock, return_value=(True, "Respuesta desde Cloud Fallback")):
            
            resp = self.client.post("/api/v1/orchestrate", json={
                "query": "¿Cómo optimizar BGP?",
                "allow_cloud_fallback": True,
                "audit_assert": False
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["route_taken"], "ESCALATE_TO_CLOUD_FALLBACK")
            self.assertEqual(data["source"], f"cloud_{config.CLOUD_PROVIDER}_fallback")

    def test_failed_assert_is_not_promoted_to_qa_cache(self):
        # Simular que ASSERT rechaza la respuesta (passed: False)
        failed_assert = {
            "technical_score": 3.0,
            "clarity_score": 4.0,
            "route_score": 5.0,
            "overall_score": 4.0,
            "passed": False,
            "feedback": "Comandos inventados detectados.",
            "evaluation_status": "completed"
        }
        with patch.object(local_engine, "get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768), \
             patch.object(local_engine, "generate", new_callable=AsyncMock, return_value=(True, "Respuesta alucinada")), \
             patch.object(assert_evaluator, "evaluate", new_callable=AsyncMock, return_value=failed_assert), \
             patch.object(vector_guard, "add_document") as mock_add_doc:
            
            resp = self.client.post("/api/v1/orchestrate", json={
                "query": "¿Comando secreto?",
                "audit_assert": True
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertFalse(data["assert_audit"]["passed"])
            # Verificar que VectorGuard NO agregó la respuesta rechazada al caché
            mock_add_doc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
