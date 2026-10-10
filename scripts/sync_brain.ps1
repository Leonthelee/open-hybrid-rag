<#
.SYNOPSIS
Sincroniza en caliente todas las notas Markdown de una carpeta local al Open Hybrid RAG Gateway.
Soporta autenticación X-API-Key, remoción de frontmatter YAML e indexación incremental por hash.
#>
param (
    [string]$FolderPath = "./knowledge_base",
    [string]$GatewayUrl = "http://127.0.0.1:8000/api/v1/ingest",
    [string]$ApiKey = $env:API_KEY
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🧠 Open Hybrid RAG - Incremental Knowledge Sync" -ForegroundColor Cyan
Write-Host "📂 Origen:  $FolderPath" -ForegroundColor Cyan
Write-Host "🌐 Destino: $GatewayUrl" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $FolderPath)) {
    Write-Host "❌ Error: La carpeta '$FolderPath' no existe." -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $FolderPath -Filter "*.md" -Recurse
Write-Host "📦 Encontradas $($files.Count) notas Markdown para procesar..." -ForegroundColor Yellow

$indexed = 0
$errors = 0
$resolvedBase = (Resolve-Path $FolderPath).Path

foreach ($file in $files) {
    $rawContent = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($rawContent)) { continue }

    # Eliminar frontmatter YAML si está presente (delimitado por --- inicial)
    $cleanContent = $rawContent
    if ($cleanContent -match "(?s)^---\r?\n.*?\r?\n---\r?\n(.*)$") {
        $cleanContent = $matches[1]
    }
    $cleanContent = $cleanContent.Trim()
    if ([string]::IsNullOrWhiteSpace($cleanContent)) { continue }

    # Calcular hash SHA-256 del contenido limpio
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($cleanContent)
    $hash = -join ($sha.ComputeHash($bytes) | ForEach-Object { "{0:x2}" -f $_ })

    $relPath = $file.FullName.Substring($resolvedBase.Length).TrimStart("\", "/")
    $docId = ($relPath -replace '[^a-zA-Z0-9._-]', '_') -replace '\.md$', ''

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
        "Content-Type" = "application/json"
    }
    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        $headers["X-API-Key"] = $ApiKey
    }

    try {
        $res = Invoke-RestMethod -Uri $GatewayUrl -Method Post -Body $body -Headers $headers -TimeoutSec 45
        Write-Host "  ✅ [$($res.doc_id)] Indexado exitosamente ($($res.vector_dims) dims)" -ForegroundColor Green
        $indexed++
    } catch {
        Write-Host "  ❌ Error indexando $($relPath): $_" -ForegroundColor Red
        $errors++
    }
}

Write-Host "`n🎉 Sincronización finalizada: $indexed indexadas, $errors errores de $($files.Count) notas." -ForegroundColor Cyan
