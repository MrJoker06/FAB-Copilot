#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ -n "${FAB_PYTHON:-}" ]]; then PYTHON="$FAB_PYTHON"
elif [[ -x "$ROOT/.venv-linux/bin/python" ]]; then PYTHON="$ROOT/.venv-linux/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then PYTHON="$ROOT/.venv/bin/python"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then PYTHON="$CONDA_PREFIX/bin/python"
else PYTHON=""; fi
if [[ -n "$PYTHON" && -x "$PYTHON" ]]; then
  exec "$PYTHON" "$ROOT/run.py" "$@"
fi

CONDA_ENV="${FAB_CONDA_ENV:-fab-insight-agent}"
CONDA_PYTHON=""
for candidate in "$HOME/miniconda3/envs/$CONDA_ENV/bin/python" "$HOME/anaconda3/envs/$CONDA_ENV/bin/python" "$HOME/.conda/envs/$CONDA_ENV/bin/python"; do
  if [[ -x "$candidate" ]]; then CONDA_PYTHON="$candidate"; break; fi
done
if [[ -n "$CONDA_PYTHON" ]]; then
  exec "$CONDA_PYTHON" "$ROOT/run.py" "$@"
fi
if [[ -n "${FAB_CONDA_ENV:-}" ]]; then
  CONDA_BIN="${CONDA_EXE:-}"
  [[ -n "$CONDA_BIN" ]] || CONDA_BIN="$(command -v conda || true)"
  [[ -n "$CONDA_BIN" ]] || CONDA_BIN="$HOME/miniconda3/bin/conda"
  [[ -x "$CONDA_BIN" ]] || CONDA_BIN="$HOME/anaconda3/bin/conda"
  if [[ -x "$CONDA_BIN" ]]; then
    exec "$CONDA_BIN" run --no-capture-output -n "$CONDA_ENV" python "$ROOT/run.py" "$@"
  fi
fi

PYTHON="$(command -v python3 || command -v python || true)"
if [[ -n "$PYTHON" && -x "$PYTHON" ]]; then exec "$PYTHON" "$ROOT/run.py" "$@"; fi

echo "Python 3.11+ is required. Set FAB_PYTHON, create .venv-linux, or activate/install the configured Conda environment." >&2
exit 1
