#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/fab-api ]]; then
  uv sync --frozen --all-packages
fi
if [[ ! -d web/dist ]]; then
  (cd web && npm ci && npm run build)
fi

export FAB_MCP_DATABASE_DIR="${FAB_MCP_DATABASE_DIR:-data/v2/mcp}"
export FAB_MCP_SERVICE_TOKEN="${FAB_MCP_SERVICE_TOKEN:-dev-mcp-service-token}"
export FAB_API_MCP_SERVICE_TOKEN="${FAB_API_MCP_SERVICE_TOKEN:-$FAB_MCP_SERVICE_TOKEN}"
export FAB_API_APPLICATION_DATABASE_DIR="${FAB_API_APPLICATION_DATABASE_DIR:-data/v2/api}"

.venv/bin/fab-data-mcp &
MCP_PID=$!
trap 'kill "$MCP_PID" 2>/dev/null || true' EXIT INT TERM
.venv/bin/fab-api
