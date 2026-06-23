# Documentație Tehnică — SAM LoRA ACDC

Documentație pentru ingineri: arhitectură, flux de date, logică LoRA și ghid de experimente.

---

## 1. Harta proiectului

### 1.1 Structura generală

```
segment-anything-model/
├── configs/           # Fișiere YAML de configurare (date, model, antrenare, eval)
├── data/              # Date brute (raw) și interim (după preprocesare) — nu în repo
├── metadata/          # Metadate auxiliare
├── outputs/           # Checkpoint-uri, metrici, vizualizări (generate la rulare)
├── scripts/           # Scripturi shell pentru pipeline (prepare, grid eval)
├── src/
│   ├── cli/           # Entry points: convert DICOM, train LoRA, eval zero-shot, eval cross-datasets
│   └── sam_lora/      # Logică de business: date, LoRA, SAM wrapper, prompturi, metrici, vizualizare
├── tests/             # Teste
├── pyproject.toml     # Pachet Python, dependențe, entry points
└── DOCUMENTATIE_TEHNICA.md
```

### 1.2 Rolul folderelor

| Folder | Rol |
|--------|-----|
| **`configs/`** | Toate setările rulărilor: rădăcini date, dimensiuni imagine, variantă SAM, parametri LoRA (rank, alpha, module țintă), hiperparametri antrenare (epochs, batch size, LR), tip prompt (point/box/grid), metrici eval, director output. Fiecare script CLI primește un `--config <fișier.yaml>`. |
| **`src/cli/`** | Puncte de intrare în aplicație. Fiecare modul expune o funcție `main()` și este înregistrat în `pyproject.toml` ca script instalabil (ex: `sam-lora-convert-dicom`, `sam-lora-train-lora`). Nu conține logică de model sau date — doar parsing argumente, încărcare YAML, apeluri în `sam_lora`. |
| **`src/sam_lora/`** | Nucleul proiectului: încărcare și iterare date (`data.py`), aplicare LoRA pe SAM (`lora.py`), wrapper SAM pentru predicții (`sam_wrapper.py`), generare prompturi (`prompts.py`), metrici (`metrics.py`), normalizare/resize (`preprocess.py`), vizualizare (`visualize.py`). |

### 1.3 Fișiere cheie

| Fișier | Rol |
|--------|-----|
| **`src/cli/convert_dicom.py`** | Preprocesare: citește config (inclusiv `RAW_ROOT`, `ROOT`, `IMG_SIZE`), convertește NIfTI (ACDC) sau NPY în imagini/măști 2D (PNG) și scrie `splits.json`. Este singurul script apelat la „preprocesare”. |
| **`src/cli/train_lora.py`** | Antrenare LoRA: încarcă config, construiește `SamPredictorWrapper`, aplică LoRA pe `predictor.model`, îngheță parametrii de bază, antrenează doar parametrii `lora_*`, salvează checkpoint în `OUTPUT_DIR`. |
| **`src/cli/eval_zero_shot.py`** | Eval zero-shot pe split-ul `test`: încarcă `SliceDataset`, SAM (fără LoRA), pentru fiecare eșantion generează prompt (point/box/grid), obține predicție, calculează Dice/HD95/BF și opțional salvează vizualizări. |
| **`src/cli/eval_cross_datasets.py`** | Eval cross-dataset: liste de dataset-uri în config (ex: MnMs, Sunnybrook), același predictor SAM pe fiecare, scrie metrici per dataset în CSV. Încărcarea ponderilor LoRA este menționată ca „future work”. |
| **`src/sam_lora/data.py`** | **`SliceDataset`**: citește `splits.json` de la `root`, pentru fiecare ID încarcă imagine (PNG sau NPY) din `root/images` și mască din `root/masks`. Returnează obiecte **`Sample`** (image tensor 1×H×W, mask opțional, meta cu `id`). Nu face normalizare sau resize la load — așteaptă date deja în formatul așteptat. |
| **`src/sam_lora/lora.py`** | **`apply_lora_to_sam(sam_model, rank, alpha, target_modules)`**: folosește PEFT (`LoraConfig` + `get_peft_model`) pentru a injeca LoRA în modulele SAM care conțin subșirurile din `target_modules` (implicit `q_proj`, `k_proj`, `v_proj`, `o_proj` — proiecțiile de atenție). Returnează modelul PEFT (SAM + adaptori LoRA). |
| **`src/sam_lora/sam_wrapper.py`** | **`SamPredictorWrapper`**: încarcă SAM din `segment_anything` (vit_b/vit_l/vit_h), pune modelul pe device (MPS/CUDA/CPU), expune `set_image()` și `predict_with_point()` / `predict_with_box()`. Convertește imagine grayscale în RGB și normalizează la [0,255] pentru API-ul SAM. |
| **`src/sam_lora/preprocess.py`** | Funcții utilitare: `zscore_normalize`, `percentile_normalize`, `remap_labels`, `resize_image_mask`. **Nu sunt apelate** în pipeline-ul curent de convert_dicom sau în `SliceDataset`; sunt disponibile pentru extinderi (ex: transform în DataLoader sau pipeline medical cu SimpleITK). |
| **`src/sam_lora/prompts.py`** | Generare prompturi din mască GT: centoid + jitter → point; bounding box → box; grid (density) → puncte. Toate în coordonate pixel. Folosite la antrenare (punct la centrul masei) și la eval (point/box/grid conform config). |
| **`src/sam_lora/metrics.py`** | Dice per clasă, HD95 (cu opțional pixel spacing), Boundary F-score, LV mass error. Implementări CPU, potrivite pentru 2D. |
| **`src/sam_lora/visualize.py`** | `side_by_side(image, gt, pred, out_png)`: panel 1×3 (imagine, GT, predicție) pentru QA. |
| **`scripts/prepare_acdc.sh`** | Apelează `sam-lora-convert-dicom` cu `configs/data_acdc.yaml` și cu rădăcini transmise ca argumente (implicit `data/raw/ACDC`, `data/interim/ACDC`). |

### 1.4 Entry points (pyproject.toml)

După `pip install -e .`:

- `sam-lora-convert-dicom` → `cli.convert_dicom:main`
- `sam-lora-eval-zero-shot` → `cli.eval_zero_shot:main`
- `sam-lora-train-lora` → `cli.train_lora:main`
- `sam-lora-eval-cross-datasets` → `cli.eval_cross_datasets:main`

---

## 2. Fluxul de date (Data Flow)

### 2.1 Preprocesare (pipeline-ul „convert”)

Când rulezi comanda de preprocesare:

1. **Comandă**  
   - Fie: `./scripts/prepare_acdc.sh [ACDC_ROOT] [OUT_ROOT]`  
   - Fie direct:  
     `sam-lora-convert-dicom --config configs/data_acdc.yaml [--acdc-root ...] [--out-root ...] [--max-slices N]`

2. **Script apelat**  
   - **`convert_dicom.py`** (entry point: `sam-lora-convert-dicom`).  
   - Niciun alt script din proiect nu este apelat pentru preprocesare.

3. **În `convert_dicom.py`**  
   - Se încarcă YAML-ul din `--config` (ex: `configs/data_acdc.yaml`).  
   - Se citesc din config: `DATA.ROOT` (output), `DATA.RAW_ROOT` (input), `DATA.IMG_SIZE` (folosit doar în config, nu pentru resize în acest script).  
   - Se creează directoare `out_root/images`, `out_root/masks`.

4. **Calea A: structură NIfTI ACDC**  
   - Dacă există `RAW_ROOT/database/`:  
     - Parcurge `database/training` și `database/testing`, apoi `patient*/`, fișiere `*frame*.nii.gz` (exclude `*_gt.nii.gz`).  
     - Pentru fiecare frame, caută `*_gt.nii.gz`; încarcă imagine și mască cu **nibabel**, extrage felii 2D pe axa Z.  
     - Ignoră felii cu mască goală.  
     - Salvează:  
       - imagine: min-max la [0,1], apoi `*255` → PNG în `out_root/images`;  
       - mască: uint8 → PNG în `out_root/masks`.  
     - ID: `{patient_dir.name}_{fp.stem}_z{z:02d}`.  
     - La final: construiește `splits.json` cu 70% train, 10% val, 20% test (pe lista de IDs).  
   - Opțional: `--max-slices` limitează numărul total de felii exportate.

5. **Calea B: fallback NPY**  
   - Dacă nu există `database/`: caută `RAW_ROOT/images/*.npy` și pentru fiecare `base.npy` caută `RAW_ROOT/masks/base.npy`.  
   - Încarcă perechea, salvează PNG în `out_root/images` și `out_root/masks`, construiește `splits.json` cu split 70/10/20.

6. **Clase din `data.py`**  
   - **Niciuna** în timpul preprocesării. `convert_dicom.py` nu importă `SliceDataset` nici `Sample`.  
   - Layout-ul produs (images/, masks/, splits.json) este cel pe care **`SliceDataset`** îl așteaptă la **antrenare** și **evaluare**.

### 2.2 Antrenare (folosirea datelor)

1. **Comandă**: `sam-lora-train-lora --config configs/lora_rank8.yaml` (sau alt YAML).

2. **Script**: **`train_lora.py`**.  
   - Citește config → `DATA.ROOT`, `DATA.IMG_SIZE`, `MODEL.*`, `TRAIN.*`, `LOG.*`.

3. **Date**:  
   - **`SliceDataset(root=data_root, split="train", img_size=(img_h, img_w), has_masks=True)`**  
   - `SliceDataset`: deschide `root/splits.json`, preia lista de IDs pentru `"train"`, pentru fiecare ID:  
     - **`_load_image(path)`**: PNG → PIL grayscale → numpy float32; sau NPY → float32.  
     - **`_load_mask(path)`**: PNG/NPY → int64.  
   - Convertește în tensori: image (1,H,W), mask (H,W).  
   - Returnează **`Sample(image=..., mask=..., meta={"id": base})`**.

4. **DataLoader**: batch-uri de `Sample`, shuffle, `BATCH_SIZE` și `NUM_WORKERS` din config.

5. **Observație**: `SliceDataset` **nu** apelează `preprocess.zscore_normalize` sau `resize_image_mask`; imaginile sunt folosite la dimensiunea și scala în care sunt stocate. Dacă în convert ai salvat PNG-uri 256×256, atunci `IMG_SIZE` din config este doar documentare; resize-ul ar trebui făcut fie în convert, fie printr-o transform în dataset (folosind `preprocess.resize_image_mask`).

### 2.3 Evaluare zero-shot și cross-dataset

- **eval_zero_shot.py**: folosește **`SliceDataset(root, split="test", img_size=(img_h, img_w), has_masks=True)`**, apoi pentru fiecare eșantion **`point_prompt_from_mask` / `box_prompt_from_mask` / `grid_prompt_for_image`** din `prompts.py`, **`SamPredictorWrapper`** pentru predicție, **`dice_score`, `hd95`, `boundary_f_score`** din `metrics.py`, opțional **`side_by_side`** din `visualize.py`.  
- **eval_cross_datasets.py**: pentru fiecare dataset din config creează un **`SliceDataset`** pe `d["ROOT"]`, apoi același flux de prompt + predictor + metrici.

Rezumat: **Preprocesare = doar `convert_dicom.py`**. **Clasele din `data.py`** (`SliceDataset`, `Sample`, `_load_image`, `_load_mask`) sunt folosite la **antrenare** și **evaluare**, nu în convert.

---

## 3. Logica modelului: LoRA și modificarea SAM

### 3.1 Unde este definită injecția LoRA

- **Fișier**: **`src/sam_lora/lora.py`**.  
- **Funcție**: **`apply_lora_to_sam(sam_model, rank=8, alpha=16, target_modules=None)`**.

### 3.2 Cum funcționează

1. **PEFT**: Se folosește biblioteca **PEFT** (Parameter-Efficient Fine-Tuning): `LoraConfig` și `get_peft_model(sam_model, config)`.

2. **Parametri**:
   - **`rank` (r)**: rangul descompunerii LoRA (W' ≈ B·A, A ∈ R^(r×k), B ∈ R^(d×r)). Mai mare = mai mulți parametri, mai multă capacitate.
   - **`alpha`**: factor de scalare pentru output-ul LoRA (efectul real este proporțional cu `alpha/rank` în multe implementări).
   - **`target_modules`**: listă de **subșiruri** pentru numele modulelor. PEFT potrivește orice modul al cărui nume **conține** unul dintre aceste subșiruri. Implicit: `["q_proj", "k_proj", "v_proj", "o_proj"]` — adică proiecțiile Q, K, V și O din blocuri de **atenție** (ViT / mask decoder, în funcție de structura SAM).

3. **Ce se modifică în SAM**:
   - **Nu** se schimbă arhitectura modelului.  
   - Se **înlocuiesc** (sau se „învelesc”) straturile liniare care conțin în nume `q_proj`, `k_proj`, `v_proj`, `o_proj` cu variante PEFT: weight-ul original rămâne înghețat, se adaugă adaptori LoRA (matrici A, B).  
   - La forward: output = W·x + (alpha/rank)·(B·A)·x. Doar A și B sunt antrenabile.

4. **În `train_lora.py`**:
   - Se obține modelul SAM din **`SamPredictorWrapper`**: `sam_model = predictor.predictor.model`.  
   - **`sam_lora = apply_lora_to_sam(sam_model, rank=..., alpha=..., target_modules=...)`**.  
   - Se îngheță toți parametrii care nu sunt LoRA: `p.requires_grad = ("lora_" in name)`.  
   - Optimizatorul și loop-ul de antrenare lucrează doar pe parametrii `lora_*`.  
   - **Limitare cunoscută**: backprop-ul real către predicția SAM nu este conectat complet în codul actual; se folosește un placeholder (L2 pe parametrii LoRA) pentru a verifica pipeline-ul. Pentru antrenament real trebuie „legată” ieșirea predictorului la graful de autograd (ex: folosirea directă a modelului PEFT în forward și loss pe mască).

### 3.3 Rezumat

- **Unde**: `lora.py` → `apply_lora_to_sam`.  
- **Cum se modifică SAM**: prin PEFT; straturile de tip proiecție (q/k/v/o) sunt extinse cu adaptori LoRA; restul SAM rămâne neschimbat și înghețat.  
- **Ce antrenăm**: doar parametrii LoRA (A, B) pentru modulele țintă.

---

## 4. Ghid de experimente: parametri YAML și impact

### 4.1 Fișiere YAML relevante

- **`configs/data_acdc.yaml`**: date și preprocesare (pentru convert și referință).  
- **`configs/lora_rank4.yaml`, lora_rank8.yaml, lora_rank16.yaml`**: antrenare LoRA cu rank 4, 8, 16.  
- **`configs/eval_zero_shot.yaml`**: evaluare zero-shot pe ACDC.  
- **`configs/cross_eval.yaml`**: evaluare cross-dataset (MnMs, Sunnybrook).

### 4.2 Secțiunea DATA

| Parametru | Fișier(e) | Descriere și impact |
|-----------|-----------|----------------------|
| **ROOT** | toate | Directorul unde sunt `images/`, `masks/`, `splits.json`. La convert = output; la train/eval = rădăcina datasetului. |
| **RAW_ROOT** | data_acdc.yaml | Sursa la convert: `database/` (NIfTI) sau `images/`+`masks/` (NPY). |
| **IMG_SIZE** | toate | [H, W]. În convert nu se face resize; în `SliceDataset` este stocat și poate fi folosit pentru transform/resize dacă îl conectezi în cod. Pentru rezultate consistente, fie exportă la acest size în convert, fie adaugă transform în dataset. |
| **SPACING_MM** | data_acdc | Documentare; poate fi folosit la metrici (ex: HD95 în mm) dacă e expus în eval. |
| **NORM** | data_acdc | zscore / percentile. Documentare; `preprocess.py` are funcțiile, dar nu sunt legate în pipeline. |
| **VAL_RATIO, TEST_RATIO, SPLIT_SEED** | data_acdc | În convert, split-ul este hardcodat 70/10/20; acești parametri pot fi folosiți dacă refactorizezi convert_dicom pentru split configurabil. |
| **LABELS, ID_MAP** | data_acdc | Etichete ACDC (LVC, MYO, RVC); folosite la metrici (clase 1..3) și pentru documentare. |

### 4.3 Secțiunea MODEL (train / eval)

| Parametru | Descriere și impact |
|-----------|----------------------|
| **SAM_VARIANT** | `vit_b` / `vit_l` / `vit_h`. Dimensiunea encoder-ului SAM; vit_h = cel mai mare, vit_b = cel mai rapid. |
| **CHECKPOINT** | Cale la checkpoint SAM. `null` = folosește default din `segment_anything`. Setează explicit pentru reproducibilitate. |
| **LORA.RANK** | Rang LoRA (r). Mai mare → mai mulți parametri, mai multă capacitate, risc overfitting. Experimente tipice: 4, 8, 16 (configurile existente). |
| **LORA.ALPHA** | Scalare LoRA. În practică contează raportul alpha/rank; de obicei alpha = 2*rank. Creșterea alpha mărește contribuția adaptorilor. |
| **LORA.TARGET_MODULES** | Listă de subșiruri (ex: `[q_proj, k_proj, v_proj, o_proj]`). Doar aceste module primesc LoRA. Poți restrânge (ex. doar `q_proj`, `v_proj`) pentru mai puțini parametri. |
| **WEIGHTS** (cross_eval) | Cale la ponderi LoRA fine-tuned. În codul actual nu este încărcat; e „future work”. |

### 4.4 Secțiunea TRAIN (doar în configurările de antrenare)

| Parametru | Descriere și impact |
|-----------|----------------------|
| **EPOCHS** | Număr epoci. Mai multe = antrenament mai lung; monitorizează overfitting pe val. |
| **BATCH_SIZE** | Mărime batch. Mai mare = mai stabil, dar mai mult GPU/RAM. |
| **LR** | Learning rate. Tipic 5e-5 pentru LoRA. Prea mare poate instabiliza. |
| **WEIGHT_DECAY** | Regularizare L2. 0.01 este un default rezonabil. |
| **WARMUP_RATIO** | În config; trebuie conectat în `train_lora.py` (scheduler) pentru a avea efect. |
| **SEED** | Pentru reproductibilitate; trebuie setat în `train_lora.py` (torch, numpy, random). |
| **NUM_WORKERS** | Workers pentru DataLoader; 0 = single-process (util la debug). |

### 4.5 Secțiunea PROMPT

| Parametru | Descriere și impact |
|-----------|----------------------|
| **TYPE** | `point` / `box` / `grid`. La eval: point = centru masei (+ jitter), box = bounding box GT, grid = puncte pe grilă. La train, în cod se folosește un singur punct (centroid). |
| **GRID_DENSITY** | Pentru `grid`: număr puncte pe axă (grilă density×density). |
| **POINT_JITTER** | Abatere standard (px) pentru jitter pe punct; 0 = fără jitter. |
| **BOX_SCALE** | Scale factor pe bounding box (1.0 = exact GT). >1 = box mai mare. |

### 4.6 Secțiunea EVAL (eval_zero_shot, cross_eval)

| Parametru | Descriere și impact |
|-----------|----------------------|
| **METRICS** | Listă: dice, hd95, bf. Ce se calculează și se scrie în CSV. |
| **SAVE_VIS** | true/false. Salvează imagini side-by-side (image, GT, pred) în subdirectorul `vis`. |
| **SEED** | Pentru reproductibilitate; trebuie setat în scriptul de eval dacă există aleatoriu. |
| **BATCH_SIZE** | Folosit în eval; în codul actual iterarea este per eșantion, nu per batch. |

### 4.7 Secțiunea LOG

| Parametru | Descriere și impact |
|-----------|----------------------|
| **OUTPUT_DIR** | Unde se salvează checkpoint-uri (train), metrici CSV și vizualizări (eval). |
| **WANDB, MLFLOW** | false în configurări; pot fi conectate ulterior pentru logging experimente. |

### 4.8 Exemplu de flux de experimente

1. **Preprocesare**:  
   `./scripts/prepare_acdc.sh` sau `sam-lora-convert-dicom --config configs/data_acdc.yaml` (opțional `--max-slices` pentru demo).

2. **Antrenare** cu rank diferit:  
   `sam-lora-train-lora --config configs/lora_rank4.yaml`  
   `sam-lora-train-lora --config configs/lora_rank8.yaml`  
   `sam-lora-train-lora --config configs/lora_rank16.yaml`  
   Checkpoint-urile merg în `LOG.OUTPUT_DIR` (ex: `outputs/train_lora/rank8`).

3. **Zero-shot**:  
   `sam-lora-eval-zero-shot --config configs/eval_zero_shot.yaml`  
   Modifici `PROMPT.TYPE` (point/box/grid) și `POINT_JITTER` pentru a testa robustețea la prompt.

4. **Cross-dataset**:  
   Pregătești date în `data/interim/MnMs` și `data/interim/Sunnybrook` (același layout: images/, masks/, splits.json), apoi:  
   `sam-lora-eval-cross-datasets --config configs/cross_eval.yaml`.

---

*Document generat pentru preluarea tehnică a proiectului SAM LoRA ACDC.*
