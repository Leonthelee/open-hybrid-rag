"""
scripts/reclassify_index.py
Reclasificador Semántico del Índice Vectorial y BM25 de Open Hybrid RAG.
Aplica la taxonomía canónica DGA MOPTT a los documentos indexados,
enriquece los metadatos con categorías y tags técnicos,
y regenera el índice BM25 y la persistencia de VectorGuard.
"""
import os
import sys
import json
import time

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

# Taxonomía Oficial DGA MOPTT
TAXONOMY_RULES = [
    {
        "category": "DGA_BPM_SNIA",
        "description": "Ciclo de vida IBM BPM, Lombardi, BD_EXP SQL, Expedientes, Catastro CPA, osTicket",
        "keywords": ["bpm", "lombardi", "bd_exp", "idinstancia", "p-darh", "snia", "expt_", "osticket", "catastro", "cpa", "darh"]
    },
    {
        "category": "DGA_INFRA_AD",
        "description": "Active Directory, LDAP, Desbloqueo de cuentas, Credenciales, VPN, Windows Server",
        "keywords": ["active directory", "desbloqueo", "ldap", "dominio", "moptt", "vpn", "cuenta", "credencial", "usuario", "password", "contraseña"]
    },
    {
        "category": "CYBER_OWASP_ISO",
        "description": "Ciberseguridad, OWASP API, Hardening Docker, WSTG, MITRE, Ley 21.663, ISO 27001 / 42001",
        "keywords": ["owasp", "cyberstrike", "vulnerabilidad", "hardening", "mitre", "ley 21.663", "iso 27001", "iso 42001", "wstg", "bola", "bopla", "ssrf"]
    },
    {
        "category": "METRICS_AUDIT",
        "description": "Métricas, KPI, SLA, MTTR, Auditoría de scripts, Metodología Branching, Trazabilidad",
        "keywords": ["kpi", "sla", "mttr", "auditoria", "branching", "profiler", "rendimiento", "estadistica", "benchmark"]
    },
    {
        "category": "DGA_DEV_TOOLS",
        "description": "Herramientas de desarrollo, Cockpits, Kit Digital Gob.cl, Web Services, Toad, n8n, OCR",
        "keywords": ["cockpit", "toad", "gobcl", "n8n", "tesseract", "ocr", "glpi", "fastapi", "web service", "teams", "telegram"]
    }
]

def classify_text(doc_id: str, text: str) -> tuple[str, list[str]]:
    """Clasifica un documento en base a reglas heurísticas ponderadas y extrae tags."""
    content_lower = (doc_id + " " + text[:3000]).lower()
    scores = {}

    for rule in TAXONOMY_RULES:
        cat = rule["category"]
        score = 0
        for kw in rule["keywords"]:
            if kw in content_lower:
                score += content_lower.count(kw)
        scores[cat] = score

    # Si hay coincidencias, elegir la categoría con mayor puntuación
    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_cat = sorted_cats[0][0] if sorted_cats[0][1] > 0 else "SOPORTE_TI_GENERAL"

    # Extraer tags detectados
    detected_tags = []
    for rule in TAXONOMY_RULES:
        if rule["category"] == best_cat:
            for kw in rule["keywords"]:
                if kw in content_lower and len(detected_tags) < 6:
                    detected_tags.append(kw.upper().replace(" ", "_"))

    if not detected_tags:
        detected_tags = ["DGA", "SOPORTE"]

    return best_cat, detected_tags

def main():
    print("============================================================")
    print("🏷️  Reclasificador Semántico DGA - Open Hybrid RAG Gateway")
    print(f"📂 Archivo Índice: {config.INDEX_STORAGE_PATH}")
    print(f"🤖 Modelo LLM Asignado: {config.LOCAL_LLM_MODEL}")
    print("============================================================")

    if not os.path.exists(config.INDEX_STORAGE_PATH):
        print("❌ Error: No existe el archivo index.npz para reclasificar.")
        return

    vector_guard = VectorGuard()
    vector_guard.load_from_disk(config.INDEX_STORAGE_PATH)
    total_docs = len(vector_guard.doc_ids)
    print(f"📦 Documentos cargados para reclasificación: {total_docs}\n")

    category_counts = {}
    taxonomy_manifest = []

    for idx, doc_id in enumerate(vector_guard.doc_ids, start=1):
        doc = vector_guard.documents[doc_id]
        text = doc.get("text", "")
        
        category, tags = classify_text(doc_id, text)
        category_counts[category] = category_counts.get(category, 0) + 1

        # Inyectar metadatos enriquecidos
        if "metadata" not in doc or not isinstance(doc["metadata"], dict):
            doc["metadata"] = {}
        
        doc["metadata"]["category"] = category
        doc["metadata"]["tags"] = tags
        doc["metadata"]["classified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        doc["metadata"]["assigned_llm"] = config.LOCAL_LLM_MODEL

        # Re-indexar en BM25 incorporando tokens de categoría y tags para búsqueda léxica
        enriched_bm25_text = f"CATEGORY:{category} " + " ".join([f"TAG:{t}" for t in tags]) + "\n" + text
        vector_guard.bm25.add_document(doc_id, enriched_bm25_text)

        taxonomy_manifest.append({
            "doc_id": doc_id,
            "category": category,
            "tags": tags,
            "type": doc.get("type", "document")
        })

        print(f"[{idx:02d}/{total_docs:02d}] {doc_id[:45]:<45} -> {category} {tags[:3]}")

    # Guardar persistencia atómica en disco
    vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
    print(f"\n✅ Índice persistido exitosamente en: {config.INDEX_STORAGE_PATH}")

    # Guardar reporte de taxonomía
    report_path = os.path.join(config.SECOND_BRAIN_PATH, "taxonomy_manifest.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_documents": total_docs,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "assigned_llm": config.LOCAL_LLM_MODEL,
            "category_distribution": category_counts,
            "manifest": taxonomy_manifest
        }, f, indent=2, ensure_ascii=False)
    print(f"📄 Reporte de taxonomía guardado en: {report_path}")

    print("\n📊 Distribución por Categorías Canónicas DGA:")
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   • {cat:<20}: {count} documentos")

    print("\n============================================================")
    print("🎉 Reclasificación e Indexación Semántica Completada.")
    print("============================================================")

if __name__ == "__main__":
    main()
