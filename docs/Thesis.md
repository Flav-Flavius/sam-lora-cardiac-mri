# Master’s Thesis Proposal

## Evaluation and Adaptation of the Segment Anything Model (SAM) on Medical Images with LoRA Fine‑Tuning

**Student:** Cenuse Flavius Dragos
**Email:** [Cenuse.Sa.Flavius@student.utcluj.ro](mailto:Cenuse.Sa.Flavius@student.utcluj.ro)
**Date:** July 4, 2025

---

## Abstract

This work proposes evaluating the performance of the Segment Anything model (SAM) applied to medical images and adapting it using the Low‑Rank Adaptation (LoRA) fine‑tuning technique. The open‑source ACDC dataset will be used, which contains cardiac MRI images and gold‑standard segmentations for anatomical structures (myocardium, chambers, etc.). Performance will be analyzed using metrics specific to medical image segmentation (Dice, Hausdorff, Boundary F).

---

## 1. Introduction and Motivation

Automatic segmentation of medical images is crucial for diagnosis. Modern models such as SAM offer zero‑shot generalization but are not optimized for medical images. Adaptation with LoRA can provide a balance between performance and efficiency, which is why I propose using SAM + LoRA on the ACDC dataset (cardiac cine‑MRI).

---

## 2. State of the Art

* **SAM‑Med2D \[2]:** zero‑shot evaluation on 12 2D medical datasets
* **MedSAM \[4]:** LoRA on SAM‑ViT‑B for multimodal images
* **MA‑SAM \[1]:** adapting SAM for 3D/video segmentation
* **SAM‑CLIP \[3]:** integrating CLIP for text‑guided segmentation
* **Medical SAM Adapter \[5]:** adapters for low‑cost fine‑tuning

None of them addresses cardiac cine‑MRI images (ACDC). This is the novelty brought by the proposed work.

---

## 3. Objectives and Hypothesis

* Evaluate zero‑shot SAM on ACDC images
* Adapt SAM with LoRA (rank 4/8/16)
* Compare prompting strategies (point, box, grid)
* Test robustness to prompt noise
* Evaluate on external data (M\&Ms, Sunnybrook)

**Hypothesis:** LoRA can improve SAM’s performance on cardiac images compared to the zero‑shot variant.

---

## 4. Proposed Methodology

### 4.1 Data and Preprocessing

* The ACDC dataset: cardiac MRI, manually segmented
* DICOM → PNG conversion, grayscale replication

### 4.2 Zero‑Shot SAM Evaluation

* Prompts: point, box
* Metrics: Dice, Boundary F, Hausdorff

### 4.3 LoRA Fine‑Tuning on SAM

* Rank: 4, 8, 16
* Framework: PEFT, W\&B logging

### 4.4 Advanced Prompting

* Grid of points, self‑prompting
* Measuring sensitivity to point variations (jitter)

### 4.5 Ablation and Cost/Performance Evaluation

* Dice vs. time, VRAM
* Reporting clinical metrics: LV mass error

### 4.6 Cross‑Dataset Testing (Generalization)

* Zero‑shot test on M\&Ms, Sunnybrook
* Visual comparisons + aggregated scores

### 4.7 Visualization of Results

* Segmentation vs. ground truth
* Side‑by‑side visualizations + negative examples

### 4.8 MLOps and Reproducibility

* Code on GitHub
* Configurations saved with MLflow, exportable notebook

---

## 5. Original Contributions

* The first LoRA adaptation of SAM on cardiac cine‑MRI (ACDC)
* Robust‑prompt + jitter study
* Comparison of LoRA ranks + prompting + cross‑evaluation
* Fully reproducible workflow

---

## References

\[1] Xiangxiang Chen et al. *Ma‑sam: Modality‑agnostic sam adaptation for 3d/video medical image segmentation.* Medical Image Analysis, 2025.

\[2] Yuying Huang et al. *Sam‑med2d: Comprehensive studies on segment anything model for medical image segmentation.* arXiv preprint arXiv:2308.16184, 2023.

\[3] Junlin Lu et al. *Sam‑clip: Merging vision foundation models towards semantic and spatial understanding.* In CVPR Workshop on ELVM, 2024. arXiv:2310.15308.

\[4] Jintang Ma, Yaozong Wang, et al. *Medsam: Segment anything model for medical images.* Nature Communications, 2024.

\[5] Hao Wu et al. *Adapting segment anything model for medical image segmentation.* Medical Image Analysis, 2024.
