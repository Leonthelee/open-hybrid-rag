import os
import uuid
import tempfile
import logging
from datetime import datetime
from typing import Optional

try:
    from . import config
except (ImportError, ValueError):
    import config

logger = logging.getLogger("open_hybrid_rag.second_brain")

class SecondBrain:
    """Gestor de Ingestión Continua y Memoria con Escritura Atómica y Permisos Seguros."""
    def __init__(self, base_path: str = config.SECOND_BRAIN_PATH):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def save_interaction(
        self,
        query: str,
        answer: str,
        source: str,
        latency_ms: float = 0.0,
        metadata: Optional[dict] = None
    ) -> str:
        """Guarda la resolución como nota Markdown estructurada de forma atómica y con permisos 0o644."""
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")[:19]
        unique_id = uuid.uuid4().hex[:6]
        doc_id = f"KB-{timestamp}-{unique_id}"
        
        target_file = os.path.join(self.base_path, f"{doc_id}.md")
        meta = dict(metadata or {})

        nota_md = f"""---
id: {doc_id}
date: {datetime.utcnow().isoformat()}Z
source: {source}
latency_ms: {latency_ms}
score: {meta.get('similarity_score', 0.0)}
tags: [open-hybrid-rag, second-brain, auto-learned]
---

# 📖 Interacción Documentada — {doc_id}

### ❓ Consulta Original
{query}

### 💡 Solución Generada / Verificada
{answer}

---
*Persistido automáticamente por Open Hybrid RAG Gateway.*
"""
        dir_name = os.path.dirname(target_file)
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
            tmp.write(nota_md)
            tmp_path = tmp.name

        try:
            os.chmod(tmp_path, 0o644)
        except Exception:
            pass

        os.replace(tmp_path, target_file)
        return doc_id
