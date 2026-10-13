"""
src/harness/observe_trim.py
Caja 6 del Arnés: Observe & Trim (El Compresor Inteligente).
Filtra y destila salidas masivas de consola (pytest, npm, logs)
de miles de líneas a solo los fragmentos críticos de fallo,
ahorrando hasta 99.7% de tokens y preservando la ventana de atención.
"""
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class TrimResult(BaseModel):
    trimmed_output: str
    original_lines: int
    trimmed_lines: int
    compression_ratio: float = Field(..., description="Porcentaje de líneas recortadas (ej: 99.7%)")
    has_failure: bool
    summary_header: str

class ObserveTrim:
    def __init__(self, max_output_lines: int = 35):
        self.max_output_lines = max_output_lines
        
        # Patrones que marcan ruido prescindible
        self.noise_patterns = [
            r"^\s*$",                                    # Líneas vacías repetitivas
            r"^\s*\d+%\s*\|[█=-]+\|",                     # Barras de progreso de descarga
            r"^Fetching\s+package\s+metadata",            # Logs de descarga de paquetes
            r"^Downloading\s+https?://",                 # URLs de descarga
            r"^\s*Collecting\s+",                         # pip collecting
            r"DeprecationWarning:",                       # Warnings de librerías de terceros
            r"FutureWarning:",
            r"UserWarning:",
        ]
        
        # Patrones que señalan el núcleo de un error real
        self.critical_error_patterns = [
            r"(?:FAIL|FAILED|FAILURE)\b",
            r"(?:ERROR|Error|Exception):",
            r"AssertionError",
            r"Traceback \(most recent call last\):",
            r"File \".*?\", line \d+",
            r"SyntaxError:",
            r"ImportError:",
            r"ModuleNotFoundError:",
            r"UndefinedVariable",
            r"NullPointerException",
            r"Segmentation fault",
            r"npm ERR!",
        ]

    def trim(self, raw_output: str, exit_code: int = 0) -> TrimResult:
        """
        Recorta la salida cruda de terminal extrayendo la esencia del fallo.
        """
        if not raw_output or not raw_output.strip():
            return TrimResult(
                trimmed_output="[Sin salida en consola (exit code: " + str(exit_code) + ")]",
                original_lines=0,
                trimmed_lines=1,
                compression_ratio=0.0,
                has_failure=(exit_code != 0),
                summary_header="Comando ejecutado sin salida."
            )

        lines = raw_output.splitlines()
        original_count = len(lines)
        has_failure = (exit_code != 0)

        # 1. Caso éxito: Todos los tests pasaron limpiamente
        if exit_code == 0 and not any(re.search(r"\b(FAILED|ERROR)\b", l) for l in lines[-15:]):
            # Extraer las últimas 3 líneas que suelen resumir el resultado (ej. "50 passed in 1.2s")
            meaningful_tail = [l.strip() for l in lines if l.strip() and not self._is_noise(l)][-3:]
            distilled = "\n".join(meaningful_tail) if meaningful_tail else "OK (Exitoso)"
            trimmed_count = len(distilled.splitlines())
            ratio = round((1.0 - (trimmed_count / max(1, original_count))) * 100, 1)
            return TrimResult(
                trimmed_output=f"✓ Ejecución exitosa (exit code 0):\n{distilled}",
                original_lines=original_count,
                trimmed_lines=trimmed_count,
                compression_ratio=max(0.0, ratio),
                has_failure=False,
                summary_header="Comando finalizado con éxito."
            )

        # 2. Caso fallo: Encontrar índices de líneas críticas
        critical_indices = set()
        for i, line in enumerate(lines):
            for pat in self.critical_error_patterns:
                if re.search(pat, line, re.IGNORECASE):
                    # Agregar la línea crítica y un radio de contexto (2 antes, 3 después)
                    start = max(0, i - 2)
                    end = min(original_count, i + 4)
                    critical_indices.update(range(start, end))
                    has_failure = True
                    break

        # Si no encontramos patrones específicos pero exit_code != 0, capturar la cola
        if not critical_indices and exit_code != 0:
            critical_indices.update(range(max(0, original_count - 15), original_count))

        # Construir bloques ordenados y no duplicados
        selected_lines: List[str] = []
        last_idx = -2
        for idx in sorted(critical_indices):
            if self._is_noise(lines[idx]):
                continue
            if idx > last_idx + 1 and last_idx != -2:
                selected_lines.append("... [líneas omitidas] ...")
            selected_lines.append(lines[idx])
            last_idx = idx

        # Si aún excede el límite máximo de líneas del presupuesto, recortar los extremos
        if len(selected_lines) > self.max_output_lines:
            half = self.max_output_lines // 2
            selected_lines = selected_lines[:half] + ["... [recorte de seguridad de tokens] ..."] + selected_lines[-half:]

        trimmed_output = "\n".join(selected_lines)
        trimmed_count = len(selected_lines)
        ratio = round((1.0 - (trimmed_count / max(1, original_count))) * 100, 1)

        summary_header = f"Fallo detectado (exit code {exit_code}). De {original_count} líneas crudas a {trimmed_count} esenciales ({ratio}% comprimido)."

        return TrimResult(
            trimmed_output=trimmed_output,
            original_lines=original_count,
            trimmed_lines=trimmed_count,
            compression_ratio=max(0.0, ratio),
            has_failure=True,
            summary_header=summary_header
        )

    def _is_noise(self, line: str) -> bool:
        """Verifica si una línea es ruido cosmético que debe ser purgado."""
        for pat in self.noise_patterns:
            if re.search(pat, line):
                return True
        return False
