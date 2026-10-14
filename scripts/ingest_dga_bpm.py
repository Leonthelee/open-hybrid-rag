"""
scripts/ingest_dga_bpm.py
Ingesta y sincronización de las reglas de negocio de DGA-BPM
(BD_EXP SQL, IBM BPM REST, y Procedimientos SNIA / osTicket)
hacia el índice vectorial y BM25 de Open Hybrid RAG Gateway.
"""
import os
import sys
import time
import asyncio
import httpx

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
src_dir = os.path.join(ROOT_DIR, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import config
from vector_guard import VectorGuard
from local_engine import LocalEngine
from second_brain import SecondBrain

KNOWLEDGE_SOURCE_DIR = r"C:\Users\daniel.diaz\.gemini\antigravity\scratch\dga-bpm-orchestrator\backend\knowledge"

async def main():
    print("============================================================")
    print("🚀 Ingesta Directa: DGA BPM Orchestrator Knowledge -> Open Hybrid RAG")
    print(f"📂 Carpeta Origen: {KNOWLEDGE_SOURCE_DIR}")
    print("============================================================")

    if not os.path.isdir(KNOWLEDGE_SOURCE_DIR):
        print(f"❌ Error: La carpeta {KNOWLEDGE_SOURCE_DIR} no existe.")
        return

    md_files = [f for f in os.listdir(KNOWLEDGE_SOURCE_DIR) if f.endswith(".md")]
    print(f"📦 Encontrados {len(md_files)} archivos de reglas:")
    for f in md_files:
        print(f"   - {f}")

    local_engine = LocalEngine()
    second_brain = SecondBrain(base_path=config.SECOND_BRAIN_PATH)
    vector_guard = VectorGuard()

    # Cargar persistencia previa para no sobreescribir los existentes
    if os.path.exists(config.INDEX_STORAGE_PATH):
        vector_guard.load_from_disk(config.INDEX_STORAGE_PATH)
        print(f"📂 Índice previo cargado con {len(vector_guard.doc_ids)} documentos.")

    print(f"\n⚙️ Vectorizando con modelo local '{config.LOCAL_EMBED_MODEL}' ({config.LOCAL_EMBED_URL})...")

    prepared_docs = []
    for filename in sorted(md_files):
        filepath = os.path.join(KNOWLEDGE_SOURCE_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()

        doc_id = f"dga-bpm-{os.path.splitext(filename)[0]}"
        print(f"   Generando vector para: {doc_id} ({len(content)} caracteres)...")

        t0 = time.perf_counter()
        vec = await local_engine.get_embedding(content)
        elapsed = (time.perf_counter() - t0) * 1000

        if not vec:
            print(f"   ⚠️ Falló embedding para {doc_id}")
            continue

        print(f"   ✓ Vector obtenido ({len(vec)} dims) en {elapsed:.2f} ms")
        prepared_docs.append({
            "doc_id": doc_id,
            "text": content,
            "vector": vec,
            "doc_type": "document",
            "metadata": {
                "source": "dga-bpm-orchestrator",
                "filename": filename
            }
        })

        # Guardar nota en segundo cerebro
        second_brain.save_interaction(
            query=f"Especificación canónica y reglas para {doc_id}",
            answer=content,
            source="dga_bpm_orchestrator",
            latency_ms=elapsed
        )

    # Ingestar en VectorGuard y persistir en disco
    count = vector_guard.add_documents_batch(prepared_docs)
    vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
    print(f"\n✅ Total documentos DGA indexados y guardados: {count}")
    print(f"📂 Total general en el índice VectorGuard: {len(vector_guard.doc_ids)} documentos")

    # Pruebas de recuperación
    print("\n🔍 Verificando recuperación con consultas reales DGA:")
    queries = [
        "¿En qué tabla de BD_EXP busco el IdInstancia de un expediente NR-0601-4573?",
        "¿Cuáles son los pasos y métodos HTTP para purgar un proceso en IBM BPM Lombardi?",
        "¿Cuál es la plantilla oficial para responder al solicitante en osTicket?"
    ]

    for q in queries:
        print(f"\nQuery: '{q}'")
        t0 = time.perf_counter()
        q_vec = await local_engine.get_embedding(q)
        embed_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        route, doc, score = vector_guard.hybrid_match(query_text=q, query_vector=q_vec)
        match_ms = (time.perf_counter() - t1) * 1000

        print(f"   Ruta: {route} | Score: {score:.4f}")
        print(f"   Latencia Embedding: {embed_ms:.2f} ms | Búsqueda Matricial: {match_ms:.3f} ms")
        if doc:
            print(f"   Doc Recuperado: {doc.get('id') or doc.get('doc_id')}")
            preview = doc['text'].splitlines()[0:3]
            print(f"   Preview: {' / '.join(preview)}")

    print("\n============================================================")
    print("🎉 Ingesta y Verificación de Reglas DGA BPM Completada con Éxito.")
    print("============================================================")

if __name__ == "__main__":
    asyncio.run(main())
