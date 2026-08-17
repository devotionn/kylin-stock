#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${KYLIN_STOCK_OCR_VENV:-$HOME/.local/share/kylin-stock/ocr-venv}"
REQUIREMENTS="$ROOT_DIR/src-tauri/resources/requirements-ocr.txt"

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("KylinStock OCR 当前锁定的 ONNX Runtime 需要 Python 3.11+。请先安装 Python 3.11/3.12。")
print(f"Python runtime: {sys.version.split()[0]}")
PY

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip

if [[ -n "${KYLIN_STOCK_OCR_WHEELHOUSE:-}" ]]; then
  "$VENV_DIR/bin/python" -m pip install \
    --no-index \
    --find-links "$KYLIN_STOCK_OCR_WHEELHOUSE" \
    -r "$REQUIREMENTS"
else
  "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS"
fi

"$VENV_DIR/bin/python" -m rapidocr check || "$VENV_DIR/bin/rapidocr" check

cat <<EOF
OCR runtime ready.

Use this runtime when starting KylinStock:
export KYLIN_STOCK_OCR_PYTHON="$VENV_DIR/bin/python"

For fully offline deployment, prepare an ARM64 wheelhouse first and run:
KYLIN_STOCK_OCR_WHEELHOUSE=/path/to/wheels $0
EOF
