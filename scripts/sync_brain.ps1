<#
.SYNOPSIS
Sincroniza en caliente todas las notas Markdown de una carpeta local al Open Hybrid RAG Gateway.
Soporta autenticacion X-API-Key, remocion de frontmatter YAML e indexacion incremental por hash.
#>
param (
    [string]$FolderPath = "./knowledge_base",
    [string]$GatewayUrl = "http://127.0.0.1:8005/api/v1/ingest",
    [string]$ApiKey = $env:API_KEY
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[BRAIN] Open Hybrid RAG - Incremental Knowledge Sync" -ForegroundColor Cyan
Write-Host "[ORIGEN]  $FolderPath" -ForegroundColor Cyan
Write-Host "[DESTINO] $GatewayUrl" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $FolderPath)) {
    Write-Host "[ERROR] La carpeta '$FolderPath' no existe." -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $FolderPath -Filter "*.md" -Recurse
Write-Host "[INFO] Encontradas $($files.Count) notas Markdown para procesar..." -ForegroundColor Yellow

$indexed = 0
$errors = 0
$resolvedBase = (Resolve-Path $FolderPath).Path

foreach ($file in $files) {
    $rawContent = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($rawContent)) { continue }

    # Eliminar frontmatter YAML si esta presente (delimitado por --- inicial)
    $cleanContent = $rawContent
    if ($cleanContent -match "(?s)^---\r?\n.*?\r?\n---\r?\n(.*)$") {
        $cleanContent = $matches[1]
    }
    $cleanContent = $cleanContent.Trim()
    # Sanitizar caracteres de control no imprimibles (excepto salto de linea y tabulacion)
    $cleanContent = $cleanContent -replace "[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", ""
    if ([string]::IsNullOrWhiteSpace($cleanContent)) { continue }

    # Calcular hash SHA-256 del contenido limpio
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($cleanContent)
    $hash = -join ($sha.ComputeHash($bytes) | ForEach-Object { "{0:x2}" -f $_ })

    $relPath = $file.FullName.Substring($resolvedBase.Length).TrimStart("\", "/")
    $docId = ($relPath -replace "\.md$", "") -replace "[^a-zA-Z0-9._-]", "_"

    $body = @{
        doc_id = $docId
        text = $cleanContent
        doc_type = "document"
        metadata = @{
            relative_path = $relPath
            filename = $file.Name
            content_hash = $hash
            updated_at = (Get-Date).ToString("o")
        }
    } | ConvertTo-Json -Depth 5

    $headers = @{
        "Content-Type" = "application/json; charset=utf-8"
    }
    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        $headers["X-API-Key"] = $ApiKey
    }

    try {
        $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        $res = Invoke-RestMethod -Uri $GatewayUrl -Method Post -Body $bodyBytes -Headers $headers -TimeoutSec 45
        Write-Host "  [OK] [$($res.doc_id)] Indexado exitosamente ($($res.vector_dims) dims)" -ForegroundColor Green
        $indexed++
    } catch {
        Write-Host "  [ERROR] Error indexando $($relPath): $_" -ForegroundColor Red
        $errors++
    }
}

Write-Host ""
Write-Host "[COMPLETADO] Sincronizacion finalizada: $indexed indexadas, $errors errores de $($files.Count) notas." -ForegroundColor Cyan
