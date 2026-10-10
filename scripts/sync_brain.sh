#!/usr/bin/env bash
# Open Hybrid RAG - Hot Knowledge Sync for Linux / macOS
# Soporta autenticación por API Key, eliminación de frontmatter YAML e indexación incremental por hash.

FOLDER_PATH="${1:-./knowledge_base}"
GATEWAY_URL="${2:-http://127.0.0.1:8000/api/v1/ingest}"
API_KEY="${API_KEY:-}"

echo "============================================================"
echo "🧠 Open Hybrid RAG - Incremental Hot Knowledge Sync"
echo "📂 Origen: $FOLDER_PATH"
echo "🌐 Destino: $GATEWAY_URL"
echo "============================================================"

if [ ! -d "$FOLDER_PATH" ]; then
    echo "❌ Error: El directorio '$FOLDER_PATH' no existe."
    exit 1
fi

indexed_count=0
error_count=0

while IFS= read -r -d '' file; do
    rel_path="${file#$FOLDER_PATH/}"
    doc_id=$(echo "$rel_path" | sed 's/[^a-zA-Z0-9._-]/_/g' | sed 's/\.md$//')
    
    # Extraer contenido removiendo frontmatter YAML (si existe)
    content=$(awk '
        BEGIN { in_fm = 0; count = 0 }
        /^---$/ {
            count++
            if (count == 1) { in_fm = 1; next }
            if (count == 2) { in_fm = 0; next }
        }
        !in_fm { print }
    ' "$file")
    
    if [ -z "$content" ]; then
        continue
    fi

    content_hash=$(echo -n "$content" | sha256sum | awk '{print $1}')

    payload=$(jq -n \
                  --arg id "$doc_id" \
                  --arg text "$content" \
                  --arg path "$rel_path" \
                  --arg hash "$content_hash" \
                  '{doc_id: $id, text: $text, doc_type: "document", metadata: {source_file: $path, content_hash: $hash}}')
                  
    headers=(-H "Content-Type: application/json")
    if [ -n "$API_KEY" ]; then
        headers+=(-H "X-API-Key: $API_KEY")
    fi

    http_response=$(curl -s -w "\n%{http_code}" -X POST "$GATEWAY_URL" "${headers[@]}" -d "$payload")
    http_code=$(echo "$http_response" | tail -n1)
    body=$(echo "$http_response" | sed '$d')

    if [ "$http_code" -eq 200 ]; then
        echo "  ✅ [$doc_id] Indexado exitosamente (HTTP 200)"
        ((indexed_count++))
    else
        echo "  ❌ [$doc_id] Falló indexación (HTTP $http_code): $body"
        ((error_count++))
    fi
done < <(find "$FOLDER_PATH" -type f -name "*.md" -print0)

echo "============================================================"
echo "🎉 Sincronización Finalizada: $indexed_count indexados, $error_count errores."
echo "============================================================"
