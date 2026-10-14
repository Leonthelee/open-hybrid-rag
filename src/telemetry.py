"""
src/telemetry.py
Recolector de Métricas en Memoria Compatible con Formato Prometheus.
Thread-safe, de latencia ultrabaja (O(1)) y sin dependencias externas pesadas.
Monitorea:
- Contadores de peticiones por ruta, método y código de estado.
- Bloqueos de Rate Limiting (HTTP 429).
- Aciertos de caché léxico BM25 y vectorial RRF.
- Escalamientos a Cloud.
- Histogramas de latencia (P50, P90, P95, P99).
"""
import time
import math
import threading
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

class MetricsCollector:
    def __init__(self):
        self._lock = threading.Lock()
        # Contadores: (nombre, tuple(sorted(labels.items()))) -> float
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        # Gauges: nombre -> float
        self._gauges: Dict[str, float] = {}
        # Muestras de latencia para percentiles (ring buffer por métrica)
        self._latencies: Dict[str, List[float]] = defaultdict(list)
        self._max_samples = 2000

    def inc_counter(self, name: str, value: float = 1.0, **labels):
        """Incrementa un contador con etiquetas."""
        label_key = tuple(sorted(labels.items()))
        with self._lock:
            self._counters[(name, label_key)] += value

    def set_gauge(self, name: str, value: float):
        """Establece el valor instantáneo de un gauge."""
        with self._lock:
            self._gauges[name] = float(value)

    def observe_duration(self, name: str, duration_seconds: float):
        """Registra una muestra de duración en segundos para cálculo de percentiles."""
        with self._lock:
            samples = self._latencies[name]
            samples.append(duration_seconds)
            if len(samples) > self._max_samples:
                # Mantener buffer acotado en memoria
                del samples[:len(samples) - self._max_samples]

    def _calc_percentiles(self, samples: List[float]) -> Dict[str, float]:
        if not samples:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_s = sorted(samples)
        n = len(sorted_s)
        def get_p(p: float) -> float:
            idx = int(math.ceil(p * n)) - 1
            return round(sorted_s[max(0, min(n - 1, idx))], 6)
        return {
            "p50": get_p(0.50),
            "p90": get_p(0.90),
            "p95": get_p(0.95),
            "p99": get_p(0.99)
        }

    def export_prometheus(self) -> str:
        """Exporta todas las métricas en formato estándar de texto de Prometheus."""
        lines: List[str] = [
            "# HELP open_hybrid_rag_build_info Información del servicio Open Hybrid RAG Gateway",
            "# TYPE open_hybrid_rag_build_info gauge",
            'open_hybrid_rag_build_info{version="1.3.0",engine="local_first"} 1'
        ]

        with self._lock:
            # 1. Gauges
            for g_name, g_val in self._gauges.items():
                lines.append(f"# HELP {g_name} Métrica instantánea")
                lines.append(f"# TYPE {g_name} gauge")
                lines.append(f"{g_name} {g_val}")

            # 2. Contadores
            counter_groups: Dict[str, List[Tuple[Tuple[Tuple[str, str], ...], float]]] = defaultdict(list)
            for (c_name, l_key), c_val in self._counters.items():
                counter_groups[c_name].append((l_key, c_val))

            for c_name, items in counter_groups.items():
                lines.append(f"# HELP {c_name} Contador acumulado de eventos")
                lines.append(f"# TYPE {c_name} counter")
                for l_key, c_val in items:
                    if l_key:
                        label_str = ",".join(f'{k}="{v}"' for k, v in l_key)
                        lines.append(f"{c_name}{{{label_str}}} {c_val}")
                    else:
                        lines.append(f"{c_name} {c_val}")

            # 3. Histogramas / Percentiles de Latencia
            for lat_name, samples in self._latencies.items():
                if not samples:
                    continue
                pcts = self._calc_percentiles(samples)
                lines.append(f"# HELP {lat_name}_seconds Percentiles de duración en segundos")
                lines.append(f"# TYPE {lat_name}_seconds summary")
                lines.append(f'{lat_name}_seconds{{quantile="0.5"}} {pcts["p50"]}')
                lines.append(f'{lat_name}_seconds{{quantile="0.9"}} {pcts["p90"]}')
                lines.append(f'{lat_name}_seconds{{quantile="0.95"}} {pcts["p95"]}')
                lines.append(f'{lat_name}_seconds{{quantile="0.99"}} {pcts["p99"]}')
                lines.append(f"{lat_name}_seconds_count {len(samples)}")
                lines.append(f"{lat_name}_seconds_sum {round(sum(samples), 6)}")

        return "\n".join(lines) + "\n"

# Instancia global del recolector
metrics_collector = MetricsCollector()
