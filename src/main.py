import time
import uuid
import secrets
import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Literal, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

try:
    from . import config
    from .vector_guard import VectorGuard
    from .local_engine import LocalEngine
    from .cloud_bridge import CloudBridge
    from .second_brain import SecondBrain
    from .assert_evaluator import AssertEvaluator
    from .security import (
        SecurityHeadersMiddleware,
        RateLimitMiddleware,
        TokenBucketRateLimiter,
        PayloadSanitizer
    )
    from .telemetry import metrics_collector
except (ImportError, ValueError):
    import config
    from vector_guard import VectorGuard
    from local_engine import LocalEngine
    from cloud_bridge import CloudBridge
    from second_brain import SecondBrain
    from assert_evaluator import AssertEvaluator
    from security import (
        SecurityHeadersMiddleware,
        RateLimitMiddleware,
        TokenBucketRateLimiter,
        PayloadSanitizer
    )
    from telemetry import metrics_collector

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
rate_limiter = TokenBucketRateLimiter(
    capacity=config.RATE_LIMIT_CAPACITY,
    refill_rate=config.RATE_LIMIT_REFILL_RATE
)

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
    metrics_collector.set_gauge("indexed_documents_total", len(vector_guard.doc_ids))
    metrics_collector.set_gauge("bm25_documents_total", vector_guard.bm25.doc_count)
    yield

app = FastAPI(
    title="Open Hybrid RAG Gateway",
    description="Universal Local-First AI Orchestrator with Multi-Cloud Fallback & ASSERT Quality Guard",
    version="1.3.0",
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

# 🛡️ Endurecimiento de Seguridad HTTP y Rate Limiting
if config.RATE_LIMIT_ENABLED:
    app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)

if config.SECURITY_HEADERS_ENABLED:
    app.add_middleware(SecurityHeadersMiddleware)

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

    latency_sec = time.perf_counter() - start_time
    latency_ms = latency_sec * 1000
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Process-Time-Ms"] = f"{latency_ms:.2f}"

    metrics_collector.inc_counter(
        "http_requests_total",
        method=request.method,
        path=request.url.path,
        status=str(response.status_code)
    )
    metrics_collector.observe_duration("http_request_duration", latency_sec)
    return response

# Modelos Pydantic
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000, description="Consulta del usuario")
    system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado."
    allow_cloud_fallback: bool = Field(True, description="Permite escalamiento a la nube si local no tiene la respuesta")
    force_cloud: bool = False
    audit_assert: bool = False

    @field_validator("query")
    @classmethod
    def validate_query_safety(cls, v: str) -> str:
        return PayloadSanitizer.sanitize_text(v, field_name="query")

class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000)
    doc_id: Optional[str] = None
    doc_type: Literal["document"] = Field("document", description="Solo documentos de contexto ('document') son permitidos en ingesta pública.")
    system_prompt: Optional[str] = None
    ttl_seconds: Optional[int] = None
    metadata: Optional[dict] = None

    @field_validator("text")
    @classmethod
    def validate_text_safety(cls, v: str) -> str:
        return PayloadSanitizer.sanitize_text(v, field_name="text")

class BatchIngestRequest(BaseModel):
    documents: List[IngestRequest] = Field(..., min_items=1, max_items=1000)

@app.get("/")
@app.get("/health")
async def health_check():
    """Endpoint de salud del servicio con diagnóstico y sondeo en vivo del motor local."""
    local_alive = await local_engine.ping()
    return {
        "status": "online",
        "service": "Open Hybrid RAG Gateway",
        "privacy_mode": config.PRIVACY_MODE.value,
        "local_engine_online": local_alive,
        "indexed_documents": len(vector_guard.doc_ids),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/metrics")
async def prometheus_metrics():
    """Endpoint de telemetría y métricas en formato estándar Prometheus."""
    metrics_collector.set_gauge("indexed_documents_total", len(vector_guard.doc_ids))
    metrics_collector.set_gauge("bm25_documents_total", vector_guard.bm25.doc_count)
    return Response(
        content=metrics_collector.export_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )

@app.get("/api/v1/config", dependencies=[Depends(verify_api_key)])
async def get_system_config():
    """Detalle completo de configuración del gateway (requiere autenticación)."""
    return {
        "privacy_mode": config.PRIVACY_MODE.value,
        "host": config.HOST,
        "port": config.PORT,
        "local_engine": {
            "type": config.LOCAL_ENGINE_TYPE,
            "llm_model": config.LOCAL_LLM_MODEL,
            "embed_model": config.LOCAL_EMBED_MODEL,
            "endpoint": config.LOCAL_LLM_URL
        },
        "cloud_fallback": {
            "provider": config.CLOUD_PROVIDER,
            "model": config.CLOUD_MODEL,
            "configured": bool(config.CLOUD_API_KEY),
            "max_tokens": config.CLOUD_MAX_TOKENS
        },
        "vector_index": {
            "indexed_documents": len(vector_guard.doc_ids),
            "expected_dimensions": vector_guard.expected_dim,
            "storage_path": config.INDEX_STORAGE_PATH,
            "high_certainty_threshold": config.RAG_CERTAINTY_THRESHOLD,
            "min_retrieval_threshold": config.RAG_MIN_THRESHOLD
        }
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
            ttl_seconds=req.ttl_seconds,
            metadata=req.metadata
        )
        await asyncio.to_thread(vector_guard.save_to_disk, config.INDEX_STORAGE_PATH)
        metrics_collector.inc_counter("ingested_documents_total", doc_type=req.doc_type)
        metrics_collector.set_gauge("indexed_documents_total", len(vector_guard.doc_ids))
        metrics_collector.set_gauge("bm25_documents_total", vector_guard.bm25.doc_count)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as e:
        logger.error(f"Error persistiendo documento ingest: {e}")
        raise HTTPException(status_code=500, detail="Error de almacenamiento persistente.")

    return {
        "status": "indexed",
        "doc_id": doc_id,
        "doc_type": req.doc_type,
        "vector_dims": len(vec),
        "total_documents": len(vector_guard.doc_ids)
    }

@app.post("/api/v1/ingest/batch", dependencies=[Depends(verify_api_key)])
async def ingest_documents_batch(req: BatchIngestRequest):
    """Ingesta masiva en lote de documentos con persistencia diferida en hilo secundario."""
    prepared_docs = []
    failed_count = 0

    for doc in req.documents:
        vec = await local_engine.get_embedding(doc.text)
        if not vec:
            failed_count += 1
            continue
        
        doc_id = doc.doc_id or f"DOC-{uuid.uuid4().hex[:8]}"
        prepared_docs.append({
            "doc_id": doc_id,
            "text": doc.text,
            "vector": vec,
            "doc_type": doc.doc_type,
            "system_prompt": doc.system_prompt,
            "ttl_seconds": doc.ttl_seconds,
            "metadata": doc.metadata
        })

    added = vector_guard.add_documents_batch(prepared_docs)
    if added > 0:
        await asyncio.to_thread(vector_guard.save_to_disk, config.INDEX_STORAGE_PATH)
        metrics_collector.inc_counter("ingested_documents_total", doc_type="document", value=float(added))
        metrics_collector.set_gauge("indexed_documents_total", len(vector_guard.doc_ids))
        metrics_collector.set_gauge("bm25_documents_total", vector_guard.bm25.doc_count)

    return {
        "status": "batch_indexed",
        "total_requested": len(req.documents),
        "successfully_indexed": added,
        "failed_embeddings": failed_count,
        "total_documents_in_index": len(vector_guard.doc_ids)
    }

@app.delete("/api/v1/cache/{doc_id}", dependencies=[Depends(verify_api_key)])
async def delete_cached_document(doc_id: str):
    """Elimina un documento o par de caché del índice vectorial y persiste en disco."""
    deleted = vector_guard.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Documento '{doc_id}' no encontrado en el índice.")

    try:
        await asyncio.to_thread(vector_guard.save_to_disk, config.INDEX_STORAGE_PATH)
    except Exception as e:
        logger.error(f"Error al persistir tras eliminar: {e}")

    return {
        "status": "deleted",
        "doc_id": doc_id,
        "remaining_documents": len(vector_guard.doc_ids)
    }

@app.post("/api/v1/orchestrate")
async def orchestrate_query(req: QueryRequest, request: Request, authorized: bool = Depends(verify_api_key)):
    """
    Orquestador Universal Local-First con Escalamiento Multi-Cloud y Guardia de Calidad ASSERT.
    """
    t_start = time.perf_counter()
    storage_warning = None
    local_available = True

    # 1. Obtener Embedding de la Consulta
    vec = await local_engine.get_embedding(req.query)
    if not vec:
        local_available = False

    # 2. Evaluación de Ruta Híbrida (True Hybrid RAG: Denso + Disperso Okapi BM25 + RRF)
    route = "ESCALATE_TO_CLOUD"
    best_doc = None
    score = 0.0

    route, best_doc, score = vector_guard.hybrid_match(
        query_text=req.query,
        query_vector=vec,
        system_prompt=req.system_prompt
    )

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
            local_available = False
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
                    logger.error(f"Fallo en Cloud Fallback: {cloud_resp}")
                    raise HTTPException(
                        status_code=502,
                        detail="Error procesando la consulta en el proveedor de nube."
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
            else:
                local_available = False

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
                    logger.error(f"Fallo en Cloud: {cloud_resp}")
                    raise HTTPException(
                        status_code=502,
                        detail="Error procesando la consulta en el proveedor de nube."
                    )

    # =========================================================================
    # 3. Auditoría ASSERT y Filtrado de Caché
    # =========================================================================
    eval_result = None
    if req.audit_assert and source not in ("local_vector_cache", "local_privacy_abstention"):
        eval_result = await assert_evaluator.evaluate(req.query, answer, source)

    total_latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

    # =========================================================================
    # 4. Almacenamiento Atómico en Second Brain (Solo para respuestas nuevas)
    # =========================================================================
    doc_id = None
    if source not in ("local_vector_cache", "local_privacy_abstention"):
        try:
            doc_id = second_brain.save_interaction(
                query=req.query,
                answer=answer,
                source=source,
                latency_ms=total_latency_ms,
                metadata={"similarity_score": score, "route": route}
            )
        except Exception as e:
            logger.error(f"⚠️ Error al guardar nota Markdown en Second Brain: {e}")
            storage_warning = f"Storage warning: {str(e)}"

        should_cache = True
        if eval_result and eval_result.get("passed") is False:
            should_cache = False
            logger.info("🛑 Respuesta rechazada por ASSERT. No se incorporará al QA Cache de alta certeza.")

        if should_cache and vec and answer:
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
                await asyncio.to_thread(vector_guard.save_to_disk, config.INDEX_STORAGE_PATH)
            except Exception as e:
                logger.error(f"⚠️ Error al actualizar VectorGuard: {e}")
                if not storage_warning:
                    storage_warning = f"Vector index persistence warning: {str(e)}"

    metrics_collector.inc_counter("orchestrator_queries_total", route=route, source=source)
    if "cloud" in source:
        metrics_collector.inc_counter("cloud_escalations_total", provider=config.CLOUD_PROVIDER)

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
            "local_available": local_available,
            "storage_warning": storage_warning
        },
        "assert_audit": eval_result
    }

@app.post("/api/v1/orchestrate/stream")
async def orchestrate_query_stream(
    req: QueryRequest,
    request: Request,
    authorized: bool = Depends(verify_api_key)
):
    """
    Streaming SSE de tokens en tiempo real con True Hybrid RAG y persistencia atómica.
    Retorna Server-Sent Events (SSE) con eventos: 'meta', 'token', 'done'.
    """
    async def sse_event_generator():
        t_start = time.perf_counter()
        req_id = getattr(request.state, "req_id", f"req-{uuid.uuid4().hex[:8]}")

        # 1. Obtener Embedding de la Consulta
        vec = await local_engine.get_embedding(req.query)
        local_available = bool(vec)

        # 2. Evaluación de Ruta Híbrida
        route = "ESCALATE_TO_CLOUD"
        best_doc = None
        score = 0.0

        route, best_doc, score = vector_guard.hybrid_match(
            query_text=req.query,
            query_vector=vec,
            system_prompt=req.system_prompt
        )

        if req.force_cloud:
            route = "ESCALATE_TO_CLOUD"

        # Evento Inicial: Metadata de Ruteo
        source = "unknown"
        meta_event = {
            "request_id": req_id,
            "route_taken": route,
            "similarity_score": round(score, 4),
            "force_cloud": req.force_cloud
        }

        full_answer_tokens = []

        # =====================================================================
        # ESCENARIO A: RESOLVE_LOCAL_HIGH (QA Cache Hit)
        # =====================================================================
        if route == "RESOLVE_LOCAL_HIGH" and best_doc and best_doc.get("type") == "qa_cache":
            source = "local_vector_cache"
            meta_event["source"] = source
            yield f"event: meta\ndata: {json.dumps(meta_event, ensure_ascii=False)}\n\n"

            cached_text = best_doc["text"]
            words = cached_text.split(" ")
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                full_answer_tokens.append(token)
                yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

        # =====================================================================
        # ESCENARIO B: RESOLVE_LOCAL_MED (RAG con Contexto Local)
        # =====================================================================
        elif route == "RESOLVE_LOCAL_MED" and best_doc:
            source = "local_slm_rag"
            meta_event["source"] = source
            yield f"event: meta\ndata: {json.dumps(meta_event, ensure_ascii=False)}\n\n"

            rag_prompt = f"""Usa el siguiente contexto técnico para responder la consulta con precisión:

[CONTEXTO RECUPERADO]:
{best_doc['text']}

[CONSULTA]:
{req.query}"""

            streamed_any = False
            async for token in local_engine.generate_stream(rag_prompt, system_prompt=req.system_prompt):
                if token.startswith("LOCAL_HTTP_") or token.startswith("LOCAL_STREAM_ERROR:"):
                    break
                streamed_any = True
                full_answer_tokens.append(token)
                yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

            if not streamed_any:
                if config.PRIVACY_MODE == config.PrivacyMode.LOCAL_ONLY or not req.allow_cloud_fallback:
                    source = "local_privacy_abstention"
                    msg = "No se encontró evidencia suficiente en la base local y la política de privacidad prohíbe el escalamiento a la nube."
                    full_answer_tokens.append(msg)
                    yield f"event: token\ndata: {json.dumps({'token': msg}, ensure_ascii=False)}\n\n"
                else:
                    source = f"cloud_{config.CLOUD_PROVIDER}_fallback"
                    async for token in cloud_bridge.generate_stream(rag_prompt, system_instruction=req.system_prompt):
                        full_answer_tokens.append(token)
                        yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

        # =====================================================================
        # ESCENARIO C: ESCALATE_TO_CLOUD / Zero-Shot
        # =====================================================================
        else:
            if not req.force_cloud:
                source = "local_slm_zero_shot"
                meta_event["source"] = source
                yield f"event: meta\ndata: {json.dumps(meta_event, ensure_ascii=False)}\n\n"

                streamed_any = False
                async for token in local_engine.generate_stream(req.query, system_prompt=req.system_prompt):
                    if token.startswith("LOCAL_HTTP_") or token.startswith("LOCAL_STREAM_ERROR:"):
                        break
                    streamed_any = True
                    full_answer_tokens.append(token)
                    yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

                if not streamed_any:
                    if config.PRIVACY_MODE == config.PrivacyMode.LOCAL_ONLY or not req.allow_cloud_fallback:
                        source = "local_privacy_abstention"
                        msg = "No se encontró evidencia suficiente en la base local y la política de privacidad prohíbe el escalamiento a la nube."
                        full_answer_tokens.append(msg)
                        yield f"event: token\ndata: {json.dumps({'token': msg}, ensure_ascii=False)}\n\n"
                    else:
                        source = f"cloud_{config.CLOUD_PROVIDER}"
                        async for token in cloud_bridge.generate_stream(req.query, system_instruction=req.system_prompt):
                            full_answer_tokens.append(token)
                            yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            else:
                source = f"cloud_{config.CLOUD_PROVIDER}"
                meta_event["source"] = source
                yield f"event: meta\ndata: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
                async for token in cloud_bridge.generate_stream(req.query, system_instruction=req.system_prompt):
                    full_answer_tokens.append(token)
                    yield f"event: token\ndata: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

        final_answer = "".join(full_answer_tokens)
        total_latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

        # Auditoría ASSERT (si aplica)
        eval_result = None
        if req.audit_assert and source not in ("local_vector_cache", "local_privacy_abstention"):
            eval_result = await assert_evaluator.evaluate(req.query, final_answer, source)

        # Persistencia en Second Brain y QA Cache
        doc_id = None
        storage_warning = None
        if source not in ("local_vector_cache", "local_privacy_abstention") and final_answer:
            try:
                doc_id = second_brain.save_interaction(
                    query=req.query,
                    answer=final_answer,
                    source=source,
                    latency_ms=total_latency_ms,
                    metadata={"similarity_score": score, "route": route}
                )
            except Exception as e:
                storage_warning = f"Storage warning: {str(e)}"

            should_cache = True
            if eval_result and eval_result.get("passed") is False:
                should_cache = False

            if should_cache and vec:
                try:
                    qa_doc_id = doc_id or f"KB-{uuid.uuid4().hex[:8]}"
                    vector_guard.add_document(
                        doc_id=qa_doc_id,
                        text=final_answer,
                        vector=vec,
                        doc_type="qa_cache",
                        system_prompt=req.system_prompt,
                        metadata={"source": source, "query": req.query}
                    )
                    await asyncio.to_thread(vector_guard.save_to_disk, config.INDEX_STORAGE_PATH)
                except Exception as e:
                    if not storage_warning:
                        storage_warning = f"Vector index persistence warning: {str(e)}"

        metrics_collector.inc_counter("orchestrator_queries_total", route=route, source=source)
        if "cloud" in source:
            metrics_collector.inc_counter("cloud_escalations_total", provider=config.CLOUD_PROVIDER)

        # Evento Final: 'done'
        done_payload = {
            "answer": final_answer,
            "route_taken": route,
            "source": source,
            "similarity_score": round(score, 4),
            "second_brain_doc_id": doc_id,
            "telemetry": {
                "total_latency_ms": total_latency_ms,
                "escalated_to_cloud": "cloud" in source,
                "local_available": local_available,
                "storage_warning": storage_warning
            },
            "assert_audit": eval_result
        }
        yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=config.HOST, port=config.PORT, reload=False)
