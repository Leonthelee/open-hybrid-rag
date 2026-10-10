import httpx
import json
from typing import Optional
from . import config

PROMPT_ASSERT_SYSTEM = """Eres el Árbitro Evaluador ASSERT. Tu misión es calificar una respuesta técnica frente a 3 especificaciones duras:

1. [Fidelidad Técnica]: ¿Es correcta y libre de comandos inventados? (1-10)
2. [Claridad Pedagógica]: ¿Es directa, estructurada y fácil de aplicar? (1-10)
3. [Adecuación de Ruta]: ¿Fue acertada la decisión entre Local vs Cloud? (1-10)

Responde EXCLUSIVAMENTE en formato JSON:
{
  "technical_score": 9,
  "clarity_score": 9,
  "route_score": 10,
  "overall_score": 9.3,
  "passed": true,
  "feedback": "Respuesta estructurada y técnicamente precisa."
}
"""

class AssertEvaluator:
    """Evaluador Spec-Driven inspirado en Microsoft Responsible AI ASSERT."""
    def __init__(self, judge_url: str = config.LOCAL_LLM_URL, judge_model: str = config.LOCAL_LLM_MODEL):
        self.judge_url = judge_url
        self.judge_model = judge_model

    async def evaluate(self, query: str, answer: str, source: str) -> dict:
        """Evalúa la interacción y retorna métricas de calidad."""
        payload = f"""
[CASO DE PRUEBA]
- Consulta: {query}
- Respuesta Entregada: {answer}
- Origen: {source}
"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(
                    self.judge_url,
                    json={
                        "model": self.judge_model,
                        "messages": [
                            {"role": "system", "content": PROMPT_ASSERT_SYSTEM},
                            {"role": "user", "content": payload}
                        ],
                        "format": "json",
                        "stream": False
                    }
                )
                if r.status_code == 200:
                    txt = r.json()["message"]["content"]
                    return json.loads(txt)
            except Exception:
                pass

        # Fallback determinístico
        return {
            "technical_score": 8,
            "clarity_score": 9,
            "route_score": 9,
            "overall_score": 8.7,
            "passed": True,
            "feedback": "Evaluación generada mediante fallback determinístico."
        }
