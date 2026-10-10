import httpx
import json
from typing import Optional, Dict, Any
from . import config

PROMPT_ASSERT_SYSTEM = """Eres el Árbitro Evaluador ASSERT. Tu misión es calificar una respuesta técnica frente a 3 especificaciones duras:

1. [Fidelidad Técnica]: ¿Es correcta y libre de comandos inventados? (1-10)
2. [Claridad Pedagógica]: ¿Es directa, estructurada y fácil de aplicar? (1-10)
3. [Adecuación de Ruta]: ¿Fue acertada la decisión entre Local vs Cloud? (1-10)

Responde EXCLUSIVAMENTE en formato JSON válido con este esquema exacto:
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
    """Evaluador Spec-Driven inspirado en Microsoft Responsible AI ASSERT con validación de esquema."""
    def __init__(self, judge_url: str = config.LOCAL_LLM_URL, judge_model: str = config.LOCAL_LLM_MODEL):
        self.judge_url = judge_url
        self.judge_model = judge_model

    async def evaluate(self, query: str, answer: str, source: str) -> Dict[str, Any]:
        """Evalúa la interacción y retorna métricas reales o estado explícito de indisponibilidad."""
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
                    raw_txt = r.json()["message"]["content"]
                    data = json.loads(raw_txt)
                    # Validar esquema
                    if "overall_score" in data and "passed" in data:
                        data["evaluation_status"] = "completed"
                        return data
            except Exception as e:
                return {
                    "evaluation_status": "unavailable",
                    "passed": None,
                    "overall_score": None,
                    "feedback": f"El juez ASSERT no estuvo disponible para calificar: {str(e)}"
                }

        return {
            "evaluation_status": "unavailable",
            "passed": None,
            "overall_score": None,
            "feedback": "El juez ASSERT devolvió una respuesta no válida."
        }
