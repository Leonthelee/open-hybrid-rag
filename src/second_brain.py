import os
from datetime import datetime
from typing import Optional
from . import config

class SecondBrain:
    """Gestor de Ingestión Continua y Memoria en Archivos Markdown / Obsidian."""
    def __init__(self, base_path: str = config.SECOND_BRAIN_PATH):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def save_interaction(self, query: str, answer: str, source: str, metadata: Optional[dict] = None) -> str:
        """Guarda la resolución como nota Markdown estructurada."""
        doc_id = f"KB-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        file_path = os.path.join(self.base_path, f"{doc_id}.md")
        
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
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(nota_md)

        return doc_id
