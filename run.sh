#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

LAUNCH_ROOT="$PWD"
PORT="${PORT:-8876}"
GIT_COMMIT="$(git rev-parse --short=12 HEAD 2>/dev/null || printf 'unversioned')"
WORKTREE_NAME="$(basename "$PWD")"
DEFAULT_INSTANCE_ID="${WORKTREE_NAME}-${GIT_COMMIT}-${PORT}"
INSTANCE_ID="${FAB_INSTANCE_ID:-$DEFAULT_INSTANCE_ID}"
if [[ ! "$INSTANCE_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "FAB_INSTANCE_ID only allows letters, numbers, dots, underscores and hyphens." >&2
  exit 2
fi

INSTANCE_ROOT="${FAB_INSTANCE_ROOT:-$PWD/runtime/$INSTANCE_ID}"
mkdir -p "$INSTANCE_ROOT/data/departments" "$INSTANCE_ROOT/data/personal_knowledge" "$INSTANCE_ROOT/logs/agent"
INSTANCE_ROOT="$(cd "$INSTANCE_ROOT" && pwd)"
SOURCE_ROOT="$INSTANCE_ROOT/source"

exec 9>"$INSTANCE_ROOT/service.lock"
if ! flock -n 9; then
  echo "Instance '$INSTANCE_ID' is already running: $INSTANCE_ROOT" >&2
  exit 3
fi

if [[ ! -d "$SOURCE_ROOT" ]]; then
  SOURCE_TMP="$(mktemp -d "$INSTANCE_ROOT/.source.XXXXXX")"
  if ! git archive "$GIT_COMMIT" | tar -x -C "$SOURCE_TMP"; then
    rm -rf "$SOURCE_TMP"
    echo "Failed to create source snapshot for commit '$GIT_COMMIT'." >&2
    exit 4
  fi
  printf '%s\n' "$GIT_COMMIT" > "$SOURCE_TMP/.fab-git-commit"
  mv "$SOURCE_TMP" "$SOURCE_ROOT"
fi

if [[ ! -f "$SOURCE_ROOT/.fab-git-commit" ]]; then
  echo "Source snapshot is incomplete: $SOURCE_ROOT" >&2
  exit 4
fi
SNAPSHOT_COMMIT="$(<"$SOURCE_ROOT/.fab-git-commit")"
if [[ "$SNAPSHOT_COMMIT" != "$GIT_COMMIT" ]]; then
  echo "Source snapshot commit '$SNAPSHOT_COMMIT' does not match requested commit '$GIT_COMMIT'." >&2
  exit 5
fi
SOURCE_ROOT="$(cd "$SOURCE_ROOT" && pwd)"

export FAB_INSTANCE_ID="$INSTANCE_ID"
export FAB_INSTANCE_ROOT="$INSTANCE_ROOT"
export FAB_SOURCE_ROOT="$SOURCE_ROOT"
export FAB_GIT_COMMIT="$GIT_COMMIT"
export FAB_WORKSPACE_ENV_FILE="${FAB_WORKSPACE_ENV_FILE:-$LAUNCH_ROOT/../../.env}"
export FAB_PROJECT_ENV_FILE="${FAB_PROJECT_ENV_FILE:-$LAUNCH_ROOT/.env}"
export FAB_DATABASE_PATH="$INSTANCE_ROOT/data/fab_history.db"
export FAB_DATABASE_DIR="$INSTANCE_ROOT/data/departments"
export FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH="$INSTANCE_ROOT/data/personal_knowledge"
export AGENT_LOG_PATH="$INSTANCE_ROOT/logs/agent_events.jsonl"
export AGENT_RUN_LOG_DIR="$INSTANCE_ROOT/logs/agent"

printf '{"instance_id":"%s","git_commit":"%s","port":%s,"worktree":"%s","source_root":"%s"}\n' \
  "$INSTANCE_ID" "$GIT_COMMIT" "$PORT" "$LAUNCH_ROOT" "$SOURCE_ROOT" > "$INSTANCE_ROOT/instance.json"

echo "Fab instance: $INSTANCE_ID"
echo "Runtime root: $INSTANCE_ROOT"
echo "Source root: $SOURCE_ROOT"
echo "Git commit: $GIT_COMMIT"
echo "Port: $PORT"

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

export PYTHONDONTWRITEBYTECODE=1
cd "$SOURCE_ROOT"
"${PYTHON[@]}" -m app.seed
exec "${PYTHON[@]}" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
