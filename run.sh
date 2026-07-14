#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

ENV_NAME="${FAB_CONDA_ENV:-fab-insight-agent}"
if [[ "${CONDA_DEFAULT_ENV:-}" == "$ENV_NAME" ]]; then
  PYTHON=(python)
else
  CONDA_BIN="${CONDA_EXE:-}"
  if [[ -z "$CONDA_BIN" ]] && command -v conda >/dev/null 2>&1; then
    CONDA_BIN="$(command -v conda)"
  fi
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda"; do
    if [[ -z "$CONDA_BIN" && -x "$candidate" ]]; then
      CONDA_BIN="$candidate"
    fi
  done
  if [[ -z "$CONDA_BIN" ]]; then
    echo "Conda is required. Create and activate the '$ENV_NAME' environment first." >&2
    exit 1
  fi
  PYTHON=("$CONDA_BIN" run --no-capture-output -n "$ENV_NAME" python)
fi

"${PYTHON[@]}" -m app.seed
exec "${PYTHON[@]}" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8765}"
