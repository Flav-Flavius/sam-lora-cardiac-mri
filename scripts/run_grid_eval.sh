#!/usr/bin/env bash
set -euo pipefail

PROMPTS=(point box grid)
RANKS=(4 8 16)

for P in "${PROMPTS[@]}"; do
  yq -y ".PROMPT.TYPE = \"$P\"" configs/eval_zero_shot.yaml > /tmp/ezs.yaml
  sam-lora-eval-zero-shot --config /tmp/ezs.yaml || true
done

for R in "${RANKS[@]}"; do
  CFG="configs/lora_rank${R}.yaml"
  sam-lora-train-lora --config "$CFG" || true
done

echo "Grid eval completed."

