import time
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config
from .vector_guard import VectorGuard
from .local_engine import LocalEngine
from .cloud_bridge import CloudBridge
from .second_brain import SecondBrain
from .assert_evaluator import AssertEvaluator

app = FastAPI(
    title="Open Hybrid RAG Gateway",
    description="Universal Local-First AI Orchestrator with Multi-Cloud Fallback & ASSERT Quality Guard",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialización de Componentes
vector_guard = VectorGuard(
    high_threshold=config.RAG_CERTAINTY_THRESHOLD,
    min_threshold=config.RAG_MIN_THRESHOLD
)
local_engine = LocalEngine()
cloud_bridge = CloudBridge()
second_brain = SecondBrain()
assert_evaluator = AssertEvaluator()

# 🔒 Dependencia de Autenticación de API Key (Opcional)
async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if config.API_KEY:
        if not x_api_key or x_api_key != config.API_KEY:
            raise HTTPException(status_code=401, detail="API Key inválida o no proporcionada en header X-API-Key.")
    return True

# 🛑 Middleware de Tráfico y Telemetría
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

# Evento de Arranque: Carga de persistencia de vectores
@app.on_event("startup")
async def startup_event():
    loaded = vector_guard.load_from_disk(config.INDEX_STORAGE_PATH)
    if loaded:
        print(f"[🚀 Startup] Índice vectorial cargado desde disco: {len(vector_guard.doc_ids)} documentos.")
    else:
        print("[🚀 Startup] No se encontró índice previo en disco. Iniciando con base limpia.")

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
    doc_type: str = Field("document", description="'document' (RAG context) | 'qa_cache' (direct bypass)")
    metadata: Optional[dict] = None

@app.get("/")
async def health_check():
    """Endpoint de salud del servicio con diagnóstico de configuración."""
    return {
        "status": "online",
        "service": "Open Hybrid RAG Gateway",
        "privacy_mode": config.PRIVACY_MODE,
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
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/v1/ingest", dependencies=[Depends(verify_api_key)])
async def ingest_document(req: IngestRequest):
    """Indexa un documento o par QA validando dimensiones y persistiendo en disco."""
    vec = await local_engine.get_embedding(req.text)
    if not vec:
        raise HTTPException(502, "Error: No se pudo generar el embedding con el motor local.")

    doc_id = req.doc_id or f"DOC-{uuid.uuid4().hex[:8]}"
    try:
        vector_guard.add_document(
            doc_id=doc_id,
            text=req.text,
            vector=vec,
            doc_type=req.doc_type,
            metadata=req.metadata
        )
        # Guardar en disco
        vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
    except ValueError as e:
        raise HTTPException(400, f"Error de validación vectorial: {str(e)}")

    return {
        "status": "indexed",
        "doc_id": doc_id,
        "doc_type": req.doc_type,
        "vector_dims": len(vec),
        "total_documents": len(vector_guard.doc_ids)
    }

@app.post("/api/v1/orchestrate", dependencies=[Depends(verify_api_key)])
async def orchestrate(req: QueryRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Orquestador Central Determinístico:
    1. Obtiene embedding local de la query.
    2. Vector Guard evalúa certeza matemática.
    3. Resuelve en local o escala a la nube según políticas de privacidad.
    4. Persiste únicamente respuestas exitosas en el Segundo Cerebro.
    5. Opcional: Audita la respuesta con ASSERT.
    """
    t_start = time.perf_counter()
    
    # 1. Obtener embedding
    q_vec = await local_engine.get_embedding(req.query)
    
    route = "ESCALATE_TO_CLOUD"
    best_doc = None
    score = 0.0

    if q_vec and not req.force_cloud:
        route, best_doc, score = vector_guard.match(q_vec)

    # Verificar políticas de privacidad
    cloud_permitted = (config.PRIVACY_MODE != "local_only") and req.allow_cloud_fallback

    # 2. Ejecución según Ruta
    answer = None
    source = None
    success = False

    if route == "RESOLVE_LOCAL_HIGH" and best_doc and best_doc.get("type") == "qa_cache":
        # Bypass directo de QA previamente validado
        answer = best_doc["text"]
        source = "local_qa_cache_bypass"
        success = True
    elif (route in ("RESOLVE_LOCAL_MED", "RESOLVE_LOCAL_HIGH")) and best_doc:
        # Síntesis local con contexto
        context_prompt = f"[Contexto de la Base de Conocimiento]:\n{best_doc['text']}\n\n[Pregunta]:\n{req.query}"
        success, local_resp = await local_engine.generate(prompt=context_prompt, system_prompt=req.system_prompt)
        if success:
            answer = local_resp
            source = "local_llm_inference"
        else:
            # Si el modelo local falló y la nube está permitida, intentar escalamiento
            if cloud_permitted:
                cloud_ok, cloud_resp = await cloud_bridge.generate(prompt=req.query, system_instruction=req.system_prompt)
                if cloud_ok:
                    answer = cloud_resp
                    source = f"cloud_{config.CLOUD_PROVIDER}_fallback"
                    success = True
                else:
                    raise HTTPException(502, f"Fallo en Local LLM ({local_resp}) y en Cloud ({cloud_resp}).")
            else:
                raise HTTPException(503, f"Fallo en Local LLM: {local_resp} (Escalamiento a nube bloqueado por privacidad).")
    else:
        # Escalamiento Cloud
        if not cloud_permitted:
            return {
                "request_id": request.state.req_id,
                "query": req.query,
                "route_taken": "LOCAL_ABSTENTION",
                "source": "privacy_guard_abstention",
                "similarity_score": round(score, 4),
                "answer": "No se encontró evidencia suficiente en la base local y la política de privacidad prohíbe el escalamiento a la nube.",
                "second_brain_doc_id": None,
                "telemetry": {"total_latency_ms": round((time.perf_counter() - t_start) * 1000, 2), "escalated_to_cloud": False},
                "assert_audit": None
            }

        cloud_ok, cloud_resp = await cloud_bridge.generate(prompt=req.query, system_instruction=req.system_prompt)
        if not cloud_ok:
            # NUNCA guardar errores en el Segundo Cerebro
            raise HTTPException(502, f"Error en proveedor cloud ({config.CLOUD_PROVIDER}): {cloud_resp}")
        
        answer = cloud_resp
        source = f"cloud_{config.CLOUD_PROVIDER}_fallback"
        success = True

    # 3. Guardar en Segundo Cerebro ONLY si fue exitosa
    doc_id = second_brain.save_interaction(
        query=req.query,
        answer=answer,
        source=source,
        metadata={"score": score}
    )

    # Si vino de la nube y tenemos vector, agregarlo a la memoria como qa_cache para auto-aprendizaje
    if "cloud" in source and q_vec:
        try:
            vector_guard.add_document(
                doc_id=doc_id,
                text=answer,
                vector=q_vec,
                doc_type="qa_cache",
                metadata={"source": source, "query": req.query}
            )
            vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
        except Exception:
            pass

    # 4. Auditoría ASSERT (Opcional)
    eval_result = None
    if req.audit_assert:
        eval_result = await assert_evaluator.evaluate(req.query, answer, source)

    # Latencia total real que incluye almacenamiento y evaluación
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
            "escalated_to_cloud": "cloud" in source
        },
        "assert_audit": eval_result
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=config.HOST, port=config.PORT, reload=False)
