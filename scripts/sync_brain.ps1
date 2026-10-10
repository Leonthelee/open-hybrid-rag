<#
.SYNOPSIS
Sincroniza en caliente todas las notas Markdown de una carpeta local al Open Hybrid RAG Gateway.
#>
param (
    [string]$FolderPath = "./knowledge_base",
    [string]$GatewayUrl = "http://127.0.0.1:8000/api/v1/ingest"
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🧠 Open Hybrid RAG - Hot Knowledge Sync" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $FolderPath)) {
    Write-Host "❌ Error: La carpeta '$FolderPath' no existe." -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $FolderPath -Filter "*.md" -Recurse
Write-Host "📦 Encontradas $($files.Count) notas Markdown para indexar..." -ForegroundColor Yellow

$indexed = 0
foreach ($file in $files) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content)) { continue }

    $body = @{
        doc_id = $file.BaseName
        text = $content
        metadata = @{
            filename = $file.Name
            path = $file.FullName
            updated_at = (Get-Date).ToString("o")
        }
    } | ConvertTo-Json -Depth 5

    try {
        $res = Invoke-RestMethod -Uri $GatewayUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 30
        Write-Host "  ✅ [$($res.doc_id)] Indexado exitosamente ($($res.vector_dims) dims)" -ForegroundColor Green
        $indexed++
    } catch {
        Write-Host "  ⚠️ Error indexando $($file.Name): $_" -ForegroundColor Red
    }
}

Write-Host "`n🎉 Sincronización finalizada: $indexed / $($files.Count) notas indexadas en caliente." -ForegroundColor Cyan
