#!/bin/sh
export PATH="/usr/local/bin:$HOME/homebrew/bin:$PATH"
set -e
cd "$(dirname "$0")"

echo "=== Pulling latest ==="
git pull

echo "=== Building images ==="
docker compose build --no-cache api web

echo "=== Starting services ==="
docker compose up -d

echo "=== Health check ==="
sleep 3
curl -sf http://localhost:8000/health > /dev/null && echo "API: OK" || echo "API: FAIL"
curl -sf http://localhost:3000/ > /dev/null && echo "Web: OK" || echo "Web: FAIL"
echo "=== Done ==="
