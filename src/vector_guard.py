import os
import json
import numpy as np
from typing import Optional, Tuple, Dict, Any

class VectorGuard:
    """
    Guardián Vectorial de Alta Densidad con Persistencia en Disco,
    Validación de Dimensiones y Enrutamiento Matemático Determinístico.
    """
    def __init__(self, high_threshold: float = 0.85, min_threshold: float = 0.65):
        self.high_threshold = high_threshold
        self.min_threshold = min_threshold
        self.expected_dim: Optional[int] = None
        self.matrix: Optional[np.ndarray] = None  # Matriz NumPy cacheada para velocidad
        self.doc_ids: list[str] = []
        self.documents: Dict[str, dict] = {}     # doc_id -> {text, metadata, type: 'document' | 'qa_cache'}

    def add_document(
        self,
        doc_id: str,
        text: str,
        vector: list[float],
        doc_type: str = "document",
        metadata: Optional[dict] = None
    ) -> bool:
        """Agrega o actualiza un documento validando dimensiones y evitando duplicados."""
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
            "metadata": metadata or {}
        }
        return True

    def match(self, query_vector: list[float]) -> Tuple[str, Optional[dict], float]:
        """
        Calcula similitud coseno ultra-rápida.
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

        # Producto punto matricial normalizado en C (NumPy)
        scores = np.dot(self.matrix, q_vec)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_doc_id = self.doc_ids[best_idx]
        best_doc = self.documents[best_doc_id]

        if best_score >= self.high_threshold:
            # Si es un QA cache verificado, permite bypass directo; si es documento, pasa a síntesis
            if best_doc.get("type") == "qa_cache":
                return "RESOLVE_LOCAL_HIGH", best_doc, best_score
            else:
                return "RESOLVE_LOCAL_MED", best_doc, best_score
        elif best_score >= self.min_threshold:
            return "RESOLVE_LOCAL_MED", best_doc, best_score
        else:
            return "ESCALATE_TO_CLOUD", best_doc, best_score

    def save_to_disk(self, storage_path: str):
        """Persiste el índice vectorial y la metadata en disco."""
        if self.matrix is None or not self.doc_ids:
            return
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        meta_path = storage_path.replace(".npz", "_meta.json")

        np.savez_compressed(storage_path, matrix=self.matrix, doc_ids=np.array(self.doc_ids))
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "expected_dim": self.expected_dim,
                "documents": self.documents
            }, f, ensure_ascii=False, indent=2)

    def load_from_disk(self, storage_path: str) -> bool:
        """Carga el índice desde disco al arrancar el servicio."""
        meta_path = storage_path.replace(".npz", "_meta.json")
        if not os.path.exists(storage_path) or not os.path.exists(meta_path):
            return False
        try:
            data = np.load(storage_path, allow_pickle=True)
            self.matrix = data["matrix"]
            self.doc_ids = list(data["doc_ids"])

            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                self.expected_dim = meta.get("expected_dim")
                self.documents = meta.get("documents", {})
            return True
        except Exception as e:
            print(f"[⚠️ VectorGuard] Error cargando índice desde disco: {e}")
            return False
