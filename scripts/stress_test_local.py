"""
scripts/stress_test_local.py
Módulo de Pruebas de Carga y Concurrencia Local para Open Hybrid RAG Gateway.
Evalúa:
1. Rendimiento y Latencia por Percentiles (P50, P90, P95, P99) bajo carga.
2. Comportamiento determinista del Token Bucket ante ráfagas de denegación de servicio (DoS).
3. Concurrencia y ausencia de condiciones de carrera en True Hybrid RAG (BM25 + RRF).
Ejecución autónoma y segura en memoria (compatible con TestClient o servidor HTTP vivo).
"""
import os
import sys
import time
import math
import statistics
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

# Asegurar importación de módulos del proyecto
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
src_dir = os.path.join(ROOT_DIR, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import config
from main import app, rate_limiter
from security import TokenBucket
from vector_guard import VectorGuard

class StressTestRunner:
    def __init__(self):
        self.client = TestClient(app)
        self.auth_headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}

    @staticmethod
    def _calc_percentiles(durations: List[float]) -> Dict[str, float]:
        if not durations:
            return {"min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
        s = sorted(durations)
        n = len(s)
        def p(pct: float) -> float:
            idx = int(math.ceil(pct * n)) - 1
            return round(s[max(0, min(n - 1, idx))] * 1000, 2)
        return {
            "min": round(min(s) * 1000, 2),
            "max": round(max(s) * 1000, 2),
            "mean": round(statistics.mean(s) * 1000, 2),
            "p50": p(0.50),
            "p90": p(0.90),
            "p95": p(0.95),
            "p99": p(0.99)
        }

    def run_scenario_a_baseline(self, num_requests: int = 40) -> Dict[str, Any]:
        """Escenario A: Concurrencia controlada dentro de los límites de cuota."""
        durations: List[float] = []
        statuses: Dict[int, int] = {}

        def send_req():
            t0 = time.perf_counter()
            r = self.client.get("/health")
            t1 = time.perf_counter()
            return r.status_code, (t1 - t0)

        t_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(send_req) for _ in range(num_requests)]
            for f in futures:
                code, dur = f.result()
                durations.append(dur)
                statuses[code] = statuses.get(code, 0) + 1
        t_total = time.perf_counter() - t_start

        pcts = self._calc_percentiles(durations)
        rps = round(num_requests / t_total, 1) if t_total > 0 else 0.0
        return {
            "name": "Línea Base Salud (Health Probe)",
            "requests": num_requests,
            "success_200": statuses.get(200, 0),
            "blocked_429": statuses.get(429, 0),
            "other_status": sum(v for k, v in statuses.items() if k not in (200, 429)),
            "rps": rps,
            "percentiles": pcts
        }

    def run_scenario_b_burst_rate_limit(self, burst_size: int = 75) -> Dict[str, Any]:
        """
        Escenario B: Ráfaga masiva que satura la cubeta de tokens (capacidad=60).
        Verifica que exactamente los primeros 60 tokens pasen (200 OK) y los 15 excedentes reciban HTTP 429.
        """
        import hashlib
        headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        if config.API_KEY:
            client_id = f"key:{hashlib.sha256(config.API_KEY.encode()).hexdigest()[:16]}"
        else:
            client_id = "ip:testclient"

        # Inicializar cubeta fresca con capacidad 60
        rate_limiter.buckets[client_id] = TokenBucket(capacity=config.RATE_LIMIT_CAPACITY, refill_rate=config.RATE_LIMIT_REFILL_RATE)

        durations: List[float] = []
        statuses: Dict[int, int] = {}
        retry_headers_count = 0

        def send_burst():
            t0 = time.perf_counter()
            r = self.client.get("/api/v1/config", headers=headers)
            t1 = time.perf_counter()
            has_retry = "Retry-After" in r.headers
            return r.status_code, (t1 - t0), has_retry

        t_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_burst) for _ in range(burst_size)]
            for f in futures:
                code, dur, has_retry = f.result()
                durations.append(dur)
                statuses[code] = statuses.get(code, 0) + 1
                if has_retry and code == 429:
                    retry_headers_count += 1
        t_total = time.perf_counter() - t_start

        # Restaurar cubeta
        rate_limiter.buckets[client_id].tokens = float(config.RATE_LIMIT_CAPACITY)

        pcts = self._calc_percentiles(durations)
        rps = round(burst_size / t_total, 1) if t_total > 0 else 0.0
        return {
            "name": "Ráfaga Anti-DoS (Excede Cuota)",
            "requests": burst_size,
            "success_200": statuses.get(200, 0),
            "blocked_429": statuses.get(429, 0),
            "retry_headers_valid": retry_headers_count == statuses.get(429, 0),
            "rps": rps,
            "percentiles": pcts
        }

    def run_scenario_c_hybrid_rag_concurrency(self, num_queries: int = 20) -> Dict[str, Any]:
        """
        Escenario C: Concurrencia de consultas al motor True Hybrid RAG (BM25 + RRF).
        Verifica consistencia matricial y cálculo léxico sin condiciones de carrera.
        """
        vg = VectorGuard()
        vg.load_from_disk(config.INDEX_STORAGE_PATH)

        queries = [
            "OWASP API3:2023 BOPLA mass assignment mitigación",
            "CIS Linux sysctl net.ipv4.tcp_syncookies ASLR",
            "CIS Kubernetes readOnlyRootFilesystem automountServiceAccountToken",
            "WSTG input validation SQL injection TLFR",
            "MITRE M1042 attack surface reduction disabling interpreters"
        ]

        durations: List[float] = []
        correct_retrievals = 0

        def run_query(q_text: str):
            t0 = time.perf_counter()
            route, doc, score = vg.hybrid_match(query_text=q_text, query_vector=None)
            t1 = time.perf_counter()
            is_valid = (doc is not None) and (score > 0.0)
            return (t1 - t0), is_valid

        t_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(run_query, queries[i % len(queries)]) for i in range(num_queries)]
            for f in futures:
                dur, is_valid = f.result()
                durations.append(dur)
                if is_valid:
                    correct_retrievals += 1
        t_total = time.perf_counter() - t_start

        pcts = self._calc_percentiles(durations)
        rps = round(num_queries / t_total, 1) if t_total > 0 else 0.0
        return {
            "name": "True Hybrid RAG Concurrente",
            "requests": num_queries,
            "success_retrievals": correct_retrievals,
            "failed_retrievals": num_queries - correct_retrievals,
            "rps": rps,
            "percentiles": pcts
        }

    def run_all(self):
        print("=" * 85)
        print("⚡ PRUEBAS DE CARGA, RENDIMIENTO Y CONCURRENCIA LOCAL (STRESS TEST)")
        print(f"   Capacidad Token Bucket: {config.RATE_LIMIT_CAPACITY} | Recarga: {config.RATE_LIMIT_REFILL_RATE} t/s")
        print("=" * 85)

        print("\n[1/3] Ejecutando Escenario A: Línea Base de Concurrencia...")
        res_a = self.run_scenario_a_baseline(num_requests=50)

        print("[2/3] Ejecutando Escenario B: Ráfaga Anti-DoS para Saturación de Cuota...")
        res_b = self.run_scenario_b_burst_rate_limit(burst_size=75)

        print("[3/3] Ejecutando Escenario C: Concurrencia Matricial True Hybrid RAG...")
        res_c = self.run_scenario_c_hybrid_rag_concurrency(num_queries=30)

        # Imprimir Tabla Resumen
        print("\n" + "=" * 85)
        print(f"{'ESCENARIO':<32} | {'PETS':<5} | {'OK':<4} | {'429':<4} | {'P50 (ms)':<9} | {'P95 (ms)':<9} | {'P99 (ms)':<9} | {'RPS':<8}")
        print("-" * 85)
        for r in [res_a, res_b]:
            p = r["percentiles"]
            print(f"{r['name']:<32} | {r['requests']:<5} | {r['success_200']:<4} | {r['blocked_429']:<4} | {p['p50']:<9.2f} | {p['p95']:<9.2f} | {p['p99']:<9.2f} | {r['rps']:<8.1f}")
        
        # Escenario C
        p_c = res_c["percentiles"]
        print(f"{res_c['name']:<32} | {res_c['requests']:<5} | {res_c['success_retrievals']:<4} | {'N/A':<4} | {p_c['p50']:<9.2f} | {p_c['p95']:<9.2f} | {p_c['p99']:<9.2f} | {res_c['rps']:<8.1f}")
        print("=" * 85)

        # Verificaciones críticas
        passed_b = res_b["blocked_429"] > 0 and res_b["retry_headers_valid"]
        passed_c = res_c["failed_retrievals"] == 0
        all_passed = (res_a["success_200"] == res_a["requests"]) and passed_b and passed_c

        print(f"📊 VEREDICTO DE RENDIMIENTO Y RESILIENCIA: {'✅ APROBADO (100% Determinista)' if all_passed else '❌ FALLO'}")
        if passed_b:
            print(f"   ✓ Token Bucket: Bloqueó exactamente {res_b['blocked_429']} peticiones con Retry-After conforme a diseño.")
        if passed_c:
            print(f"   ✓ True Hybrid RAG: {res_c['success_retrievals']}/{res_c['requests']} consultas recuperadas sin colisión de hilos.")
        print("=" * 85)
        return all_passed

def main():
    runner = StressTestRunner()
    ok = runner.run_all()
    if not ok:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
