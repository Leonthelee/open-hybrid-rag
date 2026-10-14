import httpx
import logging
from typing import Optional, Tuple, AsyncIterator
try:
    from . import config
except (ImportError, ValueError):
    import config

logger = logging.getLogger("open_hybrid_rag.cloud_bridge")

class CloudBridgeError(Exception):
    """Excepción para errores de conectividad o autenticación con proveedores cloud."""
    pass

class CloudBridge:
    """Puente Universal de Escalamiento Multi-Cloud con Detección de Bloqueos y Truncado."""
    def __init__(
        self,
        provider: str = config.CLOUD_PROVIDER,
        api_key: str = config.CLOUD_API_KEY,
        model: str = config.CLOUD_MODEL,
        max_tokens: int = config.CLOUD_MAX_TOKENS
    ):
        self.provider = provider.lower().strip()
        self.api_key = api_key
        self.model = model or config.PROVIDER_DEFAULT_MODELS.get(self.provider, "gemini-2.0-flash")
        self.max_tokens = max_tokens

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Invocación a la nube con verificación de código y estados de terminación.
        Retorna: (success: bool, response_or_error: str)
        """
        target_sys = system_instruction or system_prompt
        if not self.api_key:
            return False, f"CLOUD_API_KEY no está configurada o contiene un placeholder para el proveedor '{self.provider}'."

        if self.provider == "gemini":
            return await self._call_gemini(prompt, target_sys)
        elif self.provider in ("openai", "groq", "deepseek"):
            return await self._call_openai_compatible(prompt, target_sys)
        elif self.provider == "anthropic":
            return await self._call_anthropic(prompt, target_sys)
        else:
            return False, f"Proveedor cloud '{self.provider}' no reconocido."

    async def _call_gemini(self, prompt: str, system_instruction: Optional[str]) -> Tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        full_prompt = f"[Sistema]: {system_instruction}\n\n[Consulta]:\n{prompt}" if system_instruction else prompt
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens
            }
        }

        async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        prompt_feedback = data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason", "SAFETY")
                        return False, f"SAFETY_BLOCKED: Consulta bloqueada por filtros de seguridad ({block_reason})."

                    candidate = candidates[0]
                    finish_reason = candidate.get("finishReason", "STOP")
                    
                    if finish_reason == "SAFETY":
                        return False, "SAFETY_BLOCKED: Respuesta bloqueada por políticas de seguridad de Gemini."
                    elif finish_reason == "MAX_TOKENS":
                        return False, "TRUNCATED: Respuesta truncada por exceder max_tokens."
                    elif finish_reason == "RECITATION":
                        return False, "RECITATION_BLOCKED: Respuesta bloqueada por coincidencia de derechos de autor."

                    parts = candidate.get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return True, parts[0]["text"]
                    return False, "EMPTY_RESPONSE: El modelo no generó texto en su respuesta."

                return False, f"HTTP_{resp.status_code}: {resp.text}"
            except Exception as e:
                return False, f"NETWORK_ERROR: {str(e)}"

    async def _call_openai_compatible(self, prompt: str, system_instruction: Optional[str]) -> Tuple[bool, str]:
        url_map = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/v1/chat/completions"
        }
        url = url_map.get(self.provider, "https://api.openai.com/v1/chat/completions")
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens
        }

        async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        return False, "EMPTY_RESPONSE: Sin opciones en respuesta OpenAI."
                    
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason")
                    if finish_reason == "length":
                        return False, "TRUNCATED: Respuesta truncada por exceder max_tokens."
                    elif finish_reason == "content_filter":
                        return False, "SAFETY_BLOCKED: Bloqueado por filtro de contenido OpenAI."

                    text = choice.get("message", {}).get("content", "")
                    if text:
                        return True, text
                    return False, "EMPTY_RESPONSE: El modelo devolvió contenido vacío."

                return False, f"HTTP_{resp.status_code}: {resp.text}"
            except Exception as e:
                return False, f"NETWORK_ERROR: {str(e)}"

    async def _call_anthropic(self, prompt: str, system_instruction: Optional[str]) -> Tuple[bool, str]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": self.model or "claude-3-5-sonnet-20241022",
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_instruction:
            payload["system"] = system_instruction

        async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    stop_reason = data.get("stop_reason")
                    if stop_reason == "max_tokens":
                        return False, "TRUNCATED: Respuesta truncada por exceder max_tokens en Claude."

                    contents = data.get("content", [])
                    if contents and "text" in contents[0]:
                        return True, contents[0]["text"]
                    return False, "EMPTY_RESPONSE: Respuesta sin texto en Claude."

                return False, f"HTTP_{resp.status_code}: {resp.text}"
            except Exception as e:
                return False, f"NETWORK_ERROR: {str(e)}"

    async def generate_stream(
        self,
        prompt: str,
        system_instruction: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Transmite tokens desde el proveedor cloud en fragmentos estructurados."""
        success, full_resp = await self.generate(prompt, system_instruction)
        if not success:
            yield f"CLOUD_ERROR: {full_resp}"
            return
        words = full_resp.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

