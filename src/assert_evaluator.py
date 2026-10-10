import httpx
import json
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError

try:
    from . import config
except (ImportError, ValueError):
    import config

logger = logging.getLogger("open_hybrid_rag.assert_evaluator")

PROMPT_ASSERT_SYSTEM = """Eres el Árbitro Evaluador ASSERT (Automated Specification & Semantic Exactness Reviewer).
Tu misión es calificar una respuesta técnica frente a 3 especificaciones duras:

1. [Fidelidad Técnica]: ¿Es correcta y libre de comandos o conceptos inventados? (Puntaje 0.0 - 10.0)
2. [Claridad Pedagógica]: ¿Es directa, estructurada y ejecutable? (Puntaje 0.0 - 10.0)
3. [Adecuación de Ruta]: ¿Fue acertada la decisión entre Local vs Cloud? (Puntaje 0.0 - 10.0)

Regla de Aprobación: passed = true SOLO si overall_score >= 8.0 y fidelidad >= 8.0.

Responde EXCLUSIVAMENTE en formato JSON válido con este esquema exacto:
{
  "technical_score": 9.0,
  "clarity_score": 9.0,
  "route_score": 10.0,
  "overall_score": 9.3,
  "passed": true,
  "feedback": "Respuesta estructurada y técnicamente precisa."
}
"""

class AssertEvaluationResult(BaseModel):
    technical_score: float = Field(..., ge=0.0, le=10.0)
    clarity_score: float = Field(..., ge=0.0, le=10.0)
    route_score: float = Field(..., ge=0.0, le=10.0)
    overall_score: float = Field(..., ge=0.0, le=10.0)
    passed: bool
    feedback: str = Field(..., min_length=1)
    evaluation_status: str = "completed"

class AssertEvaluator:
    """Evaluador Spec-Driven inspirado en Microsoft Responsible AI ASSERT con validación de esquema Pydantic."""
    def __init__(
        self,
        judge_url: str = config.LOCAL_LLM_URL,
        judge_model: str = config.LOCAL_LLM_MODEL,
        engine_type: str = config.LOCAL_ENGINE_TYPE
    ):
        self.judge_url = judge_url
        self.judge_model = judge_model
        self.engine_type = engine_type

    async def evaluate(self, query: str, answer: str, source: str) -> Dict[str, Any]:
        """Evalúa la interacción y retorna métricas validadas con Pydantic o estado explícito de indisponibilidad."""
        payload = f"""
[CASO DE PRUEBA]
- Consulta: {query}
- Respuesta Entregada: {answer}
- Origen: {source}
"""
        messages = [
            {"role": "system", "content": PROMPT_ASSERT_SYSTEM},
            {"role": "user", "content": payload}
        ]

        async with httpx.AsyncClient(timeout=35.0) as client:
            try:
                if self.engine_type == "ollama":
                    r = await client.post(
                        self.judge_url,
                        json={
                            "model": self.judge_model,
                            "messages": messages,
                            "format": "json",
                            "stream": False
                        }
                    )
                    if r.status_code == 200:
                        raw_txt = r.json().get("message", {}).get("content", "{}")
                    else:
                        raise Exception(f"HTTP {r.status_code}: {r.text}")
                else:
                    # OpenAI Compatible
                    r = await client.post(
                        self.judge_url,
                        json={
                            "model": self.judge_model,
                            "messages": messages,
                            "response_format": {"type": "json_object"}
                        }
                    )
                    if r.status_code == 200:
                        raw_txt = r.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    else:
                        raise Exception(f"HTTP {r.status_code}: {r.text}")

                # Limpieza de markdown si el modelo envolvió en ```json
                cleaned = raw_txt.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned = "\n".join(lines).strip()

                parsed = json.loads(cleaned)
                
                # Validación estricta con Pydantic
                validated = AssertEvaluationResult(**parsed)
                return validated.model_dump()

            except (ValidationError, json.JSONDecodeError) as val_err:
                logger.warning(f"[ASSERT Evaluator] Respuesta de juez no cumplió el esquema: {val_err}")
                return {
                    "evaluation_status": "schema_violation",
                    "passed": None,
                    "overall_score": None,
                    "feedback": f"El juez retornó una estructura inválida: {str(val_err)}"
                }
            except Exception as e:
                logger.info(f"[ASSERT Evaluator] Juez no disponible: {e}")
                return {
                    "evaluation_status": "unavailable",
                    "passed": None,
                    "overall_score": None,
                    "feedback": f"El juez ASSERT no estuvo disponible para calificar: {str(e)}"
                }
