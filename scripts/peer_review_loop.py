"""
Peer Review Loop (Bucle de Consenso y Debate Multi-Agente LLM-to-LLM)
Automatiza la auditoría adversaria continua entre Antigravity y ChatGPT / Claude / Gemini.

Uso:
  python scripts/peer_review_loop.py --reviewer openai --model gpt-4o
  python scripts/peer_review_loop.py --reviewer gemini --model gemini-2.0-flash
  python scripts/peer_review_loop.py --reviewer ollama --model qwen2.5:14b
"""
import os
import sys
import io
import json
import time
import argparse
import asyncio
import subprocess
from typing import Dict, Any, List, Optional
import httpx
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

load_dotenv()

TARGET_DIRECTORIES = ["src", "tests", "benchmark", "scripts"]
TARGET_FILES = ["Dockerfile", "docker-compose.yml", "requirements.txt", "README.md"]
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SYSTEM_AUDITOR_PROMPT = """Eres Astra / Auditor Senior Adversarial de Arquitectura de Software y Seguridad.
Tu trabajo es auditar el código fuente del repositorio Open Hybrid RAG (Gateway de RAG híbrido Local-First + Multi-Cloud).

DEBES seguir estrictamente el siguiente PROTOCOLO DE VERIFICACIÓN:
1. Sé implacable y busca fallos reales: condiciones de carrera, fugas de privacidad, esquemas rotos, cuellos de botella de memoria/disco, inconsistencias en el caché y seguridad en endpoints.
2. Si encuentras problemas, repórtalos con severidad (Alta / Media / Baja), archivo, línea aproximada y la solución recomendada.
3. Si el código cumple rigurosamente con estándares de producción y no tiene fallos lógicos ni de seguridad, establece consensus_approved = true.

Responde EXCLUSIVAMENTE en formato JSON válido con este esquema:
{
  "consensus_approved": false,
  "confidence_score": 9.2,
  "overall_verdict": "Resumen ejecutivo del estado del código",
  "findings": [
    {
      "id": "SEC-01",
      "priority": "Alta",
      "file": "src/main.py",
      "problem": "Descripción exacta del fallo o vulnerabilidad",
      "evidence": "Línea o bloque de código afectado",
      "recommended_fix": "Solución arquitectónica o código sugerido"
    }
  ],
  "adversarial_tests_suggested": [
    "Descripción de un test para intentar romper el sistema"
  ]
}
"""

def collect_codebase() -> str:
    """Empaqueta los archivos relevantes del repositorio en un snapshot estructurado."""
    bundle = []
    
    # Archivos sueltos en raíz
    for fname in TARGET_FILES:
        fpath = os.path.join(ROOT_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            bundle.append(f"### FILE: {fname}\n```\n{content}\n```\n")

    # Archivos en directorios clave
    for folder in TARGET_DIRECTORIES:
        folder_path = os.path.join(ROOT_DIR, folder)
        if not os.path.exists(folder_path):
            continue
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.endswith((".py", ".sh", ".ps1", ".json", ".yml", ".yaml")) and not file.endswith(".pyc"):
                    rel_path = os.path.relpath(os.path.join(root, file), ROOT_DIR)
                    abs_path = os.path.join(root, file)
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    bundle.append(f"### FILE: {rel_path}\n```\n{content}\n```\n")

    return "\n".join(bundle)

def run_local_unit_tests() -> Tuple[bool, str]:
    """Ejecuta la suite de pruebas local y captura la salida."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "tests"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        success = (proc.returncode == 0)
        output = proc.stdout + "\n" + proc.stderr
        return success, output.strip()
    except Exception as e:
        return False, str(e)

class PeerReviewClient:
    def __init__(self, provider: str, model: str, api_key: str, base_url: Optional[str] = None):
        self.provider = provider.lower().strip()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    async def audit(self, codebase_text: str, test_output: str) -> Dict[str, Any]:
        user_message = f"""Por favor audita el siguiente estado actual del repositorio Open Hybrid RAG.

[ESTADO DE TESTS LOCALES]:
{test_output}

[CÓDIGO FUENTE DEL REPOSITORIO]:
{codebase_text}
"""
        async with httpx.AsyncClient(timeout=120.0) as client:
            if self.provider == "openai":
                headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                url = "https://api.openai.com/v1/chat/completions"
                payload = {
                    "model": self.model or "gpt-4o",
                    "messages": [
                        {"role": "system", "content": SYSTEM_AUDITOR_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    "response_format": {"type": "json_object"}
                }
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 200:
                    raw = r.json()["choices"][0]["message"]["content"]
                    return json.loads(raw)
                raise Exception(f"OpenAI HTTP {r.status_code}: {r.text}")

            elif self.provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model or 'gemini-2.0-flash'}:generateContent"
                headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
                full_prompt = f"{SYSTEM_AUDITOR_PROMPT}\n\n{user_message}"
                payload = {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"}
                }
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 200:
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(raw)
                raise Exception(f"Gemini HTTP {r.status_code}: {r.text}")

            elif self.provider == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": self.model or "claude-3-5-sonnet-20241022",
                    "max_tokens": 4096,
                    "system": SYSTEM_AUDITOR_PROMPT,
                    "messages": [{"role": "user", "content": user_message}]
                }
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 200:
                    raw = r.json()["content"][0]["text"]
                    # Limpiar wrapper si existe
                    if "```json" in raw:
                        raw = raw.split("```json")[1].split("```")[0]
                    return json.loads(raw.strip())
                raise Exception(f"Claude HTTP {r.status_code}: {r.text}")

            elif self.provider == "ollama":
                endpoint = self.base_url or "http://127.0.0.1:11434/api/chat"
                payload = {
                    "model": self.model or "qwen2.5:14b",
                    "messages": [
                        {"role": "system", "content": SYSTEM_AUDITOR_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    "format": "json",
                    "stream": False
                }
                r = await client.post(endpoint, json=payload)
                if r.status_code == 200:
                    raw = r.json()["message"]["content"]
                    return json.loads(raw)
                raise Exception(f"Ollama HTTP {r.status_code}: {r.text}")

            else:
                raise ValueError(f"Proveedor '{self.provider}' no soportado.")

async def main():
    parser = argparse.ArgumentParser(description="Peer Review Loop: Debate Multi-Agente LLM-to-LLM")
    parser.add_argument("--reviewer", choices=["openai", "gemini", "anthropic", "ollama"], default="openai")
    parser.add_argument("--model", default="", help="Nombre del modelo del auditor (ej. gpt-4o, gemini-2.0-flash, claude-3-5-sonnet-20241022)")
    parser.add_argument("--api-key", default="", help="API Key si no está en variables de entorno")
    parser.add_argument("--output", default="benchmark/peer_review_report.json", help="Ruta para guardar el reporte JSON")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        if args.reviewer == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        elif args.reviewer == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("CLOUD_API_KEY", "")
        elif args.reviewer == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if args.reviewer != "ollama" and not api_key:
        print(f"\n❌ Error: No se proporcionó API Key para el auditor '{args.reviewer}'.")
        print(f"   Por favor pasa --api-key <TU_KEY> o configúrala en .env (ej. OPENAI_API_KEY=sk-...).")
        return

    print("\n" + "="*75)
    print("🤖 INICIANDO BUCLE DE DEBATE Y REVISIÓN POR PARES (PEER REVIEW LOOP)")
    print(f"🎯 Auditor Externo: {args.reviewer.upper()} | Modelo: {args.model or 'Default'}")
    print("="*75)

    # 1. Ejecutar tests locales primero
    print("\n[Paso 1/3] 🧪 Ejecutando suite de pruebas locales de control...")
    tests_ok, test_output = run_local_unit_tests()
    print(f"  • Estado Tests Locales: {'✅ EN VERDE' if tests_ok else '❌ CON ERRORES'}")

    # 2. Empaquetar el codebase
    print("\n[Paso 2/3] 📦 Empaquetando snapshot completo del repositorio...")
    codebase = collect_codebase()
    print(f"  • Tamaño del snapshot: {len(codebase)} caracteres empaquetados.")

    # 3. Enviar al auditor
    print(f"\n[Paso 3/3] 🛰️ Consultando a la API de {args.reviewer.upper()} para auditoría adversarial...")
    client = PeerReviewClient(args.reviewer, args.model, api_key)
    
    t0 = time.perf_counter()
    try:
        report = await client.audit(codebase, test_output)
        elapsed = time.perf_counter() - t0
        print(f"  • Respuesta recibida en {elapsed:.2f}s.")
    except Exception as e:
        print(f"\n❌ Falló la consulta con el auditor: {e}")
        return

    # Guardar reporte
    out_path = os.path.join(ROOT_DIR, args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Imprimir resumen de debate
    print("\n" + "="*75)
    print("📋 DICTAMEN DEL AUDITOR EXTERNO")
    print("="*75)
    print(f"  • Consenso Aprobado:  {'✅ SÍ (0 observaciones bloqueantes)' if report.get('consensus_approved') else '🛑 NO (Requiere ajustes)'}")
    print(f"  • Veredicto General:  {report.get('overall_verdict')}")
    print(f"  • Confianza:          {report.get('confidence_score', 'N/A')}/10")
    print("-" * 75)

    findings = report.get("findings", [])
    if not findings:
        print("  🎉 ¡Cero fallos detectados! El código fue calificado como impecable para producción.")
    else:
        print(f"  🔍 Total Hallazgos Detectados: {len(findings)}\n")
        for idx, f in enumerate(findings, 1):
            print(f"  [{f.get('priority', 'Info')}] {f.get('id', f'FIND-{idx}')}: {f.get('problem')}")
            print(f"     📁 Archivo:   {f.get('file')}")
            print(f"     📍 Evidencia: {f.get('evidence')}")
            print(f"     💡 Solución:  {f.get('recommended_fix')}\n")

    scenarios = report.get("adversarial_tests_suggested", [])
    if scenarios:
        print("-" * 75)
        print("🧪 Escenarios Adversarios Sugeridos:")
        for s in scenarios:
            print(f"  • {s}")

    print(f"\n💾 Reporte completo guardado en: {out_path}\n" + "="*75 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
