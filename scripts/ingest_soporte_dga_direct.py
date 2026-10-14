import os
import sys
import time
import asyncio
import numpy as np

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

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

SOPORTE_DIR = r"C:\Users\daniel.diaz\.gemini\antigravity\scratch\Soporte_DGA"

async def main():
    print("=" * 70)
    print("🚀 INGESTA DIRECTA DE MANUALES INTERNOS DGA -> OPEN HYBRID RAG")
    print(f"📂 Origen: {SOPORTE_DIR}")
    print(f"📂 Destino Índice: {config.INDEX_STORAGE_PATH}")
    print("=" * 70)

    vg = VectorGuard()
    if os.path.exists(config.INDEX_STORAGE_PATH):
        vg.load_from_disk(config.INDEX_STORAGE_PATH)
        print(f"📦 Índice existente cargado con {len(vg.doc_ids)} documentos.")

    engine = LocalEngine()
    second_brain = SecondBrain(base_path=config.SECOND_BRAIN_PATH)

    md_files = [f for f in os.listdir(SOPORTE_DIR) if f.endswith(".md")]
    print(f"Encontradas {len(md_files)} notas Markdown para indexar/actualizar...")

    indexed = 0
    for filename in sorted(md_files):
        doc_id = os.path.splitext(filename)[0]
        filepath = os.path.join(SOPORTE_DIR, filename)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Limpiar caracteres de control no permitidos
        clean_content = "".join(ch for ch in content if ch in ("\n", "\r", "\t") or ord(ch) >= 32).strip()
        if not clean_content:
            continue

        # Si ya existe con el mismo hash o texto idéntico, actualizar de todos modos para asegurar sincronía
        t0 = time.perf_counter()
        vec = await engine.get_embedding(clean_content)
        lat_ms = (time.perf_counter() - t0) * 1000

        if not vec:
            print(f"⚠️ Error generando vector para {doc_id}")
            continue

        vg.add_document(
            doc_id=doc_id,
            text=clean_content,
            vector=vec,
            doc_type="document",
            metadata={"source": "soporte_dga_manuals", "filename": filename}
        )
        # Sincronizar copia en knowledge_base
        dest_md = os.path.join(config.SECOND_BRAIN_PATH, filename)
        with open(dest_md, "w", encoding="utf-8") as f_out:
            f_out.write(clean_content)

        indexed += 1
        print(f"  [OK] {doc_id} ({len(vec)} dims, {lat_ms:.1f} ms)")

    vg.save_to_disk(config.INDEX_STORAGE_PATH)
    print("=" * 70)
    print(f"🎉 Ingesta finalizada: {indexed} notas procesadas.")
    print(f"📊 Total acumulado en índice: {len(vg.doc_ids)} documentos.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
