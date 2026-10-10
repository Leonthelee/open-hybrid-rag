import httpx
from typing import Optional
from . import config

class LocalEngine:
    """Cliente universal agnóstico para modelos y embeddings locales."""
    def __init__(self, llm_url: str = config.LOCAL_LLM_URL, embed_url: str = config.LOCAL_EMBED_URL):
        self.llm_url = llm_url
        self.embed_url = embed_url

    async def get_embedding(self, text: str, model: str = config.LOCAL_EMBED_MODEL) -> list[float]:
        """Obtiene vector de embeddings desde el servidor local."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(
                    self.embed_url,
                    json={"model": model, "prompt": text}
                )
                if r.status_code == 200:
                    data = r.json()
                    return data.get("embedding", [])
            except Exception as e:
                print(f"[⚠️ Local Engine Embed Error]: {e}")
        return []

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, model: str = config.LOCAL_LLM_MODEL) -> str:
        """Inferencia de texto con el LLM local."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=90.0) as client:
            try:
                r = await client.post(
                    self.llm_url,
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False
                    }
                )
                if r.status_code == 200:
                    return r.json()["message"]["content"]
                return f"Error Local LLM (Status {r.status_code}): {r.text}"
            except Exception as e:
                return f"Excepción de conexión con Local LLM: {e}"
