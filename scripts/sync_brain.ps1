<#
.SYNOPSIS
Sincroniza en caliente todas las notas Markdown de una carpeta local al Open Hybrid RAG Gateway.
Soporta autenticación X-API-Key, validación de códigos HTTP y slugs de ruta jerárquica para evitar colisiones.
#>
param (
    [string]$FolderPath = "./knowledge_base",
    [string]$GatewayUrl = "http://127.0.0.1:8000/api/v1/ingest",
    [string]$ApiKey = $env:API_KEY
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🧠 Open Hybrid RAG - Hot Knowledge Sync" -ForegroundColor Cyan
Write-Host "📂 Origen:  $FolderPath" -ForegroundColor Cyan
Write-Host "🌐 Destino: $GatewayUrl" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $FolderPath)) {
    Write-Host "❌ Error: La carpeta '$FolderPath' no existe." -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $FolderPath -Filter "*.md" -Recurse
Write-Host "📦 Encontradas $($files.Count) notas Markdown para indexar..." -ForegroundColor Yellow

$indexed = 0
$errors = 0

$resolvedBase = (Resolve-Path $FolderPath).Path

foreach ($file in $files) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content)) { continue }

    # Calcular ruta relativa y slug único para evitar colisiones entre subcarpetas
    $relPath = $file.FullName.Substring($resolvedBase.Length).TrimStart("\", "/")
    $docId = ($relPath -replace '[^a-zA-Z0-9._-]', '_') -replace '\.md$', ''

    $body = @{
        doc_id = $docId
        text = $content
        doc_type = "document"
        metadata = @{
            relative_path = $relPath
            filename = $file.Name
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
