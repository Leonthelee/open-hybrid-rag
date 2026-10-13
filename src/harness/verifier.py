"""
src/harness/verifier.py
Caja 7 del Arnés: Verifier (El Juez Determinista).
Verifica el estado real del sistema operativo y código, no las afirmaciones del modelo.
Aplica la regla de oro: lo que el LLM diga ("Ya está arreglado") vale CERO.
Solo aprueba el estado DONE si los tests pasan, no hay linter errors y quedan turnos.
"""
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class VerificationVerdict(str, Enum):
    SHIP_IT = "SHIP_IT"                 # Todos los tests en verde, lints limpios -> Listo para PR/Commit
    LOOP_AGAIN = "LOOP_AGAIN"           # Fallaron tests o sintaxis -> Forzar nuevo turno con feedback
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED" # Se agotó el presupuesto de turnos -> Abortar para frenar costos

class VerificationResult(BaseModel):
    verdict: VerificationVerdict
    tests_passed: bool
    lint_clean: bool
    budget_ok: bool
    has_real_changes: bool
    current_turn: int
    max_turns: int
    feedback_for_model: str
    metrics: Dict[str, Any] = Field(default_factory=dict)

class Verifier:
    def __init__(self, max_turns: int = 15):
        self.max_turns = max_turns

    def verify(
        self,
        current_turn: int,
        test_exit_code: int,
        test_summary: str,
        lint_error_count: int = 0,
        files_modified_count: int = 1,
        model_claimed_done: bool = True
    ) -> VerificationResult:
        """
        Inspecciona el estado determinista y emite el veredicto del juez.
        """
        tests_passed = (test_exit_code == 0)
        lint_clean = (lint_error_count == 0)
        budget_ok = (current_turn <= self.max_turns)
        has_real_changes = (files_modified_count > 0)

        # 1. Presupuesto de turnos agotado
        if not budget_ok:
            return VerificationResult(
                verdict=VerificationVerdict.BUDGET_EXCEEDED,
                tests_passed=tests_passed,
                lint_clean=lint_clean,
                budget_ok=False,
                has_real_changes=has_real_changes,
                current_turn=current_turn,
                max_turns=self.max_turns,
                feedback_for_model=f"PRESUPUESTO AGOTADO: Se alcanzaron los {self.max_turns} turnos máximos sin estabilizar los tests.",
                metrics={"current_turn": current_turn, "max_turns": self.max_turns}
            )

        # 2. El modelo dice que terminó, pero no modificó ningún archivo
        if model_claimed_done and not has_real_changes:
            return VerificationResult(
                verdict=VerificationVerdict.LOOP_AGAIN,
                tests_passed=False,
                lint_clean=lint_clean,
                budget_ok=True,
                has_real_changes=False,
                current_turn=current_turn,
                max_turns=self.max_turns,
                feedback_for_model="RECHAZADO: Declaraste que la tarea está lista pero no se detectaron cambios reales en archivos.",
                metrics={"files_modified": 0}
            )

        # 3. Fallo en tests reales
        if not tests_passed:
            return VerificationResult(
                verdict=VerificationVerdict.LOOP_AGAIN,
                tests_passed=False,
                lint_clean=lint_clean,
                budget_ok=True,
                has_real_changes=has_real_changes,
                current_turn=current_turn,
                max_turns=self.max_turns,
                feedback_for_model=f"RECHAZADO 'ALL DONE': Los tests siguen fallando (exit code {test_exit_code}). Corrige la causa raíz:\n{test_summary}",
                metrics={"test_exit_code": test_exit_code, "test_summary": test_summary}
            )

        # 4. Fallo en linters o sintaxis
        if not lint_clean:
            return VerificationResult(
                verdict=VerificationVerdict.LOOP_AGAIN,
                tests_passed=True,
                lint_clean=False,
                budget_ok=True,
                has_real_changes=has_real_changes,
                current_turn=current_turn,
                max_turns=self.max_turns,
                feedback_for_model=f"RECHAZADO: Los tests pasaron pero se detectaron {lint_error_count} errores de linter/sintaxis.",
                metrics={"lint_errors": lint_error_count}
            )

        # 5. Éxito determinista total (SHIP IT)
        return VerificationResult(
            verdict=VerificationVerdict.SHIP_IT,
            tests_passed=True,
            lint_clean=True,
            budget_ok=True,
            has_real_changes=has_real_changes,
            current_turn=current_turn,
            max_turns=self.max_turns,
            feedback_for_model=f"APROBADO PARA ENVÍO (SHIP IT): Tests en verde (exit code 0), 0 errores de linter, completado en {current_turn}/{self.max_turns} turnos.",
            metrics={"current_turn": current_turn, "tests_passed": True, "lint_clean": True}
        )
