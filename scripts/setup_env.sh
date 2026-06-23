#!/usr/bin/env bash
set -euo pipefail

# Idempotent environment setup
ENV_DIR=${1:-venv-sam}
PY=${PYTHON:-python3}

if [ ! -d "$ENV_DIR" ]; then
  $PY -m venv "$ENV_DIR"
fi
source "$ENV_DIR"/bin/activate
pip install --upgrade pip wheel setuptools
pip install -e .[dev]
echo "Environment ready in $ENV_DIR"

