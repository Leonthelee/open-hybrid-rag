"""
src/bm25.py
Motor BM25 Nativo (Okapi BM25) y Fusión de Rango Recíproco (RRF).
Implementa búsqueda dispersa (lexical search) en memoria para coincidencia
exacta de términos técnicos, códigos de error (HTTP 422, BOPLA), IDs y variables,
combinándose con vectores densos para Hybrid RAG Real.
"""
import re
import math
from typing import List, Dict, Tuple, Optional
from collections import Counter

class BM25Index:
    """
    Índice BM25 ligero y puro en Python (sin dependencias externas).
    Parámetros Okapi estándar: k1=1.5, b=0.75.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_lengths: Dict[str, int] = {}
        self.doc_tokens: Dict[str, Counter] = {}
        self.doc_count: int = 0
        self.avg_doc_length: float = 0.0
        # Frecuencia de documentos por término: n(t)
        self.doc_freqs: Dict[str, int] = Counter()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """
        Tokenizador técnico: preserva identificadores, códigos de error con guiones,
        números y dos puntos (ej. 'API3:2023', 'HTTP_422', 'M1042', 'test.py'),
        removiendo puntuación periférica (puntos finales de oración, comas, etc.).
        """
        if not text:
            return []
        raw_tokens = re.findall(r"[a-zA-Z0-9_:\.\-]+", text.lower())
        tokens = []
        for t in raw_tokens:
            cleaned = t.strip(".:,;!?()[]{}'\"")
            if len(cleaned) > 1 or cleaned.isdigit():
                tokens.append(cleaned)
        return tokens

    def add_document(self, doc_id: str, text: str):
        """Agrega o reemplaza un documento en el índice léxico."""
        if doc_id in self.doc_tokens:
            self.delete_document(doc_id)

        tokens = self.tokenize(text)
        token_counts = Counter(tokens)
        doc_len = len(tokens)

        self.doc_tokens[doc_id] = token_counts
        self.doc_lengths[doc_id] = doc_len
        self.doc_count += 1

        for term in token_counts.keys():
            self.doc_freqs[term] += 1

        total_length = sum(self.doc_lengths.values())
        self.avg_doc_length = total_length / self.doc_count if self.doc_count > 0 else 0.0

    def add_documents_batch(self, docs: List[Dict[str, str]]):
        """Ingesta masiva de documentos en el índice léxico."""
        for d in docs:
            self.add_document(d["doc_id"], d["text"])

    def delete_document(self, doc_id: str) -> bool:
        """Elimina un documento y recalcula estadísticas globales de BM25."""
        if doc_id not in self.doc_tokens:
            return False

        old_counts = self.doc_tokens.pop(doc_id)
        self.doc_lengths.pop(doc_id, None)
        self.doc_count -= 1

        for term in old_counts.keys():
            self.doc_freqs[term] -= 1
            if self.doc_freqs[term] <= 0:
                del self.doc_freqs[term]

        total_length = sum(self.doc_lengths.values())
        self.avg_doc_length = total_length / self.doc_count if self.doc_count > 0 else 0.0
        return True

    def _idf(self, term: str) -> float:
        """Calcula Inverse Document Frequency con suavizado probabilístico."""
        n_t = self.doc_freqs.get(term, 0)
        if n_t == 0:
            return 0.0
        # Fórmula Okapi BM25 estándar
        return math.log(1.0 + (self.doc_count - n_t + 0.5) / (n_t + 0.5))

    def score(self, query: str) -> Dict[str, float]:
        """Calcula el puntaje BM25 para todos los documentos que coincidan con la consulta."""
        query_tokens = self.tokenize(query)
        if not query_tokens or self.doc_count == 0:
            return {}

        scores: Dict[str, float] = {}

        for doc_id, token_counts in self.doc_tokens.items():
            doc_len = self.doc_lengths[doc_id]
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_length if self.avg_doc_length > 0 else 1.0)
            doc_score = 0.0

            for q_term in query_tokens:
                f_td = token_counts.get(q_term, 0)
                if f_td > 0:
                    idf = self._idf(q_term)
                    # Saturación de frecuencia de término Okapi
                    num = f_td * (self.k1 + 1.0)
                    denom = f_td + self.k1 * len_norm
                    doc_score += idf * (num / denom)

            if doc_score > 0:
                scores[doc_id] = doc_score

        return scores

    def rank(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Devuelve los top_k documentos ordenados por relevancia BM25."""
        scores = self.score(query)
        sorted_docs = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return sorted_docs[:top_k]


def reciprocal_rank_fusion(
    dense_ranks: List[str],
    sparse_ranks: List[str],
    k: int = 60,
    weight_dense: float = 0.5,
    weight_sparse: float = 0.5
) -> List[Tuple[str, float]]:
    """
    Fusión de Rango Recíproco (RRF - Cormack et al.).
    Combina rankings de diferente escala (vectores continuos vs scores BM25)
    garantizando que documentos que ranqueen alto en cualquiera de los dos
    o en ambos ganen la máxima prioridad.
    """
    rrf_scores: Dict[str, float] = {}

    for rank, doc_id in enumerate(dense_ranks):
        score = weight_dense / (k + (rank + 1))
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + score

    for rank, doc_id in enumerate(sparse_ranks):
        score = weight_sparse / (k + (rank + 1))
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + score

    sorted_fused = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    return sorted_fused
