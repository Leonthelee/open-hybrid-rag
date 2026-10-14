"""
sdk/client.py
SDK Ligero y Resiliente en Python para Open Hybrid RAG Gateway.
Soporte completo Síncrono y Asíncrono con:
- Manejo determinista de HTTP 429 Too Many Requests respetando la cabecera 'Retry-After' con jitter.
- Reintentos con retroceso exponencial (Exponential Backoff) ante errores 502/503/504 de red.
- Modelos estructurados para respuestas y telemetría.
- Inyección de cabeceras de seguridad y trazabilidad (X-API-Key, X-Request-ID).
"""
import time
import random
import logging
import json
from typing import Optional, Dict, Any, List, Union, Iterator, AsyncIterator
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger("open_hybrid_rag.sdk")

# ==============================================================================
# Excepciones del SDK
# ==============================================================================

class OpenHybridRAGException(Exception):
    """Excepción base del SDK."""
    pass

class APIError(OpenHybridRAGException):
    """Error devuelto por la API HTTP (4xx o 5xx)."""
    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}

class RateLimitError(APIError):
    """Excepción lanzada cuando se supera la cuota (HTTP 429) y se agotan los reintentos."""
    def __init__(self, retry_after: float, message: str, payload: Optional[dict] = None):
        super().__init__(429, message, payload)
        self.retry_after = retry_after

# ==============================================================================
# Modelos de Datos (Respuestas)
# ==============================================================================

@dataclass
class QueryResponse:
    request_id: str
    query: str
    route_taken: str
    source: str
    similarity_score: float
    answer: str
    second_brain_doc_id: Optional[str] = None
    telemetry: Dict[str, Any] = field(default_factory=dict)
    assert_audit: Optional[Dict[str, Any]] = None
    retries_made: int = 0

@dataclass
class IngestResponse:
    status: str
    doc_id: str
    doc_type: str
    vector_dims: int
    total_documents: int

@dataclass
class BatchIngestResponse:
    status: str
    total_requested: int
    successfully_indexed: int
    failed_embeddings: int
    total_documents_in_index: int

# ==============================================================================
# Cliente Síncrono
# ==============================================================================

class OpenHybridRAGClient:
    """
    Cliente Síncrono de alto rendimiento para Open Hybrid RAG Gateway.
    """
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        api_key: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
        app: Optional[Any] = None
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenHybridRAG-SDK/1.3.0-Python"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        if app is not None:
            # Compatibilidad directa in-memory para testing síncrono contra FastAPI / Starlette
            from starlette.testclient import TestClient
            self._client = TestClient(app, base_url=self.base_url, headers=headers)
        elif transport is not None:
            self._client = httpx.Client(transport=transport, base_url=self.base_url, headers=headers, timeout=self.timeout)
        else:
            self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout)

    def close(self):
        if hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _execute_with_retry(self, method: str, path: str, json_data: Optional[dict] = None) -> Tuple[httpx.Response, int]:
        retries = 0
        while True:
            try:
                response = self._client.request(method=method, url=path, json=json_data)
                
                # Manejo de Rate Limiting (HTTP 429)
                if response.status_code == 429:
                    raw_retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = float(raw_retry_after) if raw_retry_after else 1.0
                    except (ValueError, TypeError):
                        retry_after = 1.0

                    if retries >= self.max_retries:
                        payload = response.json() if "json" in response.headers.get("content-type", "") else {}
                        raise RateLimitError(
                            retry_after=retry_after,
                            message=f"Límite de tasa excedido tras {retries} reintentos. Retry-After: {retry_after}s",
                            payload=payload
                        )

                    # Jitter aleatorio (+10% a +25%) para evitar efecto manada (thundering herd)
                    sleep_time = retry_after + random.uniform(0.05, 0.25)
                    logger.warning(f"⚠️ [SDK] HTTP 429 detectado. Esperando {sleep_time:.2f}s (reintento {retries + 1}/{self.max_retries})...")
                    time.sleep(sleep_time)
                    retries += 1
                    continue

                # Manejo de Errores Transitorios de Servidor (502, 503, 504)
                if response.status_code in (502, 503, 504) and retries < self.max_retries:
                    sleep_time = (self.backoff_factor * (2 ** retries)) + random.uniform(0.05, 0.15)
                    logger.warning(f"⚠️ [SDK] Error transitorio {response.status_code}. Reintentando en {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                    retries += 1
                    continue

                return response, retries

            except (httpx.ConnectError, httpx.TimeoutException) as net_err:
                if retries >= self.max_retries:
                    raise OpenHybridRAGException(f"Fallo de conexión tras {retries} reintentos: {net_err}")
                sleep_time = (self.backoff_factor * (2 ** retries)) + random.uniform(0.05, 0.15)
                logger.warning(f"⚠️ [SDK] Error de red ({net_err}). Reintentando en {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                retries += 1

    def health(self) -> Dict[str, Any]:
        """Consulta el estado del servicio y del motor local."""
        resp, _ = self._execute_with_retry("GET", "/health")
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)
        return resp.json()

    def get_metrics(self) -> str:
        """Obtiene las métricas de telemetría en formato estándar Prometheus."""
        resp, _ = self._execute_with_retry("GET", "/metrics")
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)
        return resp.text

    def get_config(self) -> Dict[str, Any]:
        """Obtiene la configuración y estado de umbrales del Gateway (requiere auth)."""
        resp, _ = self._execute_with_retry("GET", "/api/v1/config")
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)
        return resp.json()

    def query(
        self,
        prompt: str,
        system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado.",
        allow_cloud_fallback: bool = True,
        force_cloud: bool = False,
        audit_assert: bool = False
    ) -> QueryResponse:
        """
        Envía una consulta al orquestador True Hybrid RAG con reintento automático ante HTTP 429.
        """
        payload = {
            "query": prompt,
            "system_prompt": system_prompt,
            "allow_cloud_fallback": allow_cloud_fallback,
            "force_cloud": force_cloud,
            "audit_assert": audit_assert
        }
        resp, retries = self._execute_with_retry("POST", "/api/v1/orchestrate", json_data=payload)
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)

        data = resp.json()
        return QueryResponse(
            request_id=data.get("request_id", ""),
            query=data.get("query", prompt),
            route_taken=data.get("route_taken", "UNKNOWN"),
            source=data.get("source", "unknown"),
            similarity_score=data.get("similarity_score", 0.0),
            answer=data.get("answer", ""),
            second_brain_doc_id=data.get("second_brain_doc_id"),
            telemetry=data.get("telemetry", {}),
            assert_audit=data.get("assert_audit"),
            retries_made=retries
        )

    def stream_query(
        self,
        prompt: str,
        system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado.",
        allow_cloud_fallback: bool = True,
        force_cloud: bool = False,
        audit_assert: bool = False
    ) -> Iterator[Dict[str, Any]]:
        """
        Envía una consulta con streaming Server-Sent Events (SSE) en tiempo real.
        Genera diccionarios estructurados: {'event': 'meta'|'token'|'done', 'data': {...}}
        """
        payload = {
            "query": prompt,
            "system_prompt": system_prompt,
            "allow_cloud_fallback": allow_cloud_fallback,
            "force_cloud": force_cloud,
            "audit_assert": audit_assert
        }
        resp = self._client.post("/api/v1/orchestrate/stream", json=payload)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 1.0))
            time.sleep(retry_after + random.uniform(0.05, 0.25))
            resp = self._client.post("/api/v1/orchestrate/stream", json=payload)

        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)

        current_event = None
        for line in resp.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            line = line.strip()
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                raw_data = line[6:].strip()
                try:
                    data = json.loads(raw_data)
                except Exception:
                    data = raw_data
                yield {"event": current_event or "message", "data": data}

    def ingest(
        self,
        text: str,
        doc_id: Optional[str] = None,
        doc_type: str = "document",
        system_prompt: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[dict] = None
    ) -> IngestResponse:
        """Indexa un documento individual en la base vectorial y léxica."""
        payload = {
            "text": text,
            "doc_id": doc_id,
            "doc_type": doc_type,
            "system_prompt": system_prompt,
            "ttl_seconds": ttl_seconds,
            "metadata": metadata
        }
        resp, _ = self._execute_with_retry("POST", "/api/v1/ingest", json_data=payload)
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)

        d = resp.json()
        return IngestResponse(
            status=d.get("status", ""),
            doc_id=d.get("doc_id", ""),
            doc_type=d.get("doc_type", ""),
            vector_dims=d.get("vector_dims", 0),
            total_documents=d.get("total_documents", 0)
        )

    def ingest_batch(self, documents: List[Dict[str, Any]]) -> BatchIngestResponse:
        """Indexa masivamente una lista de documentos."""
        payload = {"documents": documents}
        resp, _ = self._execute_with_retry("POST", "/api/v1/ingest/batch", json_data=payload)
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)

        d = resp.json()
        return BatchIngestResponse(
            status=d.get("status", ""),
            total_requested=d.get("total_requested", 0),
            successfully_indexed=d.get("successfully_indexed", 0),
            failed_embeddings=d.get("failed_embeddings", 0),
            total_documents_in_index=d.get("total_documents_in_index", 0)
        )

    def delete_cache(self, doc_id: str) -> bool:
        """Elimina un documento o elemento de caché por su ID."""
        resp, _ = self._execute_with_retry("DELETE", f"/api/v1/cache/{doc_id}")
        if resp.status_code == 404:
            return False
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)
        return True

# ==============================================================================
# Cliente Asíncrono
# ==============================================================================

class AsyncOpenHybridRAGClient:
    """
    Cliente Asíncrono para aplicaciones FastAPI, bots, agentes y workers de alta concurrencia.
    """
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        api_key: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        app: Optional[Any] = None
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenHybridRAG-SDK-Async/1.3.0-Python"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        if app is not None:
            self._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=self.base_url, headers=headers, timeout=self.timeout)
        elif transport is not None:
            self._client = httpx.AsyncClient(transport=transport, base_url=self.base_url, headers=headers, timeout=self.timeout)
        else:
            self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=self.timeout)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _execute_with_retry(self, method: str, path: str, json_data: Optional[dict] = None) -> Tuple[httpx.Response, int]:
        import asyncio
        retries = 0
        while True:
            try:
                response = await self._client.request(method=method, url=path, json=json_data)
                
                # Manejo de Rate Limiting (HTTP 429)
                if response.status_code == 429:
                    raw_retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = float(raw_retry_after) if raw_retry_after else 1.0
                    except (ValueError, TypeError):
                        retry_after = 1.0

                    if retries >= self.max_retries:
                        payload = response.json() if "json" in response.headers.get("content-type", "") else {}
                        raise RateLimitError(
                            retry_after=retry_after,
                            message=f"Límite de tasa excedido tras {retries} reintentos. Retry-After: {retry_after}s",
                            payload=payload
                        )

                    sleep_time = retry_after + random.uniform(0.05, 0.25)
                    logger.warning(f"⚠️ [AsyncSDK] HTTP 429 detectado. Esperando {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)
                    retries += 1
                    continue

                if response.status_code in (502, 503, 504) and retries < self.max_retries:
                    sleep_time = (self.backoff_factor * (2 ** retries)) + random.uniform(0.05, 0.15)
                    await asyncio.sleep(sleep_time)
                    retries += 1
                    continue

                return response, retries

            except (httpx.ConnectError, httpx.TimeoutException) as net_err:
                if retries >= self.max_retries:
                    raise OpenHybridRAGException(f"Fallo de conexión tras {retries} reintentos: {net_err}")
                sleep_time = (self.backoff_factor * (2 ** retries)) + random.uniform(0.05, 0.15)
                await asyncio.sleep(sleep_time)
                retries += 1

    async def query(
        self,
        prompt: str,
        system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado.",
        allow_cloud_fallback: bool = True,
        force_cloud: bool = False,
        audit_assert: bool = False
    ) -> QueryResponse:
        """Consulta asíncrona al orquestador True Hybrid RAG."""
        payload = {
            "query": prompt,
            "system_prompt": system_prompt,
            "allow_cloud_fallback": allow_cloud_fallback,
            "force_cloud": force_cloud,
            "audit_assert": audit_assert
        }
        resp, retries = await self._execute_with_retry("POST", "/api/v1/orchestrate", json_data=payload)
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)

        data = resp.json()
        return QueryResponse(
            request_id=data.get("request_id", ""),
            query=data.get("query", prompt),
            route_taken=data.get("route_taken", "UNKNOWN"),
            source=data.get("source", "unknown"),
            similarity_score=data.get("similarity_score", 0.0),
            answer=data.get("answer", ""),
            second_brain_doc_id=data.get("second_brain_doc_id"),
            telemetry=data.get("telemetry", {}),
            assert_audit=data.get("assert_audit"),
            retries_made=retries
        )

    async def health(self) -> Dict[str, Any]:
        resp, _ = await self._execute_with_retry("GET", "/health")
        if resp.status_code != 200:
            raise APIError(resp.status_code, resp.text)
        return resp.json()

    async def stream_query(
        self,
        prompt: str,
        system_prompt: Optional[str] = "Eres un asistente de ingeniería directo, claro y estructurado.",
        allow_cloud_fallback: bool = True,
        force_cloud: bool = False,
        audit_assert: bool = False
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Envía una consulta asincrónica con streaming Server-Sent Events (SSE) en tiempo real.
        Genera diccionarios estructurados: {'event': 'meta'|'token'|'done', 'data': {...}}
        """
        import asyncio
        payload = {
            "query": prompt,
            "system_prompt": system_prompt,
            "allow_cloud_fallback": allow_cloud_fallback,
            "force_cloud": force_cloud,
            "audit_assert": audit_assert
        }
        async with self._client.stream("POST", "/api/v1/orchestrate/stream", json=payload) as response:
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.0))
                await asyncio.sleep(retry_after + random.uniform(0.05, 0.25))
                async with self._client.stream("POST", "/api/v1/orchestrate/stream", json=payload) as retry_resp:
                    if retry_resp.status_code != 200:
                        body = await retry_resp.aread()
                        raise APIError(retry_resp.status_code, body.decode("utf-8"))
                    current_event = None
                    async for line in retry_resp.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("event: "):
                            current_event = line[7:].strip()
                        elif line.startswith("data: "):
                            raw_data = line[6:].strip()
                            try:
                                data = json.loads(raw_data)
                            except Exception:
                                data = raw_data
                            yield {"event": current_event or "message", "data": data}
                return

            if response.status_code != 200:
                body = await response.aread()
                raise APIError(response.status_code, body.decode("utf-8"))

            current_event = None
            async for line in response.aiter_lines():
                if not line:
                    continue
                line = line.strip()
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: "):
                    raw_data = line[6:].strip()
                    try:
                        data = json.loads(raw_data)
                    except Exception:
                        data = raw_data
                    yield {"event": current_event or "message", "data": data}

