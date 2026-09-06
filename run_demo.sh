#!/usr/bin/env bash
# Run this AFTER `docker compose up -d` and once Exasol has finished booting
# (first boot can take ~60-90s). It seeds the database, then scores it.
set -euo pipefail

echo "==> Waiting for backend to report healthy..."
until curl -sf http://localhost:8000/health > /dev/null; do
  sleep 3
done
echo "==> Backend is up."

echo "==> Generating synthetic UPI dataset into Exasol..."
docker exec aegis-backend python /app/simulation/generate_data.py

echo "==> Running baseline + graph + explainability pipeline..."
curl -s -X POST http://localhost:8000/pipeline/run | python3 -m json.tool

echo "==> Done. Open http://localhost:3000 for the War Room UI."
echo "    (Optional) trigger the adaptive-loop stretch demo:"
echo "    curl -X POST http://localhost:8000/adapt/run"
