import sys
import os

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sdk.client import OpenHybridRAGClient

client = OpenHybridRAGClient(base_url="http://127.0.0.1:8005")

print("=" * 70)
print("🚀 STREAMING EN VIVO (SSE) DESDE EL SDK -> OPEN HYBRID RAG GATEWAY")
print("=" * 70)

query = "¿Cuál es el software oficial, la dirección del nuevo servidor y el procedimiento con Cisco Duo MFA para la VPN del MOP?"
print(f"❓ Consulta: '{query}'\n")

for event in client.stream_query(query, allow_cloud_fallback=False):
    ev_type = event.get("event")
    data = event.get("data", {})
    if ev_type == "meta":
        print(f"📡 [META] Ruta: {data.get('route_taken')} | Score: {data.get('similarity_score')} | Fuente: {data.get('source')}")
        print("💬 [RESPUESTA EN VIVO]: ", end="", flush=True)
    elif ev_type == "token":
        sys.stdout.write(data.get("token", ""))
        sys.stdout.flush()
    elif ev_type == "done":
        print(f"\n\n🏁 [DONE] Latencia Total: {data['telemetry']['total_latency_ms']} ms")
        print(f"📂 Guardado en Second Brain: {data.get('second_brain_doc_id')}")
        print("=" * 70)

client.close()
