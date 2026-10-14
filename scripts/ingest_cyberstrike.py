"""
scripts/ingest_cyberstrike.py
Script de ingesta automatizada del corpus defensivo de CyberStrike
(OWASP API Top 10, OWASP WSTG, MITRE ATT&CK, CIS Hardening)
en Open Hybrid RAG Gateway y Segundo Cerebro.
"""
import os
import sys
import json
import time
import asyncio
import httpx

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# Asegurar importación de módulos del proyecto
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
src_dir = os.path.join(ROOT_DIR, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import config
from vector_guard import VectorGuard
from local_engine import LocalEngine
from second_brain import SecondBrain

CORPUS_CYBERSTRIKE = [
    {
        "doc_id": "sec-owasp-api-top10-2023",
        "doc_type": "document",
        "text": """# OWASP API Security Top 10 (2023) - Marco y Controles Defensivos

1. API1:2023 Broken Object Level Authorization (BOLA):
   - Falla: El usuario manipula IDs en la URL (/api/users/{id}) y accede a registros ajenos sin validación de propiedad.
   - Mitigación: Validar siempre en backend que el sujeto autenticado en el JWT/Sesión sea el dueño legítimo del objeto solicitado, usando políticas de autorización a nivel de código o middleware de pertenencia.

2. API2:2023 Broken Authentication:
   - Falla: Mecanismos de autenticación débiles, tokens JWT sin firma o con algoritmo "none", falta de rate limiting en endpoints de login.
   - Mitigación: Forzar rotación de claves asimétricas (RS256/EdDSA), usar secretos seguros de longitud suficiente, comparar hashes en tiempo constante (secrets.compare_digest) y aplicar rate limiting estricto con Leaky Bucket o Redis.

3. API3:2023 Broken Object Property Level Authorization (BOPLA / Mass Assignment):
   - Falla: Exposición o manipulación de campos sensibles (ej. is_admin, role) al permitir payloads de entrada sin filtrar que se bindean directo a la entidad.
   - Mitigación: Usar DTOs explícitos (Pydantic con extra="forbid"), listas blancas de campos modificables y nunca mapear el JSON directo al modelo de base de datos ORM.

4. API4:2023 Unrestricted Resource Consumption:
   - Falla: Peticiones masivas sin límites de tamaño, ausencia de timeouts en queries o falta de paginación con límite superior (DoS por agotamiento de RAM o CPU).
   - Mitigación: Límites estrictos de tamaño de payload (max_length), paginación obligatoria con max_limit fijado en backend, límites de cuota y rate-limiting por IP y por API Key.

5. API5:2023 Broken Function Level Authorization (BFLA):
   - Falla: Usuarios estándar invocando endpoints administrativos (ej. DELETE /api/admin/users) confiando solo en que la UI oculte los botones.
   - Mitigación: Control de acceso basado en roles (RBAC) o atributos (ABAC) verificado explícitamente en cada función o decorador del endpoint.

6. API6:2023 Unrestricted Access to Sensitive Business Flows:
   - Falla: Automatización masiva de flujos críticos (compras en masa, scraping de precios, reserva masiva de cupos).
   - Mitigación: Detección de patrones anómalos, captcha en flujos sensibles y huella digital de cliente con bloqueo temporal.

7. API7:2023 Server Side Request Forgery (SSRF):
   - Falla: La API recibe URLs de usuario y descarga recursos internos (metadata de AWS/GCP 169.254.169.254 o servicios en localhost).
   - Mitigación: Lista blanca de dominios e IPs externas permitidas, resolución DNS previa para descartar rangos RFC 1918 / loopback y deshabilitar redirecciones automáticas HTTP.

8. API8:2023 Security Misconfiguration:
   - Falla: Exposición de stack traces en respuestas 500, cabeceras CORS permisivas (Access-Control-Allow-Origin: * con credenciales), endpoints de debug activos en producción.
   - Mitigación: Cabeceras de seguridad estrictas (HSTS, Content-Security-Policy), deshabilitar Swagger/OpenAPI en producción si no es público, y capturar todas las excepciones no controladas con handlers genéricos.

9. API9:2023 Improper Inventory Management:
   - Falla: APIs deprecadas (v1, v2) expuestas en endpoints vivos sin parches de seguridad, o documentación desactualizada.
   - Mitigación: Desmantelar gateways obsoletos, versionado estricto y auditoría periódica de rutas con escáneres OpenAPI.

10. API10:2023 Unsafe Consumption of APIs:
    - Falla: Confiar ciegamente en datos provenientes de APIs de terceros o microservicios internos.
    - Mitigación: Validar y sanitizar toda respuesta externa antes de procesarla en la lógica de negocio.""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "OWASP_API_2023",
            "tags": ["owasp", "api", "security", "fastapi"]
        }
    },
    {
        "doc_id": "sec-owasp-wstg-web-testing",
        "doc_type": "document",
        "text": """# OWASP Web Security Testing Guide (WSTG v4.2) - Técnicas de Detección y Defensa

1. WSTG-INPV (Input Validation Testing):
   - Sanitización y parametrización de entradas para prevenir SQL Injection, XSS reflected/stored y Command Injection.
   - Todo input debe pasar por validación de tipo, longitud, formato y rango (Type, Length, Format, Range - TLFR).

2. WSTG-ATHN (Authentication Testing):
   - Evaluación de políticas de contraseñas, políticas de bloqueo tras intentos fallidos y protección contra credential stuffing.
   - Requerir MFA en canales críticos y almacenar contraseñas exclusivamente con Argon2id o bcrypt con costo adaptativo.

3. WSTG-SESS (Session Management):
   - Cookies de sesión con flags: Secure, HttpOnly, SameSite=Strict/Lax.
   - Expiración absoluta y por inactividad; invalidación simultánea en servidor y cliente al hacer logout.

4. WSTG-CRYP (Cryptography Testing):
   - Desactivación estricta de TLS 1.0/1.1; forzar TLS 1.3 con suites de cifrado AEAD (GCM o ChaCha20-Poly1305).
   - Verificación de certificados X.509 y prevención de downgrade attacks mediante HSTS (Strict-Transport-Security: max-age=31536000; includeSubDomains; preload).""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "OWASP_WSTG",
            "tags": ["owasp", "wstg", "pentesting", "defensive"]
        }
    },
    {
        "doc_id": "sec-mitre-attack-enterprise-mitigations",
        "doc_type": "document",
        "text": """# MITRE ATT&CK Enterprise - Catálogo de Controles de Mitigación Defensiva

1. M1042 - Disable or Remove Feature or Program:
   - Principio de superficie de ataque mínima. Deshabilitar puertos, intérpretes (ej. PowerShell no firmado), APIs no utilizadas y servicios de depuración en entornos productivos.

2. M1038 - Execution Prevention:
   - Uso de AppLocker, listas de ejecución de binarios permitidos (WDAC en Windows) y no permitir la ejecución de scripts arbitrarios desde directorios temporales (%TEMP%, /tmp).

3. M1032 - Multi-Factor Authentication (MFA):
   - Obligatorio en todos los puntos de entrada perimetrales (SSH, VPN, RDP, portales web administrativos). Preferir FIDO2 / WebAuthn sobre SMS o OTP básicos.

4. M1026 - Privileged Account Management:
   - Aislar cuentas de administración de dominio de cuentas de uso diario. No usar cuentas con privilegios de root/administrador para levantar contenedores o servicios daemon.

5. M1030 - Network Segmentation:
   - Segmentar zonas de base de datos, servidores de aplicaciones y redes de gestión mediante firewalls con inspección de estado. Los microservicios solo deben comunicarse por puertos y protocolos estrictamente definidos.

6. M1047 - Audit & Telemetry Logging:
   - Registro centralizado e inmutable de eventos de seguridad (Sysmon, auditd, logs HTTP de acceso con latencia y código de estado). Alerta automatizada ante ráfagas de 401/403 o accesos a endpoints no mapeados.""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "MITRE_ATTACK",
            "tags": ["mitre", "enterprise", "mitigations", "defense"]
        }
    },
    {
        "doc_id": "sec-cis-docker-container-hardening",
        "doc_type": "document",
        "text": """# CIS Benchmarks - Hardening de Contenedores y Entornos Docker

1. Ejecución sin privilegios de root (Non-Root User):
   - Regla: Nunca ejecutar procesos de contenedor como UID 0 (root).
   - Implementación Dockerfile: 'USER 10001:10001' antes del ENTRYPOINT/CMD.

2. Sistema de archivos de solo lectura (Read-Only Filesystem):
   - Montar el contenedor con '--read-only' o en compose 'read_only: true'.
   - Si la aplicación necesita escribir logs o temporales, mapear volúmenes tmpfs específicos ('tmpfs: /tmp:noexec,nosuid,size=64m').

3. Eliminación de Linux Capabilities (Drop Capabilities):
   - Por defecto Docker otorga capacidades que no siempre son requeridas.
   - Hardening Compose:
     cap_drop:
       - ALL
     cap_add:
       - NET_BIND_SERVICE # Solo si requiere enlace a puertos bajos

4. Límites de Recursos (Prevenir DoS local):
   - Configurar límites explícitos de CPU y memoria en cada contenedor:
     deploy:
       resources:
         limits:
           cpus: '2.0'
           memory: 2048M

5. Prevención de Escalamiento de Privilegios:
   - Agregar 'security_opt: [ "no-new-privileges:true" ]' para impedir que binarios SUID dentro del contenedor eleven privilegios.""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "CIS_BENCHMARKS",
            "tags": ["cis", "docker", "containers", "hardening"]
        }
    },
    {
        "doc_id": "sec-cis-linux-os-hardening",
        "doc_type": "document",
        "text": """# CIS Linux Benchmark - Hardening de Sistema Operativo y Servidores Host

1. Hardening de Parámetros de Kernel y Red (/etc/sysctl.d/99-cis.conf):
   - Mitigación SYN Flood: net.ipv4.tcp_syncookies = 1
   - Prevención de Spoofing e IP Forwarding: net.ipv4.ip_forward = 0, net.ipv4.conf.all.rp_filter = 1
   - Deshabilitar ICMP Redirects: net.ipv4.conf.all.accept_redirects = 0, net.ipv6.conf.all.accept_redirects = 0
   - Protección de Enlaces Simbólicos y Memoria: fs.protected_hardlinks = 1, fs.protected_symlinks = 1, fs.suid_dumpable = 0, kernel.randomize_va_space = 2 (ASLR completo).

2. Hardening de SSH Daemon (/etc/ssh/sshd_config):
   - Deshabilitar acceso root directo: PermitRootLogin no
   - Deshabilitar autenticación por contraseñas débiles: PasswordAuthentication no
   - Límite de intentos: MaxAuthTries 3
   - Criptografía moderna: KexAlgorithms curve25519-sha256, Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com
   - Deshabilitar X11 y Agentes: X11Forwarding no, AllowTcpForwarding no.

3. Sistema de Archivos, Permisos y Particionado:
   - Máscara de permisos predeterminada: umask 027 en /etc/profile y /etc/bash.bashrc
   - Protección de particiones temporales: /tmp y /dev/shm montados con nodev, nosuid, noexec
   - Permisos estrictos de archivos críticos: chmod 0600 /etc/shadow, chmod 0644 /etc/passwd.

4. Auditoría Inmutable y Cortafuegos:
   - Servicio auditd activo con reglas inmutables (-e 2) auditando cambios en /etc/passwd, llamadas execve y elevaciones sudo.
   - Cortafuegos de host (nftables / iptables) con política por defecto DROP en INPUT y FORWARD.""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "CIS_BENCHMARKS",
            "tags": ["cis", "linux", "kernel", "ssh", "hardening"]
        }
    },
    {
        "doc_id": "sec-cis-kubernetes-cloud-native",
        "doc_type": "document",
        "text": """# CIS Kubernetes Benchmark - Hardening de Clústeres y Entornos Cloud Native

1. Hardening del Control Plane y API Server:
   - Control de acceso RBAC estricto: --authorization-mode=Node,RBAC
   - Deshabilitar acceso anónimo: --anonymous-auth=false
   - Deshabilitar profiling de depuración: --profiling=false
   - Cifrado de datos en reposo para etcd mediante EncryptionConfiguration con proveedor KMS / AES-GCM (secretos cifrados en disco).

2. Pod Security Standards (Perfil Restringido / Restricted):
   - Forzar no-root: securityContext.runAsNonRoot: true, securityContext.runAsUser: 10001
   - Sistema de archivos inmutable: securityContext.readOnlyRootFilesystem: true
   - Prohibir escalada de privilegios: securityContext.allowPrivilegeEscalation: false
   - Eliminación total de capacidades: securityContext.capabilities.drop: ["ALL"]
   - Perfil Seccomp estricto: seccompProfile.type: RuntimeDefault.

3. Aislamiento de Red (Network Policies):
   - Política predeterminada de aislamiento DefaultDeny para Ingress y Egress en todos los namespaces con cargas de trabajo de producción.
   - Apertura explícita punto a punto solo hacia pods y puertos estrictamente requeridos.

4. Gestión de Identidad de Cargas (Service Accounts):
   - Deshabilitar inyección automática de tokens si el pod no interactúa con la API de Kubernetes:
     automountServiceAccountToken: false.""",
        "metadata": {
            "source": "cyberstrike_corpus",
            "framework": "CIS_BENCHMARKS",
            "tags": ["cis", "kubernetes", "cloud_native", "k8s", "hardening"]
        }
    }
]

async def check_api_server(gateway_url: str) -> bool:
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{gateway_url}/health")
            return r.status_code == 200
        except Exception:
            return False

async def ingest_via_api(gateway_url: str, api_key: str):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    print(f"📡 Ingestando vía API HTTP ({gateway_url}/api/v1/ingest/batch)...")
    payload = {"documents": CORPUS_CYBERSTRIKE}
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{gateway_url}/api/v1/ingest/batch", json=payload, headers=headers)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            print(f"✅ Ingesta por API completada en {elapsed_ms:.2f} ms:")
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
            return True
        else:
            print(f"❌ Error en API ({r.status_code}): {r.text}")
            return False

async def ingest_direct_engine():
    print("⚙️ Ingestando directamente a través de VectorGuard + LocalEngine + SecondBrain...")
    vector_guard = VectorGuard(
        high_threshold=config.RAG_CERTAINTY_THRESHOLD,
        min_threshold=config.RAG_MIN_THRESHOLD
    )
    # Cargar persistencia previa si existe
    vector_guard.load_from_disk(config.INDEX_STORAGE_PATH)

    local_engine = LocalEngine()
    second_brain = SecondBrain(base_path=config.SECOND_BRAIN_PATH)

    prepared_docs = []
    for doc in CORPUS_CYBERSTRIKE:
        print(f"   Generando vector para: {doc['doc_id']}...")
        t0 = time.perf_counter()
        vec = await local_engine.get_embedding(doc["text"])
        elapsed = (time.perf_counter() - t0) * 1000
        if not vec:
            print(f"   ⚠️ Falló embedding para {doc['doc_id']}")
            continue
        print(f"   ✓ Vector obtenido ({len(vec)} dims) en {elapsed:.2f} ms")

        prepared_docs.append({
            "doc_id": doc["doc_id"],
            "text": doc["text"],
            "vector": vec,
            "doc_type": doc["doc_type"],
            "metadata": doc.get("metadata")
        })

        # Sincronizar en Markdown para el Segundo Cerebro (Obsidian)
        second_brain.save_interaction(
            query=f"Guía y controles de seguridad para {doc['doc_id']}",
            answer=doc["text"],
            source=f"cyberstrike_{doc.get('metadata', {}).get('framework', 'corpus')}",
            latency_ms=elapsed
        )

    added = vector_guard.add_documents_batch(prepared_docs)
    vector_guard.save_to_disk(config.INDEX_STORAGE_PATH)
    print(f"\n✅ Total documentos indexados y guardados en disco: {added}")
    print(f"📂 Archivo vectorial guardado en: {config.INDEX_STORAGE_PATH}")
    print(f"📂 Notas Markdown sincronizadas en: {config.SECOND_BRAIN_PATH}")
    return vector_guard, local_engine

async def verify_similarity(vector_guard: VectorGuard, local_engine: LocalEngine):
    print("\n🔍 Verificando recuperación True Hybrid RAG con consulta de prueba:")
    query = "¿Cómo mitigar OWASP API3:2023 Broken Object Property Level Authorization (BOPLA)?"
    print(f"Query: \"{query}\"")
    
    t0 = time.perf_counter()
    q_vec = await local_engine.get_embedding(query)
    embed_ms = (time.perf_counter() - t0) * 1000
    
    t1 = time.perf_counter()
    route, doc, score = vector_guard.hybrid_match(query_text=query, query_vector=q_vec)
    search_ms = (time.perf_counter() - t1) * 1000

    print(f"   Ruta Matemática: {route}")
    print(f"   Similitud / Score Efectivo: {score:.4f}")
    print(f"   Latencia Embedding: {embed_ms:.2f} ms | Búsqueda Híbrida: {search_ms:.3f} ms")
    if doc:
        print(f"   Doc Recuperado: {doc.get('id')}")
        if "hybrid_metrics" in doc:
            print(f"   Métricas Híbridas: {doc.get('hybrid_metrics')}")
        print(f"   Primeras líneas: {doc.get('text', '')[:250]}...")
    print("=" * 60)

async def main():
    gateway_url = f"http://{config.HOST}:{config.PORT}"
    server_online = await check_api_server(gateway_url)

    if server_online:
        print(f"🟢 Servidor Open Hybrid RAG detectado en línea en {gateway_url}")
        success = await ingest_via_api(gateway_url, config.API_KEY)
        if not success:
            print("Fallback a ingesta directa...")
            vg, le = await ingest_direct_engine()
            await verify_similarity(vg, le)
    else:
        print(f"⚪ Servidor no detectado en {gateway_url}. Ejecutando ingesta directa local.")
        vg, le = await ingest_direct_engine()
        await verify_similarity(vg, le)

if __name__ == "__main__":
    asyncio.run(main())
