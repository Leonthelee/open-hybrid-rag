import time
import uuid
import secrets
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Literal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from . import config
    from .vector_guard import VectorGuard
    from .local_engine import LocalEngine
    from .cloud_bridge import CloudBridge
    from .second_brain import SecondBrain
    from .assert_evaluator import AssertEvaluator
except (ImportError, ValueError):
    import config
    from vector_guard import VectorGuard
    from local_engine import LocalEngine
    from cloud_bridge import CloudBridge
    from second_brain import SecondBrain
    from assert_evaluator import AssertEvaluator

logger = logging.getLogger("open_hybrid_rag.main")

# Inicialización de Componentes
vector_guard = VectorGuard(
    high_threshold=config.RAG_CERTAINTY_THRESHOLD,
    min_threshold=config.RAG_MIN_THRESHOLD
)
local_engine = LocalEngine()
cloud_bridge = CloudBridge()
second_brain = SecondBrain()
assert_evaluator = AssertEvaluator()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestor de ciclo de vida del servidor (validación de seguridad y carga de persistencia)."""
    config.validate_server_security()
    logger.info(f"🚀 Iniciando Open Hybrid RAG Gateway en {config.HOST}:{config.PORT} [Modo: {config.PRIVACY_MODE.value}]")
    
    loaded = vector_guard.load_from_disk(config.INDEX_STORAGE_PATH)
    if loaded:
        logger.info(f"📂 Índice vectorial cargado desde disco: {len(vector_guard.doc_ids)} documentos.")
    else:
        logger.info("📂 Base vectorial inicializada limpia.")
    yield

app = FastAPI(
    title="Open Hybrid RAG Gateway",
    description="Universal Local-First AI Orchestrator with Multi-Cloud Fallback & ASSERT Quality Guard",
    version="1.2.0",
    lifespan=lifespan
)

# Configuración de CORS segura
cors_origins_list = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]
allow_all_origins = "*" in cors_origins_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔒 Autenticación de API Key con tiempo constante (Anti-Timing Attack)
async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if config.API_KEY:
        if not x_api_key or not secrets.compare_digest(x_api_key, config.API_KEY):
            raise HTTPException(status_code=401, detail="API Key inválida o no proporcionada en header X-API-Key.")
    return True

# 🛑 Middleware de Telemetría
@app.middleware("http")
async def traffic_telemetry_middleware(request: Request, call_next):
    req_id = f"req-{uuid.uuid4().hex[:8]}"
    start_time = time.perf_counter()
    request.state.req_id = req_id

    response = await call_next(request)

    latency_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Process-Time-Ms"] = f"{latency_ms:.2f}"
    return response

# Modelos Pydantic
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000, description="Consulta del usuario")
    system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado."
    allow_cloud_fallback: bool = Field(True, description="Permite escalamiento a la nube si local no tiene la respuesta")
    force_cloud: bool = False
    audit_assert: bool = False

class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000)
    doc_id: Optional[str] = None
    doc_type: Literal["document"] = Field("document", description="Solo documentos de contexto ('document') son permitidos en ingesta pública.")
    system_prompt: Optional[str] = None
    metadata: Optional[dict] = None

@app.get("/")
async def health_check():
    """Endpoint de salud del servicio con diagnóstico completo."""
    return {
        "status": "online",
        "service": "Open Hybrid RAG Gateway",
        "privacy_mode": config.PRIVACY_MODE.value,
        "local_engine": {
            "type": config.LOCAL_ENGINE_TYPE,
            "llm_model": config.LOCAL_LLM_MODEL,
            "embed_model": config.LOCAL_EMBED_MODEL,
            "endpoint": config.LOCAL_LLM_URL
        },
        "cloud_fallback": {
            "provider": config.CLOUD_PROVIDER,
            "model": config.CLOUD_MODEL,
            "configured": bool(config.CLOUD_API_KEY)
        },
        "vector_index": {
            "indexed_documents": len(vector_guard.doc_ids),
            "expected_dimensions": vector_guard.expected_dim,
            "storage_path": config.INDEX_STORAGE_PATH
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/v1/ingest", dependencies=[Depends(verify_api_key)])
async def ingest_document(req: IngestRequest):
    """Indexa un documento validando dimensiones y persistiendo en disco de forma segura."""
    vec = await local_engine.get_embedding(req.text)
    if not vec:
        raise HTTPException(
            status_code=503,
            detail="No se pudo generar el vector de embeddings con el motor local."
        )

    doc_id = req.doc_id or f"DOC-{uuid.uuid4().hex[:8]}"
    try:
        vector_guard.add_document(
            doc_id=doc_id,
            text=req.text,
            vector=vec,
            doc_type=req.doc_type,
            system_prompt=req.system_prompt,
            metadata=req.metadata
        )
        vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as e:
        logger.error(f"Error persistiendo documento ingest: {e}")
        raise HTTPException(status_code=500, detail=f"Error de persistencia: {str(e)}")

    return {
        "status": "indexed",
        "doc_id": doc_id,
        "doc_type": req.doc_type,
        "vector_dims": len(vec),
        "total_documents": len(vector_guard.doc_ids)
    }

@app.post("/api/v1/orchestrate")
async def orchestrate_query(req: QueryRequest, request: Request, authorized: bool = Depends(verify_api_key)):
    """
    Orquestador Universal Local-First con Escalamiento Multi-Cloud y Guardia de Calidad ASSERT.
    """
    t_start = time.perf_counter()
    storage_warning = None

    # 1. Obtener Embedding de la Consulta
    vec = await local_engine.get_embedding(req.query)
    
    # 2. Evaluación de Ruta Vectorial
    route = "ESCALATE_TO_CLOUD"
    best_doc = None
    score = 0.0

    if vec:
        route, best_doc, score = vector_guard.match(vec, system_prompt=req.system_prompt)

    if req.force_cloud:
        route = "ESCALATE_TO_CLOUD"

    answer = ""
    source = "unknown"

    # =========================================================================
    # ESCENARIO A: RESOLVE_LOCAL_HIGH (Bypass Directo de Caché Verificado)
    # =========================================================================
    if route == "RESOLVE_LOCAL_HIGH" and best_doc and best_doc.get("type") == "qa_cache":
        answer = best_doc["text"]
        source = "local_vector_cache"

    # =========================================================================
    # ESCENARIO B: RESOLVE_LOCAL_MED (RAG con Contexto Documental Local)
    # =========================================================================
    elif route == "RESOLVE_LOCAL_MED" and best_doc:
        rag_prompt = f"""Usa el siguiente contexto técnico para responder la consulta con precisión:

[CONTEXTO RECUPERADO]:
{best_doc['text']}

[CONSULTA]:
{req.query}"""

        success, local_resp = await local_engine.generate(rag_prompt, system_prompt=req.system_prompt)
        if success:
            answer = local_resp
            source = "local_slm_rag"
        else:
            if config.PRIVACY_MODE == config.PrivacyMode.LOCAL_ONLY or not req.allow_cloud_fallback:
                route = "LOCAL_ABSTENTION"
                answer = "No se encontró evidencia suficiente en la base local y la política de privacidad prohíbe el escalamiento a la nube."
                source = "local_privacy_abstention"
            else:
                logger.info(f"🔄 Fallback local falló ({local_resp}). Escalando a Cloud ({config.CLOUD_PROVIDER}).")
                cloud_success, cloud_resp = await cloud_bridge.generate(rag_prompt, system_prompt=req.system_prompt)
                if cloud_success:
                    answer = cloud_resp
                    route = "ESCALATE_TO_CLOUD_FALLBACK"
                    source = f"cloud_{config.CLOUD_PROVIDER}_fallback"
                else:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Error en inferencia local y en fallback cloud: {cloud_resp}"
                    )

    # =========================================================================
    # ESCENARIO C: ESCALATE_TO_CLOUD (Local-First Zero-Shot o Escalamiento Cloud)
    # =========================================================================
    else:
        if not req.force_cloud:
            success, local_resp = await local_engine.generate(req.query, system_prompt=req.system_prompt)
            if success:
                answer = local_resp
                route = "RESOLVE_LOCAL_ZERO_SHOT"
                source = "local_slm_zero_shot"

        if not answer:
            if config.PRIVACY_MODE == config.PrivacyMode.LOCAL_ONLY or not req.allow_cloud_fallback:
                route = "LOCAL_ABSTENTION"
                answer = "No se encontró evidencia suficiente en la base local y la política de privacidad prohíbe el escalamiento a la nube."
                source = "local_privacy_abstention"
            else:
                cloud_success, cloud_resp = await cloud_bridge.generate(req.query, system_prompt=req.system_prompt)
                if cloud_success:
                    answer = cloud_resp
                    route = "ESCALATE_TO_CLOUD"
                    source = f"cloud_{config.CLOUD_PROVIDER}"
                else:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Fallo en proveedor cloud ({config.CLOUD_PROVIDER}): {cloud_resp}"
                    )

    # =========================================================================
    # 3. Auditoría ASSERT y Filtrado de Caché
    # =========================================================================
    eval_result = None
    if req.audit_assert and source not in ("local_vector_cache", "local_privacy_abstention"):
        eval_result = await assert_evaluator.evaluate(req.query, answer, source)

    # =========================================================================
    # 4. Almacenamiento Atómico en Second Brain
    # =========================================================================
    doc_id = None
    if source not in ("local_vector_cache", "local_privacy_abstention"):
        try:
            doc_id = second_brain.save_interaction(
                query=req.query,
                answer=answer,
                source=source,
                metadata={"similarity_score": score, "route": route}
            )
        except Exception as e:
            logger.error(f"⚠️ Error al guardar nota Markdown en Second Brain: {e}")
            storage_warning = f"Storage warning: {str(e)}"

        should_cache = True
        if eval_result and eval_result.get("passed") is False:
            should_cache = False
            logger.info("🛑 Respuesta rechazada por ASSERT. No se incorporará al QA Cache de alta certeza.")

        if should_cache and vec:
            try:
                qa_doc_id = doc_id or f"KB-{uuid.uuid4().hex[:8]}"
                vector_guard.add_document(
                    doc_id=qa_doc_id,
                    text=answer,
                    vector=vec,
                    doc_type="qa_cache",
                    system_prompt=req.system_prompt,
                    metadata={"source": source, "query": req.query}
                )
                vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
            except Exception as e:
                logger.error(f"⚠️ Error al actualizar VectorGuard: {e}")
                if not storage_warning:
                    storage_warning = f"Vector index persistence warning: {str(e)}"

    total_latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

    return {
        "request_id": request.state.req_id,
        "query": req.query,
        "route_taken": route,
        "source": source,
        "similarity_score": round(score, 4),
        "answer": answer,
        "second_brain_doc_id": doc_id,
        "telemetry": {
            "total_latency_ms": total_latency_ms,
            "escalated_to_cloud": "cloud" in source,
            "storage_warning": storage_warning
        },
        "assert_audit": eval_result
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=config.HOST, port=config.PORT, reload=False)
