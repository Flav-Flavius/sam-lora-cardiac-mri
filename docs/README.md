# SAM + LoRA for ACDC (Master's Thesis)

Evaluating zero-shot SAM and adapting it to cardiac cine-MRI (ACDC) via LoRA. Includes reproducible configs, CLIs, and optional W&B/MLflow tracking.

## Quickstart

1) Create/activate venv (or use existing `venv-sam`):
```bash
python3 -m venv venv-sam
source venv-sam/bin/activate
```

2) Install package (editable) and pre-commit hooks:
```bash
pip install --upgrade pip wheel setuptools
pip install -e .[dev]
pre-commit install
```

3) Verify PyTorch device (Mac M-series uses MPS):
```bash
python - <<'PY'
import torch
print('PyTorch', torch.__version__)
print('MPS available:', torch.backends.mps.is_available())
print('MPS built:', torch.backends.mps.is_built())
PY
```

## Data Preparation (ACDC)

Place raw ACDC under `data/raw/ACDC` (DICOMs or provided NIfTI). Then:
```bash
sam-lora-convert-dicom --config configs/data_acdc.yaml --acdc-root data/raw/ACDC --out-root data/interim/ACDC
```
This converts to a normalized, resized 2D slice dataset and remaps labels `{0:bg,1:LVC,2:MYO,3:RVC}`.

## Zero-shot Baseline
```bash
sam-lora-eval-zero-shot --config configs/eval_zero_shot.yaml
```
Produces CSV metrics under `outputs/zero_shot/*` and optional PNG visualizations.

## LoRA Training
```bash
# choose rank config: 4/8/16
sam-lora-train-lora --config configs/lora_rank8.yaml
```
Weights and logs saved under `outputs/train_lora/rank8/`. W&B/MLflow can be toggled in YAML.

## Cross-Dataset Evaluation
```bash
sam-lora-eval-cross-datasets --config configs/cross_eval.yaml --weights outputs/train_lora/rank8/best.pt
```

## Configuration
YAML files in `configs/` control paths, normalization, prompt type, seeds, batch size, image size, and LoRA hyperparameters. You can override any key via CLI `--key.subkey value` pairs.

- `data_acdc.yaml`: dataset paths and preprocessing
- `eval_zero_shot.yaml`: zero-shot prompt and eval settings
- `lora_rank{4,8,16}.yaml`: training and LoRA settings
- `cross_eval.yaml`: external dataset evaluation

## Logging
- Optional: Weights & Biases (W&B) and MLflow (toggle via `LOG.wandb` / `LOG.mlflow`).
- If disabled, metrics are written to CSV under `outputs/` and figures to PNG.

## Tests
```bash
pytest -q
```
Minimal tests check Dice and prompt generation logic.

## Scripts
- `scripts/setup_env.sh`: idempotent env bootstrap
- `scripts/prepare_acdc.sh`: convert ACDC to `data/interim`
- `scripts/run_grid_eval.sh`: sweep prompt types and LoRA ranks

## Citation
If you use this scaffold, please cite the associated thesis work.
