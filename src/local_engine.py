import httpx
import logging
from typing import Optional, Tuple
try:
    from . import config
except (ImportError, ValueError):
    import config

logger = logging.getLogger("open_hybrid_rag.local_engine")

class LocalEngine:
    """Cliente universal para motores locales (Ollama, LM Studio, vLLM, LocalAI) con sondeo de salud."""
    def __init__(
        self,
        engine_type: str = config.LOCAL_ENGINE_TYPE,
        llm_url: str = config.LOCAL_LLM_URL,
        embed_url: str = config.LOCAL_EMBED_URL
    ):
        self.engine_type = engine_type
        self.llm_url = llm_url
        self.embed_url = embed_url

    async def ping(self) -> bool:
        """Comprueba disponibilidad del motor local."""
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                # Para Ollama
                if self.engine_type == "ollama":
                    base_url = self.llm_url.replace("/api/chat", "/api/tags")
                    r = await client.get(base_url)
                    return r.status_code == 200
                else:
                    # Para OpenAI-compatible
                    base_url = self.llm_url.replace("/chat/completions", "/models")
                    r = await client.get(base_url)
                    return r.status_code == 200
            except Exception:
                return False

    async def get_embedding(self, text: str, model: str = config.LOCAL_EMBED_MODEL) -> list[float]:
        """Obtiene vector de embeddings desde Ollama o endpoint OpenAI-compatible."""
        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                if self.engine_type == "ollama":
                    r = await client.post(
                        self.embed_url,
                        json={"model": model, "prompt": text}
                    )
                    if r.status_code == 200:
                        return r.json().get("embedding", [])
                else:
                    r = await client.post(
                        self.embed_url,
                        json={"model": model, "input": text}
                    )
                    if r.status_code == 200:
                        data = r.json()
                        return data.get("data", [{}])[0].get("embedding", [])
            except Exception as e:
                logger.warning(f"Local Engine Embed Error: {e}")
        return []

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = config.LOCAL_LLM_MODEL
    ) -> Tuple[bool, str]:
        """Inferencia local con retorno estricto de (éxito, respuesta_o_error)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=90.0) as client:
            try:
                if self.engine_type == "ollama":
                    r = await client.post(
                        self.llm_url,
                        json={"model": model, "messages": messages, "stream": False}
                    )
                    if r.status_code == 200:
                        return True, r.json()["message"]["content"]
                    return False, f"LOCAL_HTTP_{r.status_code}: {r.text}"
                else:
                    r = await client.post(
                        self.llm_url,
                        json={"model": model, "messages": messages}
                    )
                    if r.status_code == 200:
                        return True, r.json()["choices"][0]["message"]["content"]
                    return False, f"LOCAL_HTTP_{r.status_code}: {r.text}"
            except Exception as e:
                return False, f"LOCAL_CONNECT_ERROR: {str(e)}"
