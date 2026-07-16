#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

uv sync --frozen --all-packages --all-groups
.venv/bin/ruff format --check packages services tests_v2 scripts/migrate_v2.py
.venv/bin/ruff check packages services tests_v2 scripts/migrate_v2.py
.venv/bin/mypy packages services scripts/migrate_v2.py
.venv/bin/lint-imports
.venv/bin/pytest --cov=fab_contracts --cov=fab_core --cov=fab_agent --cov=fab_api --cov=fab_data_mcp --cov-report=term-missing --cov-fail-under=70 tests_v2

cd web
npm ci
npm run lint
npm run build

if [[ "$ROOT" == /mnt/* ]]; then
  WEB_TEST_DIR="$(mktemp -d /tmp/fab-insight-web-test.XXXXXX)"
  cleanup_web_test() {
    if [[ "$WEB_TEST_DIR" == /tmp/fab-insight-web-test.* ]]; then
      rm -rf -- "$WEB_TEST_DIR"
    fi
  }
  trap cleanup_web_test EXIT
  cp -a src package.json package-lock.json tsconfig.json tsconfig.app.json tsconfig.node.json \
    vite.config.ts eslint.config.js index.html "$WEB_TEST_DIR/"
  cd "$WEB_TEST_DIR"
  npm ci --prefer-offline --no-audit
  npm run test
else
  npm run test
fi
