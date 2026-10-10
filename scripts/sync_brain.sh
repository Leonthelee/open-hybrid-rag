#!/usr/bin/env bash
# Open Hybrid RAG - Hot Knowledge Sync for Linux / macOS
FOLDER_PATH="${1:-./knowledge_base}"
GATEWAY_URL="${2:-http://127.0.0.1:8000/api/v1/ingest}"

echo "============================================================"
echo "🧠 Open Hybrid RAG - Hot Knowledge Sync"
echo "============================================================"

if [ ! -d "$FOLDER_PATH" ]; then
    echo "❌ Error: Directory '$FOLDER_PATH' does not exist."
    exit 1
fi

find "$FOLDER_PATH" -type f -name "*.md" | while read -r file; do
    doc_id=$(basename "$file" .md)
    content=$(cat "$file")
    
    # Payload JSON
    payload=$(jq -n \
                  --arg id "$doc_id" \
                  --arg text "$content" \
                  '{doc_id: $id, text: $text}')
                  
    response=$(curl -s -X POST "$GATEWAY_URL" \
                    -H "Content-Type: application/json" \
                    -d "$payload")
                    
    echo "  ✅ Indexado: $doc_id"
done

echo "🎉 Hot Knowledge Sync Complete!"
