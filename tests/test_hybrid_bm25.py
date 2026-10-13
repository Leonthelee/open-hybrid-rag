import os
import shutil
import tempfile
import unittest
import numpy as np

from src.bm25 import BM25Index, reciprocal_rank_fusion
from src.vector_guard import VectorGuard

class TestOkapiBM25(unittest.TestCase):
    def setUp(self):
        self.bm25 = BM25Index(k1=1.5, b=0.75)

    def test_tokenize_preserves_technical_tokens(self):
        text = "Falla de seguridad API3:2023 y error HTTP_422 en endpoint /api/v1/checkout con CVE-2024-1234."
        tokens = self.bm25.tokenize(text)
        self.assertIn("api3:2023", tokens)
        self.assertIn("http_422", tokens)
        self.assertIn("cve-2024-1234", tokens)
        self.assertIn("api", tokens)

    def test_bm25_exact_keyword_retrieval(self):
        doc1 = "Configuración de balanceador de carga NGINX con timeouts y buffers estándar."
        doc2 = "Vulnerabilidad de inyección SQL en autenticación y tokens JWT expirados."
        doc3 = "Detección de BOPLA Broken Object Property Level Authorization y error HTTP_422 en APIs."

        self.bm25.add_document("doc1", doc1)
        self.bm25.add_document("doc2", doc2)
        self.bm25.add_document("doc3", doc3)

        self.assertEqual(self.bm25.doc_count, 3)

        # Consulta con término técnico exclusivo
        query = "bopla http_422"
        scores = self.bm25.score(query)

        self.assertIn("doc3", scores)
        self.assertGreater(scores["doc3"], 0.0)
        self.assertEqual(scores.get("doc1", 0.0), 0.0)
        self.assertEqual(scores.get("doc2", 0.0), 0.0)

        rankings = self.bm25.rank(query, top_k=1)
        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0][0], "doc3")

    def test_delete_document_updates_stats(self):
        self.bm25.add_document("docA", "protocolo de autenticación zero trust")
        self.bm25.add_document("docB", "auditoría de llaves ssh")

        self.assertEqual(self.bm25.doc_count, 2)
        self.assertTrue(self.bm25.delete_document("docA"))
        self.assertEqual(self.bm25.doc_count, 1)

        scores = self.bm25.score("zero trust")
        self.assertEqual(len(scores), 0)

    def test_reciprocal_rank_fusion_logic(self):
        # Caso: doc_lexical es #1 en sparse y #2 en dense
        # doc_semantic es #1 en dense pero no aparece en sparse (término no coincide)
        dense_ranks = ["doc_semantic", "doc_lexical", "doc_other"]
        sparse_ranks = ["doc_lexical"]

        fused = reciprocal_rank_fusion(
            dense_ranks=dense_ranks,
            sparse_ranks=sparse_ranks,
            k=60,
            weight_dense=0.5,
            weight_sparse=0.5
        )

        # doc_lexical: 0.5/(60+2) + 0.5/(60+1) = 0.5/62 + 0.5/61 = 0.008064 + 0.008196 = 0.01626
        # doc_semantic: 0.5/(60+1) + 0 = 0.008196
        self.assertEqual(fused[0][0], "doc_lexical")
        self.assertEqual(fused[1][0], "doc_semantic")


class TestVectorGuardHybridMatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.guard = VectorGuard(high_threshold=0.85, min_threshold=0.60)

        # Documento A: semánticamente similar pero genérico
        # Vector A: [0.9, 0.1, 0.0, 0.0] -> normalizado
        v_a = [0.9, 0.1, 0.0, 0.0]
        # Documento B: contiene identificador técnico exacto 'CVE-CRITICAL-99'
        # Vector B: [0.85, 0.2, 0.0, 0.0] -> ligeramente menor similitud coseno con [1.0, 0.0, 0.0, 0.0]
        v_b = [0.85, 0.2, 0.0, 0.0]

        self.guard.add_document(
            doc_id="DOC_GENERIC",
            text="Medidas de mitigación de vulnerabilidades y ciberseguridad defensiva.",
            vector=v_a,
            doc_type="document"
        )
        self.guard.add_document(
            doc_id="DOC_EXACT_VULN",
            text="Parche específico para vulnerabilidad CVE-CRITICAL-99 en librerías criptográficas.",
            vector=v_b,
            doc_type="document"
        )

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_hybrid_match_prioritizes_exact_technical_keyword(self):
        # Query con vector cercano a [1.0, 0.0, 0.0, 0.0]
        # En búsqueda puramente vectorial:
        # dot(v_a_norm, [1,0,0,0]) > dot(v_b_norm, [1,0,0,0])
        # Pero la query busca expresamente 'CVE-CRITICAL-99'
        query_text = "cómo mitigar CVE-CRITICAL-99"
        query_vec = [1.0, 0.0, 0.0, 0.0]

        # 1. Búsqueda vectorial pura
        route_dense, doc_dense, score_dense = self.guard.match(query_vec)
        self.assertEqual(doc_dense["id"], "DOC_GENERIC")

        # 2. Búsqueda Híbrida Real (Dense + BM25 + RRF)
        route_hybrid, doc_hybrid, score_hybrid = self.guard.hybrid_match(
            query_text=query_text,
            query_vector=query_vec,
            alpha=0.5
        )

        # BM25 + RRF rescatan el documento exacto DOC_EXACT_VULN
        self.assertEqual(doc_hybrid["id"], "DOC_EXACT_VULN")
        self.assertEqual(doc_hybrid["retrieval_mode"], "hybrid")
        self.assertIn("hybrid_metrics", doc_hybrid)
        self.assertGreater(doc_hybrid["hybrid_metrics"]["bm25_score"], 0.0)
        self.assertGreater(score_hybrid, 0.0)

    def test_hybrid_match_sparse_only_fallback(self):
        # Cuando el motor de embeddings local falla (query_vector=None),
        # BM25 aún es capaz de resolver en memoria local
        query_text = "librerías criptográficas CVE-CRITICAL-99"
        route, doc, score = self.guard.hybrid_match(
            query_text=query_text,
            query_vector=None
        )

        self.assertEqual(doc["id"], "DOC_EXACT_VULN")
        self.assertGreater(score, 0.0)
        self.assertIn(route, ["RESOLVE_LOCAL_MED", "RESOLVE_LOCAL_HIGH"])

    def test_persistence_reconstructs_bm25_index(self):
        storage_path = os.path.join(self.temp_dir, "hybrid_index.npz")
        self.guard.save_to_disk(storage_path)

        # Nueva instancia limpia
        new_guard = VectorGuard()
        loaded = new_guard.load_from_disk(storage_path)
        self.assertTrue(loaded)
        self.assertEqual(new_guard.bm25.doc_count, 2)

        # Ejecutar búsqueda híbrida en nueva instancia cargada
        route, doc, score = new_guard.hybrid_match(
            query_text="CVE-CRITICAL-99",
            query_vector=[1.0, 0.0, 0.0, 0.0]
        )
        self.assertEqual(doc["id"], "DOC_EXACT_VULN")

if __name__ == "__main__":
    unittest.main()
