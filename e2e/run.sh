#!/usr/bin/env sh
# Испытания со сбоями на реальных сервисах. Нужны docker compose и python3.10+.
set -e
cd "$(dirname "$0")/.."
VENV="${E2E_VENV:-.venv-e2e}"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q pytest httpx psycopg2-binary
"$VENV/bin/python" -m pytest e2e -v -p no:cacheprovider "$@"
