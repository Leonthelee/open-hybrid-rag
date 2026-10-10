import httpx
from typing import Optional, Tuple
try:
    from . import config
except (ImportError, ValueError):
    import config

class CloudBridgeError(Exception):
    """Excepción para errores de conectividad o autenticación con proveedores cloud."""
    pass

class CloudBridge:
    """Puente Universal de Escalamiento Multi-Cloud con Manejo Estricto de Excepciones."""
    def __init__(
        self,
        provider: str = config.CLOUD_PROVIDER,
        api_key: str = config.CLOUD_API_KEY,
        model: str = config.CLOUD_MODEL
    ):
        self.provider = provider.lower().strip()
        self.api_key = api_key
        self.model = model

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> Tuple[bool, str]:
        """
        Invocación a la nube.
        Retorna: (success: bool, response_or_error: str)
        """
        if not self.api_key:
            return False, "CLOUD_API_KEY no está configurada en las variables de entorno."

        if self.provider == "gemini":
            return await self._call_gemini(prompt, system_instruction)
        elif self.provider in ("openai", "groq", "deepseek"):
            return await self._call_openai_compatible(prompt, system_instruction)
        elif self.provider == "anthropic":
            return await self._call_anthropic(prompt, system_instruction)
        else:
            return False, f"Proveedor cloud '{self.provider}' no reconocido."

    async def _call_gemini(self, prompt: str, system_instruction: Optional[str]) -> Tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        full_prompt = f"[Sistema]: {system_instruction}\n\n[Consulta]:\n{prompt}" if system_instruction else prompt
        payload = {"contents": [{"parts": [{"text": full_prompt}]}]}

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return True, text
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
        payload = {"model": self.model, "messages": messages}

        async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return True, text
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
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_instruction:
            payload["system"] = system_instruction

        async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["content"][0]["text"]
                    return True, text
                return False, f"HTTP_{resp.status_code}: {resp.text}"
            except Exception as e:
                return False, f"NETWORK_ERROR: {str(e)}"
