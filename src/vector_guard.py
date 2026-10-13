import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
import numpy as np

try:
    from . import config
    from .bm25 import BM25Index, reciprocal_rank_fusion
except (ImportError, ValueError):
    import config
    from bm25 import BM25Index, reciprocal_rank_fusion

logger = logging.getLogger("open_hybrid_rag.vector_guard")

class VectorGuard:
    """
    Guardián Vectorial de Alta Densidad con Ingesta O(1) Amortizada,
    Persistencia Atómica, Aislamiento por System Prompt y TTL.
    """
    def __init__(self, high_threshold: float = config.RAG_CERTAINTY_THRESHOLD, min_threshold: float = config.RAG_MIN_THRESHOLD):
        self.high_threshold = high_threshold
        self.min_threshold = min_threshold
        self.expected_dim: Optional[int] = None
        self.vectors: List[np.ndarray] = []
        self._matrix: Optional[np.ndarray] = None
        self._matrix_dirty: bool = True
        self.doc_ids: list[str] = []
        self.documents: Dict[str, dict] = {}
        self.bm25: BM25Index = BM25Index()

    @property
    def matrix(self) -> Optional[np.ndarray]:
        """Matriz NumPy construida bajo demanda de forma vectorizada sin vstack O(N^2)."""
        if self._matrix_dirty:
            if self.vectors:
                self._matrix = np.array(self.vectors, dtype=np.float32)
            else:
                self._matrix = None
            self._matrix_dirty = False
        return self._matrix

    @staticmethod
    def compute_prompt_hash(system_prompt: Optional[str]) -> str:
        """Calcula un hash determinístico de las instrucciones del sistema para aislar el caché."""
        normalized = (system_prompt or "").strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def add_document(
        self,
        doc_id: str,
        text: str,
        vector: list[float],
        doc_type: str = "document",
        system_prompt: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[dict] = None
    ) -> bool:
        """Agrega o actualiza un documento en O(1) amortizado sin reconstruir la matriz completa."""
        vec = np.array(vector, dtype=np.float32)
        if vec.ndim != 1 or len(vec) == 0 or not np.all(np.isfinite(vec)):
            raise ValueError("El vector debe ser un array unidimensional de números finitos.")

        if self.expected_dim is None:
            self.expected_dim = len(vec)
        elif len(vec) != self.expected_dim:
            raise ValueError(
                f"Dimensión incompatible: el índice espera {self.expected_dim} dimensiones, "
                f"pero el vector recibido tiene {len(vec)}."
            )

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            raise ValueError("El vector tiene norma cero y no puede ser normalizado.")

        doc_meta = dict(metadata or {})
        if system_prompt:
            doc_meta["system_prompt_hash"] = self.compute_prompt_hash(system_prompt)

        if ttl_seconds is not None:
            doc_meta["expires_at_timestamp"] = datetime.utcnow().timestamp() + ttl_seconds

        if doc_id in self.documents:
            idx = self.doc_ids.index(doc_id)
            self.vectors[idx] = vec
        else:
            self.doc_ids.append(doc_id)
            self.vectors.append(vec)

        self._matrix_dirty = True
        self.documents[doc_id] = {
            "id": doc_id,
            "text": text,
            "type": doc_type,
            "created_at": datetime.utcnow().isoformat(),
            "metadata": doc_meta
        }
        # Sincronizar índice léxico BM25
        self.bm25.add_document(doc_id, text)
        return True

    def add_documents_batch(self, batch: List[dict]) -> int:
        """Ingesta en lote de alta velocidad con una sola reconstrucción de matriz."""
        added = 0
        for doc in batch:
            try:
                self.add_document(
                    doc_id=doc["doc_id"],
                    text=doc["text"],
                    vector=doc["vector"],
                    doc_type=doc.get("doc_type", "document"),
                    system_prompt=doc.get("system_prompt"),
                    ttl_seconds=doc.get("ttl_seconds"),
                    metadata=doc.get("metadata")
                )
                added += 1
            except Exception as e:
                logger.warning(f"Error indexando documento en lote ({doc.get('doc_id')}): {e}")
        return added

    def delete_document(self, doc_id: str) -> bool:
        """Elimina un documento de la memoria vectorial, léxica y metadatos."""
        if doc_id not in self.documents:
            return False

        idx = self.doc_ids.index(doc_id)
        self.doc_ids.pop(idx)
        self.vectors.pop(idx)
        del self.documents[doc_id]
        self.bm25.delete_document(doc_id)

        self._matrix_dirty = True
        if len(self.doc_ids) == 0:
            self.expected_dim = None

        return True

    def match(
        self,
        query_vector: list[float],
        system_prompt: Optional[str] = None
    ) -> Tuple[str, Optional[dict], float]:
        """Calcula similitud coseno ultra-rápida, verifica TTL y respeta aislamiento de instrucciones."""
        mat = self.matrix
        if mat is None or len(self.doc_ids) == 0:
            return "ESCALATE_TO_CLOUD", None, 0.0

        q_vec = np.array(query_vector, dtype=np.float32)
        if len(q_vec) != self.expected_dim:
            return "ESCALATE_TO_CLOUD", None, 0.0

        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        scores = np.dot(mat, q_vec)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_doc_id = self.doc_ids[best_idx]
        best_doc = self.documents[best_doc_id]

        # Verificar expiración TTL
        exp_ts = best_doc.get("metadata", {}).get("expires_at_timestamp")
        if exp_ts and datetime.utcnow().timestamp() > exp_ts:
            logger.info(f"[VectorGuard] Documento {best_doc_id} expirado por TTL.")
            return "ESCALATE_TO_CLOUD", None, 0.0

        if best_score >= self.high_threshold:
            if best_doc.get("type") == "qa_cache":
                cached_prompt_hash = best_doc.get("metadata", {}).get("system_prompt_hash")
                if cached_prompt_hash and system_prompt is not None:
                    current_prompt_hash = self.compute_prompt_hash(system_prompt)
                    if cached_prompt_hash != current_prompt_hash:
                        return "RESOLVE_LOCAL_MED", best_doc, best_score
                return "RESOLVE_LOCAL_HIGH", best_doc, best_score
            else:
                return "RESOLVE_LOCAL_MED", best_doc, best_score
        elif best_score >= self.min_threshold:
            return "RESOLVE_LOCAL_MED", best_doc, best_score
        else:
            return "ESCALATE_TO_CLOUD", best_doc, best_score

    def hybrid_match(
        self,
        query_text: str,
        query_vector: Optional[list[float]] = None,
        system_prompt: Optional[str] = None,
        alpha: float = 0.5,
        top_k: int = 10
    ) -> Tuple[str, Optional[dict], float]:
        """
        True Hybrid RAG:
        1. Dense retrieval (similitud coseno vectorial).
        2. Sparse retrieval (Okapi BM25 léxico para tokens técnicos y exactos).
        3. Reciprocal Rank Fusion (RRF k=60).
        4. Resolución de ruta con verificación TTL, boost léxico y aislamiento de System Prompt.
        """
        if len(self.doc_ids) == 0:
            return "ESCALATE_TO_CLOUD", None, 0.0

        dense_scores: Optional[np.ndarray] = None
        dense_ranks: List[str] = []

        # 1. Dense Scoring
        mat = self.matrix
        if query_vector is not None and mat is not None and self.expected_dim is not None:
            q_vec = np.array(query_vector, dtype=np.float32)
            if len(q_vec) == self.expected_dim:
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                dense_scores = np.dot(mat, q_vec)
                sorted_indices = np.argsort(-dense_scores)
                dense_ranks = [self.doc_ids[i] for i in sorted_indices]

        # 2. Sparse Okapi BM25 Scoring
        bm25_scores = self.bm25.score(query_text)
        if bm25_scores:
            sparse_ranks = [
                doc_id for doc_id, _ in sorted(
                    bm25_scores.items(),
                    key=lambda item: item[1],
                    reverse=True
                )
            ]
        else:
            sparse_ranks = []

        if not dense_ranks and not sparse_ranks:
            return "ESCALATE_TO_CLOUD", None, 0.0

        # 3. Reciprocal Rank Fusion (RRF)
        fused = reciprocal_rank_fusion(
            dense_ranks=dense_ranks,
            sparse_ranks=sparse_ranks,
            k=60,
            weight_dense=alpha,
            weight_sparse=1.0 - alpha
        )

        if not fused:
            return "ESCALATE_TO_CLOUD", None, 0.0

        best_doc_id, rrf_score = fused[0]
        best_doc = self.documents[best_doc_id]

        # Verificar expiración TTL
        exp_ts = best_doc.get("metadata", {}).get("expires_at_timestamp")
        if exp_ts and datetime.utcnow().timestamp() > exp_ts:
            logger.info(f"[VectorGuard] Documento {best_doc_id} expirado por TTL.")
            return "ESCALATE_TO_CLOUD", None, 0.0

        best_dense_score = 0.0
        if dense_scores is not None and best_doc_id in self.doc_ids:
            idx = self.doc_ids.index(best_doc_id)
            best_dense_score = float(dense_scores[idx])

        best_bm25_score = float(bm25_scores.get(best_doc_id, 0.0))

        # 4. Cálculo de Score Efectivo (con boost léxico si hay match exacto)
        if dense_scores is not None:
            effective_score = best_dense_score
            if best_bm25_score > 0:
                lexical_boost = min(0.10, (best_bm25_score / (best_bm25_score + 1.5)) * 0.10)
                effective_score = min(1.0, best_dense_score + lexical_boost)
        else:
            # Fallback puramente léxico cuando no hay embeddings disponibles
            effective_score = min(1.0, best_bm25_score / (best_bm25_score + 0.8))

        # Enriquecer resultado con métricas híbridas para auditoría
        doc_result = dict(best_doc)
        doc_result["retrieval_mode"] = "hybrid"
        doc_result["hybrid_metrics"] = {
            "rrf_score": round(rrf_score, 6),
            "dense_score": round(best_dense_score, 4),
            "bm25_score": round(best_bm25_score, 4),
            "effective_score": round(effective_score, 4)
        }

        # 5. Determinación de Ruta y Verificación de Caché
        if effective_score >= self.high_threshold:
            if doc_result.get("type") == "qa_cache":
                cached_prompt_hash = doc_result.get("metadata", {}).get("system_prompt_hash")
                if cached_prompt_hash and system_prompt is not None:
                    current_prompt_hash = self.compute_prompt_hash(system_prompt)
                    if cached_prompt_hash != current_prompt_hash:
                        return "RESOLVE_LOCAL_MED", doc_result, effective_score
                return "RESOLVE_LOCAL_HIGH", doc_result, effective_score
            else:
                return "RESOLVE_LOCAL_MED", doc_result, effective_score
        elif effective_score >= self.min_threshold:
            return "RESOLVE_LOCAL_MED", doc_result, effective_score
        else:
            return "ESCALATE_TO_CLOUD", doc_result, effective_score

    def save_to_disk(self, storage_path: str):
        """Persistencia atómica y segura en disco con array de strings para allow_pickle=False."""
        mat = self.matrix
        if mat is None or not self.doc_ids:
            return

        storage_dir = os.path.dirname(os.path.abspath(storage_path))
        os.makedirs(storage_dir, exist_ok=True)
        meta_path = storage_path.replace(".npz", "_meta.json")

        tmp_npz = os.path.join(storage_dir, f".tmp_{os.path.basename(storage_path)}")
        tmp_meta = os.path.join(storage_dir, f".tmp_{os.path.basename(meta_path)}")

        try:
            doc_ids_array = np.array(self.doc_ids, dtype=np.str_)
            np.savez_compressed(tmp_npz, matrix=mat, doc_ids=doc_ids_array)
            
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump({
                    "expected_dim": self.expected_dim,
                    "documents": self.documents,
                    "updated_at": datetime.utcnow().isoformat()
                }, f, ensure_ascii=False, indent=2)

            os.replace(tmp_npz, storage_path)
            os.replace(tmp_meta, meta_path)
        except Exception as e:
            logger.error(f"❌ Error al guardar índice atómico en disco: {e}")
            for p in (tmp_npz, tmp_meta):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            raise

    def load_from_disk(self, storage_path: str) -> bool:
        """Carga segura con allow_pickle=False y verificación rigurosa de consistencia."""
        meta_path = storage_path.replace(".npz", "_meta.json")
        if not os.path.exists(storage_path) or not os.path.exists(meta_path):
            return False

        try:
            with np.load(storage_path, allow_pickle=False) as data:
                loaded_matrix = data["matrix"]
                loaded_doc_ids = [str(x) for x in data["doc_ids"]]

            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                loaded_dim = meta.get("expected_dim")
                loaded_docs = meta.get("documents", {})

            if len(loaded_matrix) != len(loaded_doc_ids) or len(loaded_doc_ids) != len(loaded_docs):
                logger.error(f"❌ Persistencia inconsistente: {len(loaded_matrix)} vectores vs {len(loaded_doc_ids)} IDs vs {len(loaded_docs)} docs. Rechazando índice.")
                return False

            if not set(loaded_doc_ids).issubset(set(loaded_docs.keys())):
                logger.error("❌ Persistencia inconsistente: existen doc_ids en el vector que no están en documents. Rechazando índice.")
                return False

            if loaded_matrix.ndim != 2 or loaded_matrix.shape[1] != loaded_dim:
                logger.error("❌ Dimensión de matriz inconsistente con metadatos. Rechazando índice.")
                return False

            self.vectors = [loaded_matrix[i].astype(np.float32) for i in range(len(loaded_matrix))]
            self._matrix = loaded_matrix.astype(np.float32)
            self._matrix_dirty = False
            self.doc_ids = loaded_doc_ids
            self.expected_dim = loaded_dim
            self.documents = loaded_docs

            # Reconstruir índice léxico BM25 en memoria
            self.bm25 = BM25Index()
            for d_id, doc_data in self.documents.items():
                self.bm25.add_document(d_id, doc_data.get("text", ""))

            return True

        except Exception as e:
            logger.error(f"❌ Error cargando índice seguro desde disco: {e}")
            return False
