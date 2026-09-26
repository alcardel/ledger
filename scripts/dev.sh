#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then cp .env.example .env; fi
docker compose up -d
if [[ ! -x .venv/bin/python ]]; then uv venv --python 3.12 .venv; fi
uv pip install --python .venv/bin/python -e backend
.venv/bin/python scripts/bootstrap.py
.venv/bin/python -m app.seed
.venv/bin/python -m app.enhance_demo
if [[ ! -d frontend/node_modules ]]; then (cd frontend && npm ci); fi
if [[ ! -f frontend/.env.local ]]; then
  cp frontend/.env.example frontend/.env.local
fi
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
.venv/bin/celery -A app.tasks.celery worker --pool=solo --concurrency=1 -Q extraction,assessment --loglevel=INFO &
worker_pid=$!
(cd frontend && npm run dev) &
web_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true' EXIT INT TERM
printf '\nCredit Workbench: http://localhost:3000\nAPI documentation: http://localhost:8000/docs\n'
wait
