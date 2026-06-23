# STATUS.md — Proiect Disertație
## SAM + LoRA pe ACDC Cardiac MRI
**Ultima actualizare:** 22 iunie 2026  
**Student:** Cenușe Flavius Dragoș  
**Timeline:** ~7 zile implementare + ~14 zile redactare

---

## 📁 Structura Proiectului

```
~/SAM/segment-anything-model/
├── checkpoints/
│   └── sam_vit_b_01ec64.pth        ✅ descărcat (357MB)
├── configs/
│   ├── eval_zero_shot.yaml          ✅ CHECKPOINT setat
│   ├── lora_rank4.yaml              ✅ CHECKPOINT setat
│   ├── lora_rank8.yaml              ✅ CHECKPOINT setat
│   ├── lora_rank16.yaml             ✅ CHECKPOINT setat
│   ├── cross_eval.yaml              ⚠️ CHECKPOINT încă null
│   └── data_acdc.yaml
├── data/
│   ├── raw/ACDC/database/
│   │   ├── training/  (patient001–100)  ✅ complet
│   │   └── testing/   (patient101–150)  ✅ complet
│   └── interim/ACDC/
│       ├── images/    (2842 PNG-uri)    ✅ preprocesate
│       ├── masks/     (2842 PNG-uri)    ✅ preprocesate
│       └── splits.json                  ✅ train/val/test corect
├── src/
│   ├── sam_lora/
│   │   ├── sam_wrapper.py           ✅ bug fix: checkpoint guard
│   │   ├── data.py                  ✅ bug fix: resize implementat
│   │   ├── lora.py                  ✅ bug fix: task_type corect
│   │   ├── metrics.py               ✅ ok (Dice, HD95, BF, LV mass)
│   │   ├── prompts.py               ✅ ok (point, box, grid, jitter)
│   │   └── visualize.py             ✅ ok
│   └── cli/
│       ├── eval_zero_shot.py        ✅ rulat cu succes
│       ├── train_lora.py            ⏳ de verificat și rulat pe Colab
│       └── eval_cross_datasets.py   ⏳ pentru mai târziu
├── outputs/
│   └── zero_shot/
│       ├── metrics.csv              ✅ 569 slice-uri evaluate
│       └── vis/                     ✅ vizualizări salvate
└── scripts/
    ├── prepare_acdc.sh              ✅ rulat cu succes
    ├── setup_env.sh
    └── run_grid_eval.sh
```

---

## ✅ CE AM FĂCUT (Ziua 1)

### Setup & Infrastructură
- [x] `pip install -e .` — pachet instalat cu succes
- [x] Preprocesare ACDC completă: **2842 slice-uri** (train: 1989 / val: 284 / test: 569)
- [x] Checkpoint SAM ViT-B descărcat: `checkpoints/sam_vit_b_01ec64.pth`
- [x] Config-uri actualizate (4/5 — cross_eval.yaml rămâne pentru mai târziu)

### Bug Fixes
- [x] **Bug 1** — `sam_wrapper.py`: checkpoint=None permitea rularea cu weights random → adăugat `ValueError` explicit
- [x] **Bug 2** — `data.py`: `img_size` primit dar niciodată aplicat → implementat resize cu BILINEAR (imagini) și NEAREST (măști)
- [x] **Bug 3** — `lora.py`: `task_type="SEQ_CLS"` (NLP) → schimbat în `TaskType.FEATURE_EXTRACTION`

### Evaluare Zero-Shot
- [x] Pipeline zero-shot funcțional end-to-end
- [x] Evaluare pe 569 slice-uri din setul de test ACDC

**Rezultate baseline zero-shot:**
| Metrică | Valoare |
|---------|---------|
| Dice macro | **0.2321** |
| HD95 macro | **7.25 px** |
| Boundary F-score | **0.6419** |

---

## ⏳ CE URMEAZĂ

### Ziua 2 — Setup Colab + Training LoRA
- [ ] Urcat proiect pe GitHub
- [ ] Clonat pe Google Colab
- [ ] Verificat `src/cli/train_lora.py` — citit și înțeles codul
- [ ] Rulat training LoRA **rank 8** primul (cel mai important)
- [ ] Salvat checkpoint pe Google Drive după training
- [ ] Evaluat modelul fine-tuned pe setul de test

### Ziua 3 — Analiza + Rankuri multiple
- [ ] Comparat rezultate zero-shot vs LoRA rank 8
- [ ] Rulat training LoRA rank 4
- [ ] Rulat training LoRA rank 16
- [ ] Tabel comparativ complet

### Ziua 4 — Vizualizări + Analiză
- [ ] Vizualizări side-by-side (GT vs zero-shot vs LoRA)
- [ ] Analiză calitativă — ce structuri se îmbunătățesc cel mai mult
- [ ] Documentat eșecuri (unde LoRA tot nu funcționează bine)

### Ziua 5-7 — Buffer + Cross-eval (opțional)
- [ ] Actualizat `cross_eval.yaml` cu checkpoint LoRA
- [ ] Cross-eval pe M&Ms sau Sunnybrook (dacă rămâne timp)
- [ ] Curățat cod, documentat, pregătit pentru GitHub final

---

## 🐛 BUGS CUNOSCUTE / LIMITĂRI ACTUALE

1. **`cross_eval.yaml`** — `CHECKPOINT: null` — de actualizat când avem weights LoRA
2. **Evaluare multi-clasă limitată** — codul zero-shot atribuie toți pixelii clasei `mask.max()=3` (RVC). Aceasta e o limitare a abordării cu prompt unic, nu un bug per se. LoRA cu prompting per clasă va rezolva asta.
3. **`train_lora.py`** — neexaminat încă. De citit și verificat înainte de rulare pe Colab.

---

## 📊 REZULTATE ACUMULATE

### Zero-Shot SAM ViT-B (baseline)
- **Data evaluare:** 22 iunie 2026
- **Split:** test (569 slice-uri, patient101–150)
- **Prompt:** point (centroid din ground truth mask)
- **Dice macro:** 0.2321
- **HD95 macro:** 7.25 px
- **BF score:** 0.6419

### LoRA Fine-Tuning (de completat)
| Config | Dice | HD95 | BF | Status |
|--------|------|------|-----|--------|
| Rank 4 | — | — | — | ⏳ |
| Rank 8 | — | — | — | ⏳ |
| Rank 16 | — | — | — | ⏳ |

---

## 🔧 MEDIU DE LUCRU

| Componentă | Detalii |
|-----------|---------|
| Laptop | MacBook M4 (MPS backend) |
| GPU training | Google Colab T4 (gratuit) |
| Python | 3.12 (miniforge/base) |
| PyTorch | 2.12.1 |
| SAM | segment-anything 1.0 |
| PEFT | 0.19.1 |
| Dataset | ACDC (150 pacienți, NIfTI) |
| Model | SAM ViT-B |

---

## 📚 DOCUMENTE AUXILIARE (Overleaf)

- `Ziua1_Concepte.tex` — explicații conceptuale: de ce Dice mic, resize, checkpoint, task_type, pred galben

---

## 💡 NOTE PENTRU SUSȚINERE

**Întrebări de așteptat și răspunsuri pregătite:**

**Q: De ce LoRA și nu fine-tuning complet?**
A: Fine-tuning complet pe SAM ar necesita resurse computaționale enorme. LoRA adaptează doar ~0.1-1% din parametri prin matrice de rang redus în attention layers, păstrând cunoștințele generale și adaptând doar ce e specific domeniului cardiac.

**Q: De ce Dice=0.23 la zero-shot?**
A: Trei motive: (1) SAM antrenat pe imagini naturale RGB, nu medicale; (2) conversia forțată grayscale→RGB; (3) SAM returnează mască binară, nu poate distinge LVC/MYO/RVC.

**Q: De ce NEAREST pentru resize-ul măștilor?**
A: Măștile conțin etichete discrete (0,1,2,3). Interpolarea bilineară ar produce valori intermediare (ex: 1.5) care nu corespund niciunei clase reale, corupând datele de antrenament.

**Q: Ce aduce LoRA față de zero-shot?**
A: Răspuns de completat după experimente — target: Dice > 0.7 pe LVC.
