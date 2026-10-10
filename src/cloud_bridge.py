import httpx
from typing import Optional
from . import config

class CloudBridge:
    """Puente de Escalamiento a Google Gemini AI en la nube."""
    def __init__(self, api_key: str = config.GEMINI_API_KEY, model: str = config.GEMINI_MODEL):
        self.api_key = api_key
        self.model = model

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Invocación directa a la API de Google Gemini."""
        if not self.api_key:
            return (
                "⚠️ [Cloud Fallback Desactivado]: Configura GEMINI_API_KEY en tu archivo .env "
                "para habilitar el escalamiento de alta capacidad a Google Gemini."
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        contents = []
        if system_instruction:
            prompt_full = f"[Instrucción del Sistema]: {system_instruction}\n\n[Consulta del Usuario]:\n{prompt}"
        else:
            prompt_full = prompt

        payload = {
            "contents": [{
                "parts": [{"text": prompt_full}]
            }]
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                return f"Error Google Gemini ({resp.status_code}): {resp.text}"
            except Exception as e:
                return f"Excepción de conexión con Google Gemini: {e}"
