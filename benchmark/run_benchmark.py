"""
Runner de Calibración: Ejecuta el Benchmark de 50 Preguntas Técnicas sobre el Open Hybrid RAG Gateway
Calcula métricas reales: latencias p50/p95, tasa de errores, enrutamiento y auditoría ASSERT.
"""
import os
import sys
import io
import json
import time
import asyncio
import numpy as np
import httpx

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BENCHMARK_FILE = os.path.join(os.path.dirname(__file__), "50_technical_benchmark.json")
GATEWAY_URL = "http://127.0.0.1:8000/api/v1/orchestrate"

async def ejecutar_pregunta(client: httpx.AsyncClient, q_id: str, question: str) -> dict:
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            GATEWAY_URL,
            json={"query": question, "audit_assert": True},
            timeout=60.0
        )
        elapsed = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": q_id,
                "question": question,
                "status": "OK",
                "route": data.get("route_taken"),
                "source": data.get("source"),
                "latency_ms": round(elapsed, 2),
                "score": data.get("similarity_score", 0.0),
                "answer_length": len(data.get("answer", "")),
                "audit": data.get("assert_audit", {})
            }
        else:
            return {
                "id": q_id,
                "question": question,
                "status": f"HTTP_{resp.status_code}",
                "error": resp.text,
                "latency_ms": round(elapsed, 2)
            }
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "id": q_id,
            "question": question,
            "status": "ERROR",
            "error": str(e),
            "latency_ms": round(elapsed, 2)
        }

async def main():
    if not os.path.exists(BENCHMARK_FILE):
        print(f"Error: No se encontró el archivo de benchmark en {BENCHMARK_FILE}")
        return

    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("\n" + "="*70)
    print(f"🚀 INICIANDO BENCHMARK DE CALIBRACIÓN: {data.get('title')}")
    print(f"🎯 Total categorías: {len(data.get('categories', []))}")
    print("="*70 + "\n")

    todos_resultados = []
    
    async with httpx.AsyncClient() as client:
        for cat in data.get("categories", []):
            print(f"\n📂 Categoría: {cat['category']}")
            print("-" * 60)
            for q in cat.get("questions", []):
                res = await ejecutar_pregunta(client, q["id"], q["question"])
                todos_resultados.append(res)
                print(f"  [{res['id']}] {res['status']} | Ruta: {res.get('route', 'N/A')} | Latencia: {res['latency_ms']}ms")

    # Métricas estadísticas
    total = len(todos_resultados)
    exitos = sum(1 for r in todos_resultados if r["status"] == "OK")
    locales = sum(1 for r in todos_resultados if "LOCAL" in str(r.get("route", "")))
    escalados = sum(1 for r in todos_resultados if "CLOUD" in str(r.get("route", "")))
    
    latencias = [r["latency_ms"] for r in todos_resultados if r["status"] == "OK"]
    p50 = round(float(np.percentile(latencias, 50)), 2) if latencias else 0
    p95 = round(float(np.percentile(latencias, 95)), 2) if latencias else 0
    avg_latency = round(float(np.mean(latencias)), 2) if latencias else 0

    print("\n" + "="*70)
    print("📊 RESUMEN ESTADÍSTICO DEL BENCHMARK")
    print("="*70)
    print(f"Total Evaluados:   {total}")
    print(f"Respuestas Válidas: {exitos} / {total} ({round((exitos/total)*100, 1)}%)")
    print(f"Resueltos Local:   {locales}")
    print(f"Escalados Cloud:   {escalados}")
    print(f"Latencia Media:    {avg_latency} ms")
    print(f"Latencia p50:      {p50} ms")
    print(f"Latencia p95:      {p95} ms")
    print("="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
