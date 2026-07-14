#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

ENV_NAME="${FAB_CONDA_ENV:-fab-insight-agent}"
if [[ "${CONDA_DEFAULT_ENV:-}" == "$ENV_NAME" ]]; then
  PYTHON=(python)
elif command -v conda >/dev/null 2>&1; then
  PYTHON=(conda run --no-capture-output -n "$ENV_NAME" python)
else
  echo "Conda is required. Create and activate the '$ENV_NAME' environment first." >&2
  exit 1
fi

"${PYTHON[@]}" -m app.seed
exec "${PYTHON[@]}" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8765}"
