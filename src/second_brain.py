import os
import uuid
import tempfile
from datetime import datetime
from typing import Optional
try:
    from . import config
except (ImportError, ValueError):
    import config

class SecondBrain:
    """Gestor de Ingestión Continua y Memoria con Escritura Atómica y UUID Anti-Colisión."""
    def __init__(self, base_path: str = config.SECOND_BRAIN_PATH):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def save_interaction(self, query: str, answer: str, source: str, metadata: Optional[dict] = None) -> str:
        """Guarda la resolución como nota Markdown estructurada de forma atómica."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:19]
        unique_id = uuid.uuid4().hex[:6]
        doc_id = f"KB-{timestamp}-{unique_id}"
        
        target_file = os.path.join(self.base_path, f"{doc_id}.md")
        meta = metadata or {}

        nota_md = f"""---
id: {doc_id}
date: {datetime.now().isoformat()}
source: {source}
latency_ms: {meta.get('latency_ms', 0)}
score: {meta.get('score', 0.0)}
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
        # Escritura atómica para evitar corrupción de archivos concurrentes
        dir_name = os.path.dirname(target_file)
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
            tmp.write(nota_md)
            tmp_path = tmp.name

        os.replace(tmp_path, target_file)
        return doc_id
