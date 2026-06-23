#!/usr/bin/env bash
set -euo pipefail

ACDC_ROOT=${1:-data/raw/ACDC}
OUT_ROOT=${2:-data/interim/ACDC}

sam-lora-convert-dicom --config configs/data_acdc.yaml --acdc-root "$ACDC_ROOT" --out-root "$OUT_ROOT"
echo "Prepared ACDC under $OUT_ROOT"

