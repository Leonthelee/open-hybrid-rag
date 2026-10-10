import numpy as np
from typing import Optional, Tuple

class VectorGuard:
    """Evaluador y Guardián Matemático de Vectores para Enrutamiento RAG."""
    def __init__(self, high_threshold: float = 0.85, min_threshold: float = 0.65):
        self.high_threshold = high_threshold
        self.min_threshold = min_threshold
        self.vectors: list[np.ndarray] = []
        self.documents: list[dict] = []

    def add_document(self, doc_id: str, text: str, vector: list[float], metadata: Optional[dict] = None):
        vec = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        self.vectors.append(vec)
        self.documents.append({
            "id": doc_id,
            "text": text,
            "metadata": metadata or {}
        })

    def match(self, query_vector: list[float]) -> Tuple[str, Optional[dict], float]:
        """
        Calcula similitud coseno contra todos los vectores en memoria.
        Retorna: (decision_route, best_document, best_score)
        """
        if not self.vectors:
            return "ESCALATE_TO_CLOUD", None, 0.0

        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        matrix = np.vstack(self.vectors)
        scores = np.dot(matrix, q_vec)
        
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_doc = self.documents[best_idx]

        if best_score >= self.high_threshold:
            return "RESOLVE_LOCAL_HIGH", best_doc, best_score
        elif best_score >= self.min_threshold:
            return "RESOLVE_LOCAL_MED", best_doc, best_score
        else:
            return "ESCALATE_TO_CLOUD", best_doc, best_score
