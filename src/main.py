import time
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .vector_guard import VectorGuard
from .local_engine import LocalEngine
from .cloud_bridge import CloudBridge
from .second_brain import SecondBrain
from .assert_evaluator import AssertEvaluator

app = FastAPI(
    title="Open Hybrid RAG Gateway",
    description="Universal Local-First AI Orchestrator with Google Gemini Fallback & ASSERT Quality Guard",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Componentes del Sistema
vector_guard = VectorGuard(
    high_threshold=config.RAG_CERTAINTY_THRESHOLD,
    min_threshold=config.RAG_MIN_THRESHOLD
)
local_engine = LocalEngine()
cloud_bridge = CloudBridge()
second_brain = SecondBrain()
assert_evaluator = AssertEvaluator()

# 🛑 MIDDLEWARE DE TRÁFICO Y TELEMETRÍA
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
    query: str
    system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado."
    force_cloud: bool = False
    audit_assert: bool = False

class IngestRequest(BaseModel):
    text: str
    doc_id: Optional[str] = None
    metadata: Optional[dict] = None

@app.get("/")
async def health_check():
    return {
        "status": "online",
        "service": "Open Hybrid RAG Gateway",
        "local_llm": config.LOCAL_LLM_MODEL,
        "local_embed": config.LOCAL_EMBED_MODEL,
        "cloud_llm": config.GEMINI_MODEL,
        "indexed_vectors": len(vector_guard.vectors),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/v1/ingest")
async def ingest_document(req: IngestRequest):
    """Indexa un fragmento de conocimiento en caliente en el Vector Guard."""
    vec = await local_engine.get_embedding(req.text)
    if not vec:
        raise HTTPException(502, "No se pudo generar el vector con el modelo de embeddings local.")
    
    doc_id = req.doc_id or f"DOC-{uuid.uuid4().hex[:6]}"
    vector_guard.add_document(
        doc_id=doc_id,
        text=req.text,
        vector=vec,
        metadata=req.metadata
    )
    return {"status": "indexed", "doc_id": doc_id, "vector_dims": len(vec)}

@app.post("/api/v1/orchestrate")
async def orchestrate(req: QueryRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Orquestador Central:
    1. Vectoriza la consulta.
    2. Vector Guard evalúa certeza matemática.
    3. Si es alta -> Resuelve en local (0ms nube, $0 costo).
    4. Si hay duda -> Escala a Google Gemini en la nube.
    5. Ingesta automáticamente la solución en el Segundo Cerebro.
    """
    t0 = time.perf_counter()
    
    # 1. Obtener embedding de la query
    q_vec = await local_engine.get_embedding(req.query)
    
    route = "ESCALATE_TO_CLOUD"
    best_doc = None
    score = 0.0

    if q_vec and not req.force_cloud:
        route, best_doc, score = vector_guard.match(q_vec)

    # 2. Decisión de Ejecución
    if route == "RESOLVE_LOCAL_HIGH" and best_doc:
        answer = best_doc["text"]
        source = "local_vector_cache_bypass"
    elif route == "RESOLVE_LOCAL_MED" and best_doc:
        context_prompt = f"[Contexto Recuperado]: {best_doc['text']}\n\n[Pregunta]: {req.query}"
        answer = await local_engine.generate(prompt=context_prompt, system_prompt=req.system_prompt)
        source = "local_llm_inference"
    else:
        # Escalamiento Cloud (Google Gemini)
        answer = await cloud_bridge.generate(prompt=req.query, system_instruction=req.system_prompt)
        source = "cloud_gemini_fallback"

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    # 3. Guardar en Segundo Cerebro (Obsidian / Markdown)
    doc_id = second_brain.save_interaction(
        query=req.query,
        answer=answer,
        source=source,
        metadata={"latency_ms": latency_ms, "score": score}
    )

    # Si vino de la nube, agregarlo a los vectores en memoria para auto-aprendizaje
    if source == "cloud_gemini_fallback" and q_vec:
        vector_guard.add_document(doc_id=doc_id, text=answer, vector=q_vec, metadata={"source": source})

    # 4. Evaluación opcional ASSERT
    eval_result = None
    if req.audit_assert:
        eval_result = await assert_evaluator.evaluate(req.query, answer, source)

    return {
        "request_id": request.state.req_id,
        "query": req.query,
        "route_taken": route,
        "source": source,
        "similarity_score": round(score, 4),
        "answer": answer,
        "second_brain_doc_id": doc_id,
        "telemetry": {
            "total_latency_ms": latency_ms,
            "escalated_to_cloud": source == "cloud_gemini_fallback"
        },
        "assert_audit": eval_result
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=config.HOST, port=config.PORT, reload=False)
