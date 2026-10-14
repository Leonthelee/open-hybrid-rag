import unittest
import asyncio
from src.vector_guard import VectorGuard
from scripts.eval_rag_accuracy import GOLDEN_DATASET, RAGAccuracyEvaluator

class TestRAGEvaluation(unittest.TestCase):
    """
    Pruebas unitarias para el arnés de evaluación de precisión RAG y métricas IR (Hit@1, Hit@3, MRR).
    """

    def test_golden_dataset_integrity(self):
        """Verifica que el Golden Dataset contenga preguntas válidas con documentos esperados y metadatos."""
        self.assertGreaterEqual(len(GOLDEN_DATASET), 10, "El Golden Dataset debe tener al menos 10 casos de prueba")
        for item in GOLDEN_DATASET:
            self.assertIn("id", item)
            self.assertIn("query", item)
            self.assertIn("expected_doc_id", item)
            self.assertIn("domain", item)
            self.assertTrue(len(item["query"]) > 10, "La consulta debe ser descriptiva")
            self.assertTrue(item["expected_doc_id"].startswith("sec-"), "Debe apuntar a un documento sec-* válido")

    def test_vector_guard_rank_candidates(self):
        """Verifica que VectorGuard.rank_candidates retorne listas de rankings para dense, sparse e hybrid."""
        guard = VectorGuard()
        guard.add_document("doc-1", "Ataque de inyección SQL y parámetros de validación", [0.1] * 1024)
        guard.add_document("doc-2", "Configuración de seguridad SSH y certificados criptográficos", [0.2] * 1024)

        rankings = guard.rank_candidates(query_text="inyección SQL", query_vector=[0.1] * 1024, top_k=5)
        self.assertIn("dense", rankings)
        self.assertIn("sparse", rankings)
        self.assertIn("hybrid", rankings)
        self.assertIsInstance(rankings["dense"], list)
        self.assertIsInstance(rankings["sparse"], list)
        self.assertIsInstance(rankings["hybrid"], list)

        # El doc-1 debe liderar la búsqueda léxica y la híbrida
        self.assertEqual(rankings["sparse"][0], "doc-1")
        self.assertEqual(rankings["hybrid"][0], "doc-1")

    def test_evaluator_metrics_calculation(self):
        """Verifica el cálculo determinista de Hit@1, Hit@3 y MRR."""
        evaluator = RAGAccuracyEvaluator(golden_dataset=GOLDEN_DATASET[:3])
        # Inicializar corpus mínimo en memoria
        async def run_eval():
            await evaluator.initialize_corpus()
            res = await evaluator.evaluate_query(GOLDEN_DATASET[0])
            return res

        res = asyncio.run(run_eval())
        self.assertIn("dense", res)
        self.assertIn("sparse", res)
        self.assertIn("hybrid", res)
        self.assertIn("latency_ms", res)
        self.assertIn(res["hybrid"]["hit1"], [0, 1])
        self.assertIn(res["hybrid"]["hit3"], [0, 1])
        self.assertTrue(0.0 <= res["hybrid"]["rr"] <= 1.0)

if __name__ == "__main__":
    unittest.main()
