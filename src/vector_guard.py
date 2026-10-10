import os
import json
import hashlib
import tempfile
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
import numpy as np

try:
    from . import config
except (ImportError, ValueError):
    import config

logger = logging.getLogger("open_hybrid_rag.vector_guard")

class VectorGuard:
    """
    Guardián Vectorial de Alta Densidad con Persistencia Transaccional,
    Aislamiento por System Prompt, TTL y Validación de Dimensiones.
    """
    def __init__(self, high_threshold: float = config.RAG_CERTAINTY_THRESHOLD, min_threshold: float = config.RAG_MIN_THRESHOLD):
        self.high_threshold = high_threshold
        self.min_threshold = min_threshold
        self.expected_dim: Optional[int] = None
        self.matrix: Optional[np.ndarray] = None
        self.doc_ids: list[str] = []
        self.documents: Dict[str, dict] = {}

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
        metadata: Optional[dict] = None
    ) -> bool:
        """Agrega o actualiza un documento validando dimensiones y estructurando metadatos de caché."""
        vec = np.array(vector, dtype=np.float32)
        if vec.ndim != 1 or len(vec) == 0 or not np.all(np.isfinite(vec)):
            raise ValueError("El vector debe ser un array unidimensional de números finitos.")

        # Validación estricta de dimensiones
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

        # Si el documento ya existe, actualizarlo en la posición existente
        if doc_id in self.documents:
            idx = self.doc_ids.index(doc_id)
            if self.matrix is not None:
                self.matrix[idx] = vec
        else:
            self.doc_ids.append(doc_id)
            if self.matrix is None:
                self.matrix = np.expand_dims(vec, axis=0)
            else:
                self.matrix = np.vstack([self.matrix, vec])

        self.documents[doc_id] = {
            "id": doc_id,
            "text": text,
            "type": doc_type,
            "created_at": datetime.utcnow().isoformat(),
            "metadata": doc_meta
        }
        return True

    def match(
        self,
        query_vector: list[float],
        system_prompt: Optional[str] = None
    ) -> Tuple[str, Optional[dict], float]:
        """
        Calcula similitud coseno ultra-rápida.
        Verifica vigencia (TTL) y compatibilidad de instrucciones (system_prompt).
        Retorna: (decision_route, best_document, best_score)
        """
        if self.matrix is None or len(self.doc_ids) == 0:
            return "ESCALATE_TO_CLOUD", None, 0.0

        q_vec = np.array(query_vector, dtype=np.float32)
        if len(q_vec) != self.expected_dim:
            return "ESCALATE_TO_CLOUD", None, 0.0

        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        scores = np.dot(self.matrix, q_vec)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_doc_id = self.doc_ids[best_idx]
        best_doc = self.documents[best_doc_id]

        # Verificar vigencia si existe expires_at
        expires_at = best_doc.get("metadata", {}).get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.utcnow() > exp_dt:
                    logger.info(f"[VectorGuard] Documento {best_doc_id} expirado. Tratando como ESCALATE_TO_CLOUD.")
                    return "ESCALATE_TO_CLOUD", None, 0.0
            except Exception:
                pass

        if best_score >= self.high_threshold:
            if best_doc.get("type") == "qa_cache":
                # Validar coherencia de instrucciones
                cached_prompt_hash = best_doc.get("metadata", {}).get("system_prompt_hash")
                if cached_prompt_hash and system_prompt is not None:
                    current_prompt_hash = self.compute_prompt_hash(system_prompt)
                    if cached_prompt_hash != current_prompt_hash:
                        # Si cambiaron las instrucciones, degradar a contexto sin bypass directo
                        return "RESOLVE_LOCAL_MED", best_doc, best_score
                return "RESOLVE_LOCAL_HIGH", best_doc, best_score
            else:
                return "RESOLVE_LOCAL_MED", best_doc, best_score
        elif best_score >= self.min_threshold:
            return "RESOLVE_LOCAL_MED", best_doc, best_score
        else:
            return "ESCALATE_TO_CLOUD", best_doc, best_score

    def save_to_disk(self, storage_path: str):
        """Persistencia atómica y transaccional en disco."""
        if self.matrix is None or not self.doc_ids:
            return

        storage_dir = os.path.dirname(os.path.abspath(storage_path))
        os.makedirs(storage_dir, exist_ok=True)
        meta_path = storage_path.replace(".npz", "_meta.json")

        tmp_npz = os.path.join(storage_dir, f".tmp_{os.path.basename(storage_path)}")
        tmp_meta = os.path.join(storage_dir, f".tmp_{os.path.basename(meta_path)}")

        try:
            np.savez_compressed(tmp_npz, matrix=self.matrix, doc_ids=np.array(self.doc_ids))
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump({
                    "expected_dim": self.expected_dim,
                    "documents": self.documents,
                    "updated_at": datetime.utcnow().isoformat()
                }, f, ensure_ascii=False, indent=2)

            # Reemplazo atómico de ambos archivos
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
        """Carga transaccional desde disco con validación de consistencia total."""
        meta_path = storage_path.replace(".npz", "_meta.json")
        if not os.path.exists(storage_path) or not os.path.exists(meta_path):
            return False

        try:
            # 1. Carga preliminar
            data = np.load(storage_path, allow_pickle=True)
            loaded_matrix = data["matrix"]
            loaded_doc_ids = list(data["doc_ids"])

            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                loaded_dim = meta.get("expected_dim")
                loaded_docs = meta.get("documents", {})

            # 2. Validación de consistencia transaccional
            if len(loaded_matrix) != len(loaded_doc_ids) or len(loaded_doc_ids) != len(loaded_docs):
                logger.error("❌ Persistencia inconsistente: el número de vectores no coincide con documentos. Abortando carga.")
                return False

            if loaded_matrix.ndim != 2 or loaded_matrix.shape[1] != loaded_dim:
                logger.error("❌ Dimensión de matriz inconsistente con metadatos. Abortando carga.")
                return False

            # 3. Asignación atómica en memoria
            self.matrix = loaded_matrix
            self.doc_ids = loaded_doc_ids
            self.expected_dim = loaded_dim
            self.documents = loaded_docs
            return True

        except Exception as e:
            logger.error(f"❌ Error cargando índice desde disco: {e}")
            return False
