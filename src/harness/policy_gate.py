"""
src/harness/policy_gate.py
Caja 4 del Arnés: Policy Gate (El Cortafuegos de Comandos).
Clasifica y filtra llamadas a herramientas y comandos de terminal
antes de que toquen el sistema operativo.
"""
import re
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class PolicyAction(str, Enum):
    ALLOW = "ALLOW"                    # Seguro: auto-aprobado (lectura, status)
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"  # Mutación: pausa y espera OK humano
    DENY = "DENY"                      # Destructivo / Peligroso: bloqueado de raíz

class PolicyVerdict(BaseModel):
    action: PolicyAction
    tool_name: str
    command_or_target: str
    reason: str
    risk_level: str = Field("LOW", description="LOW | MEDIUM | CRITICAL")

class PolicyGate:
    def __init__(self):
        # 🔴 Lista negra estricta (Bloqueo absoluto inmediato)
        self.prohibited_patterns = [
            r"\brm\s+-(?:r|f|rf|fr)\s+[/~]",              # rm -rf en raíz o home
            r"\bformat\s+[a-zA-Z]:",                     # formateo de discos en Windows
            r"\bdrop\s+(?:table|database|schema)\b",     # borrado masivo SQL
            r"\btruncate\s+table\b",                     # truncado SQL
            r"\bcurl\b.*\|\s*(?:bash|sh|powershell|pwsh)", # ejecución remota sin verificar
            r"\bkill\s+-9\s+1\b",                        # matar init/PID 1
            r"\bchmod\s+-R\s+777\b",                     # permisos inseguros masivos
            r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;",    # fork bomb
            r">\s*/dev/sd[a-z]",                         # sobrescritura directa de bloques
        ]
        
        # 🟡 Lista de mutaciones (Requiere aprobación humana)
        self.mutation_tools = {
            "write_file", "edit_file", "delete_file", "git_commit", "git_push",
            "deploy_service", "apply_migration"
        }
        
        # 🟢 Lista de lecturas seguras (Auto-aprobadas)
        self.safe_read_tools = {
            "read_file", "search_docs", "git_status", "git_diff", "list_dir",
            "search_web", "check_health"
        }

    def evaluate(self, tool_name: str, payload: Dict[str, Any]) -> PolicyVerdict:
        """
        Evalúa una llamada a herramienta y emite un veredicto determinista.
        """
        # Extraer comando o archivo objetivo del payload
        target = str(payload.get("command") or payload.get("path") or payload.get("file") or "")

        # 1. Chequeo de patrones destructivos en texto o comando
        full_text_to_scan = f"{tool_name} {target} {str(payload)}".lower()
        for pattern in self.prohibited_patterns:
            if re.search(pattern, full_text_to_scan, re.IGNORECASE):
                return PolicyVerdict(
                    action=PolicyAction.DENY,
                    tool_name=tool_name,
                    command_or_target=target,
                    reason=f"Comando destructivo bloqueado por política de seguridad (Patrón: {pattern})",
                    risk_level="CRITICAL"
                )

        # 2. Si la herramienta es destructiva conocida
        if tool_name in ("delete_database", "wipe_disk", "destroy_infra"):
            return PolicyVerdict(
                action=PolicyAction.DENY,
                tool_name=tool_name,
                command_or_target=target,
                reason="Herramienta explícitamente clasificada como destructiva no permitida.",
                risk_level="CRITICAL"
            )

        # 3. Chequeo de mutación (escrituras en disco / git / deploys)
        if tool_name in self.mutation_tools or "write" in tool_name or "edit" in tool_name:
            return PolicyVerdict(
                action=PolicyAction.REQUIRE_APPROVAL,
                tool_name=tool_name,
                command_or_target=target,
                reason="La herramienta muta el estado del sistema o código. Requiere confirmación humana.",
                risk_level="MEDIUM"
            )

        # 4. Chequeo de ejecución de comandos genéricos de shell (bash/powershell)
        if tool_name in ("execute_command", "run_shell", "terminal"):
            # Comandos de inspección seguros
            if re.match(r"^(git\s+status|git\s+log|dir|ls|cat|type|pwd|echo)\b", target.strip(), re.IGNORECASE):
                return PolicyVerdict(
                    action=PolicyAction.ALLOW,
                    tool_name=tool_name,
                    command_or_target=target,
                    reason="Comando de inspección seguro auto-aprobado.",
                    risk_level="LOW"
                )
            # Otros comandos de consola van a revisión
            return PolicyVerdict(
                action=PolicyAction.REQUIRE_APPROVAL,
                tool_name=tool_name,
                command_or_target=target,
                reason="Comando de consola que puede alterar el entorno.",
                risk_level="MEDIUM"
            )

        # 5. Herramientas de solo lectura
        if tool_name in self.safe_read_tools or "read" in tool_name or "search" in tool_name:
            return PolicyVerdict(
                action=PolicyAction.ALLOW,
                tool_name=tool_name,
                command_or_target=target,
                reason="Herramienta de solo lectura.",
                risk_level="LOW"
            )

        # Default seguro: si no se conoce la herramienta, pedir aprobación
        return PolicyVerdict(
            action=PolicyAction.REQUIRE_APPROVAL,
            tool_name=tool_name,
            command_or_target=target,
            reason="Herramienta no clasificada en lista blanca. Aplicando principio de precaución.",
            risk_level="MEDIUM"
        )
