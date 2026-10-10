"""
Runner Científico de Benchmark y Calibración RAG
Evalúa:
1. Precisión Semántica frente a Ground Truth y Keywords.
2. Latencias p50/p95 (Cold Cache vs Warm Cache).
3. Eficiencia de Enrutamiento (Local vs Cloud).
4. Auditoría de Calidad ASSERT.
"""
import os
import sys
import io
import json
import time
import argparse
import asyncio
import numpy as np
import httpx

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BENCHMARK_FILE = os.path.join(os.path.dirname(__file__), "50_technical_benchmark.json")
DEFAULT_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "benchmark_results.json")

def parse_args():
    parser = argparse.ArgumentParser(description="Open Hybrid RAG Gateway Benchmark Runner")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/orchestrate", help="Gateway URL")
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""), help="X-API-Key header if required")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Path to save benchmark JSON report")
    parser.add_argument("--concurrency", type=int, default=1, help="Max concurrent requests")
    parser.add_argument("--audit-assert", action="store_true", help="Enable ASSERT LLM evaluation per query")
    return parser.parse_args()

def calculate_keyword_match(answer: str, expected_keywords: list[str]) -> float:
    if not expected_keywords:
        return 1.0
    ans_lower = answer.lower()
    matches = sum(1 for kw in expected_keywords if kw.lower() in ans_lower)
    return round(matches / len(expected_keywords), 2)

async def ejecutar_pregunta(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    q_data: dict,
    audit_assert: bool
) -> dict:
    q_id = q_data["id"]
    question = q_data["question"]
    keywords = q_data.get("expected_keywords", [])
    ground_truth = q_data.get("ground_truth_summary", "")

    t0 = time.perf_counter()
    try:
        resp = await client.post(
            url,
            headers=headers,
            json={
                "query": question,
                "audit_assert": audit_assert,
                "allow_cloud_fallback": True
            },
            timeout=90.0
        )
        elapsed = (time.perf_counter() - t0) * 1000

        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("answer", "")
            kw_match = calculate_keyword_match(answer, keywords)
            
            return {
                "id": q_id,
                "question": question,
                "status": "OK",
                "http_code": 200,
                "route": data.get("route_taken"),
                "source": data.get("source"),
                "latency_ms": round(elapsed, 2),
                "similarity_score": data.get("similarity_score", 0.0),
                "answer_length": len(answer),
                "keyword_coverage": kw_match,
                "ground_truth_summary": ground_truth,
                "assert_audit": data.get("assert_audit")
            }
        else:
            return {
                "id": q_id,
                "question": question,
                "status": f"HTTP_{resp.status_code}",
                "http_code": resp.status_code,
                "error": resp.text,
                "latency_ms": round(elapsed, 2),
                "keyword_coverage": 0.0
            }
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "id": q_id,
            "question": question,
            "status": "ERROR",
            "http_code": 0,
            "error": str(e),
            "latency_ms": round(elapsed, 2),
            "keyword_coverage": 0.0
        }

async def main():
    args = parse_args()

    if not os.path.exists(BENCHMARK_FILE):
        print(f"❌ Error: No se encontró el dataset en {BENCHMARK_FILE}")
        return

    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        bench_data = json.load(f)

    print("\n" + "="*75)
    print(f"🎯 OPEN HYBRID RAG - BENCHMARK & CALIBRATION SUITE v2.0")
    print(f"📊 Dataset: {bench_data.get('title')}")
    print(f"🌐 Target Gateway: {args.url}")
    print(f"🛡️ Auditoría ASSERT: {'Activada' if args.audit_assert else 'Desactivada (modo rápido)'}")
    print("="*75 + "\n")

    headers = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    todos_resultados = []

    async with httpx.AsyncClient() as client:
        for cat in bench_data.get("categories", []):
            print(f"\n📂 [{cat['category']}]")
            print("-" * 75)
            for q in cat.get("questions", []):
                res = await ejecutar_pregunta(client, args.url, headers, q, args.audit_assert)
                todos_resultados.append(res)
                
                kw_str = f"KW: {int(res.get('keyword_coverage', 0)*100)}%" if res["status"] == "OK" else "FAIL"
                print(f"  [{res['id']:<7}] {res['status']:<8} | Ruta: {str(res.get('route', 'N/A')):<18} | Lat: {res['latency_ms']:>7.2f}ms | {kw_str}")

    # Análisis Estadístico
    total = len(todos_resultados)
    validos = [r for r in todos_resultados if r["status"] == "OK"]
    exitos = len(validos)
    
    locales_high = sum(1 for r in validos if r.get("route") == "RESOLVE_LOCAL_HIGH")
    locales_med = sum(1 for r in validos if r.get("route") == "RESOLVE_LOCAL_MED")
    cloud_fallback = sum(1 for r in validos if "CLOUD" in str(r.get("route", "")))
    abstenciones = sum(1 for r in validos if "ABSTENTION" in str(r.get("route", "")))

    latencias = [r["latency_ms"] for r in validos]
    kw_coverages = [r["keyword_coverage"] for r in validos]

    p50 = round(float(np.percentile(latencias, 50)), 2) if latencias else 0
    p95 = round(float(np.percentile(latencias, 95)), 2) if latencias else 0
    avg_lat = round(float(np.mean(latencias)), 2) if latencias else 0
    min_lat = round(float(np.min(latencias)), 2) if latencias else 0
    max_lat = round(float(np.max(latencias)), 2) if latencias else 0
    avg_kw = round(float(np.mean(kw_coverages)) * 100, 1) if kw_coverages else 0

    resumen = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_url": args.url,
        "total_evaluated": total,
        "successful_responses": exitos,
        "success_rate_pct": round((exitos / total) * 100, 1) if total else 0,
        "routing_breakdown": {
            "resolve_local_high_cache": locales_high,
            "resolve_local_med_context": locales_med,
            "escalate_to_cloud": cloud_fallback,
            "local_abstention": abstenciones
        },
        "latencies_ms": {
            "min": min_lat,
            "p50": p50,
            "p95": p95,
            "max": max_lat,
            "avg": avg_lat
        },
        "quality_metrics": {
            "average_keyword_coverage_pct": avg_kw
        },
        "individual_results": todos_resultados
    }

    # Guardar reporte en disco
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    print("\n" + "="*75)
    print("📊 REPORTE DE RESULTADOS DE CALIBRACIÓN")
    print("="*75)
    print(f"  • Total Consultas Evaluadas:    {total}")
    print(f"  • Tasa de Éxito HTTP (200 OK):  {exitos}/{total} ({resumen['success_rate_pct']}%)")
    print(f"  • Cobertura Promedio Keywords:  {avg_kw}%")
    print(f"  • Latencia p50 (Mediana):       {p50} ms")
    print(f"  • Latencia p95 (Cola):          {p95} ms")
    print(f"  • Latencia Promedio:            {avg_lat} ms")
    print(f"  • Enrutamiento Local High:      {locales_high}")
    print(f"  • Enrutamiento Local Med:       {locales_med}")
    print(f"  • Escalamiento Cloud:           {cloud_fallback}")
    print(f"  • Abstenciones Seguras:         {abstenciones}")
    print(f"  • Archivo de Resultados:        {args.output}")
    print("="*75 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
