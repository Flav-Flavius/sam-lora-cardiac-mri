# Master Thesis Plan — Adapting Segment Anything (SAM) to Medical Imaging with LoRA (Cardiac Cine‑MRI)

> **Goal:** Evaluate zero‑shot SAM on cardiac cine‑MRI (ACDC) and improve it via Low‑Rank Adaptation (LoRA), measuring segmentation quality, robustness, and compute efficiency. Deliver a fully reproducible pipeline and a clear scientific report.

---

## 1) Quick Summary (Executive Overview)

* **Problem:** Off‑the‑shelf SAM underperforms on medical images. Can lightweight LoRA fine‑tuning close the gap efficiently?
* **Datasets:** Primary — **ACDC** (cine‑MRI). External generalization — **M\&Ms**, **Sunnybrook**.
* **Methods:** SAM (ViT‑B default) + LoRA ranks {4, 8, 16}; prompt types {point, box, grid}; prompt‑noise robustness; cost/perf analysis.
* **Metrics:** Dice, 95% Hausdorff Distance (HD95), Boundary F (BF score), clinical **LV mass error**.
* **Outcomes:** 1) Baseline zero‑shot vs. LoRA gains; 2) Robustness to prompt jitter; 3) Cross‑dataset generalization; 4) Reproducible MLOps stack.

---

## 2) Deliverables

* **D1. Codebase (public GitHub)** with clear README, scripts, configs, and CI checks.
* **D2. Trained adapters** (LoRA weights) + model cards (metadata).
* **D3. Evaluation suite** producing tables/figures & HTML report.
* **D4. Thesis document**: background, methods, experiments, analysis, limitations.
* **D5. Reproducibility pack**: environment lockfile, data prep notebook, seeds, W\&B/MLflow artifacts.

---

## 3) Repository Structure (proposed)

```
repo/
├─ README.md
├─ env/
│  ├─ environment.yml            # conda
│  └─ requirements.txt           # pip (if needed)
├─ configs/
│  ├─ data_acdc.yaml
│  ├─ lora_rank4.yaml
│  ├─ lora_rank8.yaml
│  ├─ lora_rank16.yaml
│  ├─ eval_zero_shot.yaml
│  └─ prompts.yaml
├─ data/
│  └─ (symlinks or paths via configs; not tracked)
├─ samlora/
│  ├─ datasets/
│  │  ├─ acdc.py
│  │  ├─ mms.py
│  │  └─ sunnybrook.py
│  ├─ models/
│  │  ├─ sam_loader.py
│  │  └─ lora_inject.py
│  ├─ training/
│  │  ├─ train_lora.py
│  │  └─ sched_optim.py
│  ├─ eval/
│  │  ├─ eval_seg.py
│  │  ├─ metrics.py
│  │  ├─ prompters.py
│  │  └─ visualize.py
│  ├─ utils/
│  │  ├─ seed.py
│  │  ├─ io.py
│  │  └─ geometry.py
│  └─ cli/
│     ├─ prepare_acdc.py
│     ├─ eval_zero_shot.py
│     └─ eval_cross_dataset.py
├─ notebooks/
│  ├─ 00_explore_acdc.ipynb
│  ├─ 10_zero_shot_baseline.ipynb
│  └─ 20_lora_tuning.ipynb
├─ scripts/
│  ├─ run_zero_shot.sh
│  ├─ run_lora.sh
│  ├─ run_ablation.sh
│  └─ export_report.sh
└─ tests/
   ├─ test_metrics.py
   └─ test_prompters.py
```

---

## 4) Environment & Dependencies

* **Machine:** MacBook Air (Apple Silicon, M‑series) — use **PyTorch with MPS (Metal)** backend (no CUDA).
* **Python env:** you already have `venv-sam`. Use it and install deps via `pip`.

**Activate & check device (Mac):**

```bash
source venv-sam/bin/activate
python - <<'PY'
import torch
print('PyTorch', torch.__version__)
print('MPS available:', torch.backends.mps.is_available())
print('MPS built:', torch.backends.mps.is_built())
PY
```

**Install minimal deps (suggested):**

```bash
pip install --upgrade pip wheel setuptools
pip install torch torchvision torchaudio  # MPS wheels include Metal backend
pip install segment-anything peft>=0.11.0 transformers>=4.41.0 \
            albumentations opencv-python pydicom nibabel SimpleITK \
            scikit-image matplotlib pandas wandb  # or mlflow
```

> Note: `bitsandbytes` (8‑bit optimizers) is **not** supported on Apple Silicon; keep **AdamW** and use gradient accumulation if needed.

**MPS usage in code:**

```python
import torch
DEVICE = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
# Keep float32 for stability on MPS; avoid half-precision unless tested
```

---

## 5) Data: Sources, Preprocessing, Splits

**Primary:** ACDC (cine‑MRI, short‑axis), with masks for LV cavity (LVC), RV cavity (RVC), myocardium (MYO).
**External:** M\&Ms (scanner variability), Sunnybrook (LV).

**Preprocessing steps:**

1. **DICOM→NIfTI/PNG**: retain spacing, slice thickness, per‑frame temporal order.
2. **Normalize** intensities per study: z‑score or percentile \[1, 99] rescale.
3. **Resample** to common in‑plane spacing (e.g., 1.25 mm) and **pad/crop** to fixed size (e.g., 256×256).
4. **Convert masks** to consistent label IDs {0: bg, 1: LVC, 2: MYO, 3: RVC}.
5. **Train/Val/Test split** (patient‑level), stratified by pathology if possible.

**CLI example:**

```bash
python -m samlora.cli.prepare_acdc \
  --acdc-root /data/ACDC \
  --out /data/ACDC_proc \
  --img-size 256 256 --spacing 1.25 \
  --labels LVC MYO RVC
```

---

## 6) Baselines & Experimental Design

**B0. Zero‑shot SAM:** prompt with (a) single foreground point (center of mass of GT), (b) tight bounding box from GT, (c) multi‑point grid (uniform over object).

**B1. Traditional U‑Net (optional):** lightweight 2D U‑Net trained on ACDC to contextualize SAM’s performance ceiling.

**LoRA fine‑tuning variants:**

* **Ranks:** r ∈ {4, 8, 16}
* **Target modules:** attention projections (q, k, v, o) in image encoder; optionally mask decoder MLPs (run ablation)
* **Freezing:** freeze all base weights; train only LoRA params + layer norm gains if needed
* **Optim:** AdamW (lr grid: 1e‑4, 5e‑5, 1e‑5), weight decay 0.01, cosine schedule, warmup 5%
* **Batching:** 2D slices or selected time frames (end‑diastole/end‑systole); experiment with 3‑frame context (t‑1,t,t+1) as channels

**Prompt robustness:**

* **Point jitter**: Gaussian noise σ ∈ {0, 2, 4, 8} px around ideal point
* **Box noise**: expand/contract box by {−20%, −10%, +10%, +20%}
* **Grid density**: {3, 5, 7} points per longest dimension

**Cross‑dataset generalization:**

* Train/val on ACDC; evaluate zero‑shot on M\&Ms/Sunnybrook without any tuning.

---

## 7) Metrics (with definitions)

* **Dice coefficient** (per class) : $\text{Dice} = \frac{2|P∩G|}{|P|+|G|}$
* **HD95**: 95th percentile of bidirectional surface distances (mm)
* **Boundary F (BF)**: F1 on contour points with tolerance τ (e.g., 2 px)
* **Clinical LV mass error**: from MYO pixels × voxel volume × myocardial density (≈1.05 g/ml); report absolute and signed errors.

**Reporting:** mean±std across patients; macro‑average over classes; paired statistics vs. baseline (Wilcoxon signed‑rank, α=0.05).

---

## 8) Training & Evaluation Pipelines

**LoRA training:**

```bash
python -m samlora.training.train_lora \
  --config configs/lora_rank8.yaml \
  DATA.ROOT /data/ACDC_proc \
  TRAIN.lr 5e-5 TRAIN.epochs 40 TRAIN.bs 12 \
  LORA.target_modules qkv,o \
  LOG.wandb true LOG.project samlora-acdc
```

**Zero‑shot evaluation:**

```bash
python -m samlora.cli.eval_zero_shot \
  --config configs/eval_zero_shot.yaml \
  DATA.ROOT /data/ACDC_proc \
  PROMPT.type point --prompt-noise 4 \
  EVAL.metrics dice hd95 bf --save-vis
```

**Cross‑dataset eval:**

```bash
python -m samlora.cli.eval_cross_dataset \
  --weights outputs/lora_rank8/best.pt \
  --dataset mms --root /data/MnMs_proc \
  --prompt box --save-report
```

---

## 9) Visualization & QA

* Side‑by‑side panels: **image / GT / SAM pred / error map** (FN red, FP blue)
* Failure library: save "hard" cases with comments (basal/apical slices, RV ambiguity)
* Automated HTML report per run (tables + thumbnails)

---

## 10) MLOps & Reproducibility

* **Tracking:** W\&B/MLflow runs, hyperparams, metrics, figures
* **Determinism:** fixed seeds, deterministic CuDNN where feasible
* **Configs‑first:** all hyperparams in YAML; scripts stateless
* **Artifacts:** version LoRA weights, model card with dataset + prompt recipe
* **CI:** unit tests for metrics & prompters on synthetic masks

---

## 11) Risk Assessment & Mitigations

* **Domain shift** (M\&Ms/Sunnybrook): include intensity normalization, test‑time augmentation; report failure cases
* **Memory/compute (Mac M‑series)**: prefer ViT‑B, enable gradient accumulation; no CUDA/8‑bit optimizer on macOS; leverage MPS backend; monitor memory with smaller batch sizes.
* **Overfitting**: early stopping on val Dice; monitor gap zero‑shot vs tuned
* **Ambiguous labels**: enforce consistent remapping; ignore unlabeled frames

---

## 12) Timeline (suggested \~12–14 weeks)

* **W1–W2:** Data prep, loaders, zero‑shot baseline
* **W3–W5:** LoRA r∈{4,8,16} sweeps, choose best rank
* **W6:** Prompt robustness experiments (point/box/grid + noise)
* **W7–W8:** Cost analysis (VRAM/time) + ablations (target modules)
* **W9:** Cross‑dataset eval (M\&Ms, Sunnybrook)
* **W10:** Visualizations, clinical LV mass error
* **W11–W12:** Writing, polishing, reproducibility pack

---

## 13) Checklists

**Experiment readiness:**

* [ ] ACDC prepared with consistent spacing/labels
* [ ] Zero‑shot eval reproduces baseline numbers
* [ ] LoRA training overfits a tiny subset (sanity check)
* [ ] Unit tests pass (metrics/prompters)

**Paper figures & tables:**

* [ ] Dice/HD95/BF per class (table)
* [ ] Rank vs. Dice vs. time/VRAM (chart)
* [ ] Robustness curves (jitter σ)
* [ ] Cross‑dataset boxplots
* [ ] Qualitative panels (success & failures)

---

## 14) Thesis Writing Outline (short)

1. **Introduction & Motivation** (clinical context, foundation models)
2. **Related Work** (SAM‑Med2D, MedSAM, MA‑SAM, SAM‑CLIP, adapters)
3. **Methods** (SAM + LoRA integration, prompting, losses)
4. **Experiments** (protocols, datasets, metrics)
5. **Results** (quant + qual, robustness, efficiency)
6. **Discussion** (insights, limitations, ethics)
7. **Conclusion & Future Work**

---

## 15) Implementation Notes

* **Losses:** Dice + BCE or focal on masks produced by SAM decoder; consider boundary‑aware auxiliary loss for fine edges.
* **Sampling:** emphasize ED/ES frames; ensure class balance per batch.
* **Post‑processing:** largest component per class; morphological closing for RV.
* **Scaling:** if time allows, try ViT‑L + LoRA r=4 for comparison.

---

## 16) Data & Ethics

* Use datasets under their licenses; store locally; remove PHI.
* Report limitations and avoid claims of clinical readiness.

---

## 17) Minimal Code Stubs

**`lora_inject.py` (pseudocode):**

```python
class LoRA(nn.Module):
    def __init__(self, in_f, out_f, r=8, alpha=16):
        super().__init__()
        self.A = nn.Linear(in_f, r, bias=False)
        self.B = nn.Linear(r, out_f, bias=False)
        nn.init.kaiming_uniform_(self.A.weight, a=math.sqrt(5))
        nn.init.zeros_(self.B.weight)
        self.scaling = alpha / r
    def forward(self, x):
        return self.B(self.A(x)) * self.scaling

# wrap attention projections: W -> W + LoRA(W)
```

**Prompt jitter (point):**

```python
def jitter_point(p, sigma_px):
    return p + np.random.normal(0, sigma_px, size=2)
```

---

## 18) How to Run (TL;DR)

```bash
# 1) Activate your existing virtualenv
source venv-sam/bin/activate

# 2) (If needed) install deps
pip install -r requirements.txt  # or the pip commands from section 4

# 3) Prepare ACDC
python -m samlora.cli.prepare_acdc --acdc-root /data/ACDC --out /data/ACDC_proc

# 4) Zero-shot baseline
bash scripts/run_zero_shot.sh

# 5) LoRA training (rank 8)
bash scripts/run_lora.sh

# 6) Robustness + cross-dataset
bash scripts/run_ablation.sh

# 7) Export report
bash scripts/export_report.sh
```

---

## 19) Acceptance Criteria

* **A1:** ≥ X% Dice gain over zero‑shot on MYO and LVC (define X after baseline)
* **A2:** Robustness degradation ≤ Δ under max jitter setting
* **A3:** External eval shows ≤ Y% drop vs. in‑domain tuned model
* **A4:** One‑command reproduction from clean env to figures

---

## 20) References (to cite in thesis)

* SAM‑Med2D (Huang et al., 2023), MedSAM (Ma et al., 2024), MA‑SAM (Chen et al., 2025), SAM‑CLIP (Lu et al., 2024), Medical SAM Adapter (Wu et al., 2024)

---

**End of Plan.**
