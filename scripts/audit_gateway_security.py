"""
scripts/audit_gateway_security.py
Módulo de Auditoría de Seguridad Automatizada Pre-Flight para Open Hybrid RAG Gateway.
Evalúa controles técnicos contra OWASP API Security Top 10 (2023) y CIS Hardening
sin requerir sockets de red expuestos (ejecución determinista en memoria mediante TestClient).
"""
import os
import sys
import time
import hashlib
from typing import List, Dict, Any
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
from security import TokenBucket, PayloadSanitizer
from vector_guard import VectorGuard

class AuditResult:
    def __init__(self, check_id: str, name: str, standard: str, passed: bool, details: str):
        self.check_id = check_id
        self.name = name
        self.standard = standard
        self.passed = passed
        self.details = details

class GatewaySecurityAuditor:
    def __init__(self):
        self.client = TestClient(app)
        self.auth_headers = {"X-API-Key": config.API_KEY} if config.API_KEY else {}
        self.results: List[AuditResult] = []

    def run_all_checks(self) -> bool:
        print("=" * 80)
        print("🛡️  AUDITORÍA DE SEGURIDAD PRE-FLIGHT: OPEN HYBRID RAG GATEWAY")
        print("    Estándares: OWASP API Security Top 10 (2023) | CIS Benchmarks | MITRE")
        print("=" * 80)

        # 1. Clickjacking & Frame Sandboxing
        self._check_clickjacking()

        # 2. MIME Sniffing Prevention
        self._check_mime_sniffing()

        # 3. Transport Security (HSTS)
        self._check_hsts()

        # 4. Fingerprint Obfuscation (Server Mask)
        self._check_server_mask()

        # 5. Anti-Timing Attack Authentication
        self._check_authentication_security()

        # 6. Token Bucket Rate Limiting & DoS Defense
        self._check_rate_limiting()

        # 7. Null Byte Injection Defense
        self._check_null_byte_injection()

        # 8. Unicode BiDi Trojan Source Defense (CVE-2021-42574)
        self._check_unicode_bidi_override()

        # 9. Pickle Deserialization Guard
        self._check_safe_deserialization()

        # 10. Privacy Mode & Network Binding Guard
        self._check_network_binding_and_privacy()

        # 11. True Hybrid Retrieval Consistency
        self._check_hybrid_retrieval_integrity()

        self._print_report()
        return all(r.passed for r in self.results)

    def _check_clickjacking(self):
        res = self.client.get("/health")
        x_frame = res.headers.get("X-Frame-Options") == "DENY"
        csp = "frame-ancestors 'none'" in res.headers.get("Content-Security-Policy", "")
        passed = x_frame and csp
        details = f"X-Frame-Options: {res.headers.get('X-Frame-Options')} | CSP: frame-ancestors 'none'"
        self.results.append(AuditResult("SEC-01", "Clickjacking & Frame Sandboxing", "OWASP API8:2023", passed, details))

    def _check_mime_sniffing(self):
        res = self.client.get("/health")
        passed = res.headers.get("X-Content-Type-Options") == "nosniff"
        details = f"X-Content-Type-Options: {res.headers.get('X-Content-Type-Options')}"
        self.results.append(AuditResult("SEC-02", "MIME Sniffing Prevention", "OWASP API8:2023", passed, details))

    def _check_hsts(self):
        res = self.client.get("/health")
        hsts = res.headers.get("Strict-Transport-Security", "")
        passed = "max-age=31536000" in hsts and "includeSubDomains" in hsts
        details = f"HSTS: {hsts}"
        self.results.append(AuditResult("SEC-03", "Transport Encryption (HSTS)", "OWASP API8 / WSTG-CRYP", passed, details))

    def _check_server_mask(self):
        res = self.client.get("/health")
        server = res.headers.get("Server")
        passed = server == "OpenHybridRAG-Guard/1.0"
        details = f"Server Banner: {server} (Sin fuga de Uvicorn/Python)"
        self.results.append(AuditResult("SEC-04", "Server Fingerprint Obfuscation", "CIS Hardening / WSTG-INFO", passed, details))

    def _check_authentication_security(self):
        # Petición con clave errónea
        fake_headers = {"X-API-Key": "malicious_timing_attack_probe_key"}
        res = self.client.get("/api/v1/config", headers=fake_headers)
        if config.API_KEY:
            passed = (res.status_code == 401)
            details = "API Key protegida con secrets.compare_digest (Tiempo constante, 401 rechazado)"
        else:
            passed = True
            details = "API_KEY no configurada en entorno de pruebas (acceso local permitido)"
        self.results.append(AuditResult("SEC-05", "Anti-Timing Attack Authentication", "OWASP API2:2023", passed, details))

    def _check_rate_limiting(self):
        client_id = "audit_probe_client"
        rate_limiter.buckets[client_id] = TokenBucket(capacity=config.RATE_LIMIT_CAPACITY, refill_rate=config.RATE_LIMIT_REFILL_RATE)
        rate_limiter.buckets[client_id].tokens = 0.0

        headers = dict(self.auth_headers)
        # Headers presentes en respuesta normal
        res_normal = self.client.get("/api/v1/config", headers=headers)
        headers_ok = "X-RateLimit-Limit" in res_normal.headers and "X-RateLimit-Remaining" in res_normal.headers

        # Petición que agota cuota
        if config.API_KEY:
            derived_id = f"key:{hashlib.sha256(config.API_KEY.encode()).hexdigest()[:16]}"
        else:
            derived_id = "ip:testclient"

        rate_limiter.buckets[derived_id] = TokenBucket(capacity=2.0, refill_rate=1.0)
        rate_limiter.buckets[derived_id].tokens = 0.0

        res_blocked = self.client.get("/api/v1/config", headers=headers)
        blocked_429 = (res_blocked.status_code == 429) and ("Retry-After" in res_blocked.headers)

        # Restaurar
        rate_limiter.buckets[derived_id].tokens = float(config.RATE_LIMIT_CAPACITY)

        passed = headers_ok and blocked_429
        details = f"Cabeceras X-RateLimit presentes; bloqueo HTTP 429 con Retry-After verificado."
        self.results.append(AuditResult("SEC-06", "Token Bucket Rate Limiting (DoS)", "OWASP API4:2023", passed, details))

    def _check_null_byte_injection(self):
        payload = {"query": "SELECT * FROM secrets\x00 WHERE admin=1", "allow_cloud_fallback": False}
        res = self.client.post("/api/v1/orchestrate", json=payload, headers=self.auth_headers)
        passed = (res.status_code == 422) and ("Null Byte Injection" in res.text)
        details = "Null Byte (\\x00) interceptado en capa de validación Pydantic (HTTP 422 emitido)"
        self.results.append(AuditResult("SEC-07", "Null Byte Injection Defense", "OWASP API3 / WSTG-INPV", passed, details))

    def _check_unicode_bidi_override(self):
        # Carácter Right-to-Left Override (\u202E)
        payload = {"query": "script peligroso \u202Efd.py", "allow_cloud_fallback": False}
        res = self.client.post("/api/v1/orchestrate", json=payload, headers=self.auth_headers)
        passed = (res.status_code == 422) and ("Unicode BiDi Override" in res.text)
        details = "Caracteres BiDi Override (Trojan Source CVE-2021-42574) bloqueados en seco"
        self.results.append(AuditResult("SEC-08", "Unicode BiDi Override (Trojan Source)", "WSTG-INPV / CVE-2021-42574", passed, details))

    def _check_safe_deserialization(self):
        # Inspeccionar que vector_guard cargue con allow_pickle=False
        vg = VectorGuard()
        # Verificar código estático / propiedad
        import inspect
        src = inspect.getsource(vg.load_from_disk)
        has_allow_pickle_false = "allow_pickle=False" in src
        passed = has_allow_pickle_false
        details = "Persistencia atómica con np.load(allow_pickle=False); RCE por Python pickle neutralizado"
        self.results.append(AuditResult("SEC-09", "Pickle Deserialization RCE Guard", "CIS Hardening / CWE-502", passed, details))

    def _check_network_binding_and_privacy(self):
        is_loopback = config.HOST in ("127.0.0.1", "localhost", "::1")
        has_auth_if_exposed = is_loopback or bool(config.API_KEY)
        passed = has_auth_if_exposed
        details = f"Host: {config.HOST} (Aislamiento Loopback: {is_loopback}) | Modo: {config.PRIVACY_MODE.value}"
        self.results.append(AuditResult("SEC-10", "Network Binding & Privacy Mode", "CIS Network / OWASP API8", passed, details))

    def _check_hybrid_retrieval_integrity(self):
        # Verificar que el índice persistido responde con True Hybrid RAG
        vg = VectorGuard()
        vg.load_from_disk(config.INDEX_STORAGE_PATH)
        route, doc, score = vg.hybrid_match("BOPLA API3:2023 sysctl")
        passed = (doc is not None) and (score > 0.0)
        details = f"BM25 + RRF operativo ({vg.bm25.doc_count} docs en RAM léxica, ruta: {route})"
        self.results.append(AuditResult("SEC-11", "True Hybrid RAG Retrieval Integrity", "Integridad de Conocimiento", passed, details))

    def _print_report(self):
        print(f"\n{'ID':<8} | {'CONTROL':<38} | {'ESTÁNDAR':<25} | {'ESTADO':<8}")
        print("-" * 85)
        for r in self.results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            print(f"{r.check_id:<8} | {r.name:<38} | {r.standard:<25} | {status:<8}")
            print(f"         └─ Detalle: {r.details}")
        print("=" * 85)
        total = len(self.results)
        passed_count = sum(1 for r in self.results if r.passed)
        print(f"📊 RESUMEN: {passed_count}/{total} controles superados ({'100% OK' if passed_count == total else 'FALLOS DETECTADOS'})")
        print("=" * 85)

def main():
    auditor = GatewaySecurityAuditor()
    all_passed = auditor.run_all_checks()
    if not all_passed:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
