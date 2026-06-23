"""Cross-dataset evaluation CLI for SAM or LoRA-adapted SAM.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import yaml

from sam_lora.data import SliceDataset
from sam_lora.metrics import boundary_f_score, dice_score, hd95
from sam_lora.prompts import box_prompt_from_mask, grid_prompt_for_image, point_prompt_from_mask
from sam_lora.sam_wrapper import SamPredictorWrapper


def eval_dataset(predictor: SamPredictorWrapper, ds: SliceDataset, prompt_cfg: dict) -> tuple[float, float, float]:
    dice_list, hd_list, bf_list = [], [], []
    for i in range(len(ds)):
        sample = ds[i]
        img = sample.image.numpy().squeeze(0)
        mask = sample.mask.numpy() if sample.mask is not None else None
        predictor.set_image(img)
        if mask is None:
            continue
        if prompt_cfg["TYPE"] == "point":
            pp = point_prompt_from_mask(mask > 0, jitter_sigma=float(prompt_cfg.get("POINT_JITTER", 0)))
            pred = predictor.predict_with_point(pp.points, pp.labels)
        elif prompt_cfg["TYPE"] == "box":
            box, _ = box_prompt_from_mask(mask > 0, scale=float(prompt_cfg.get("BOX_SCALE", 1.0)))
            pred = predictor.predict_with_box(box)
        else:
            h, w = mask.shape
            pp = grid_prompt_for_image(w, h, density=int(prompt_cfg.get("GRID_DENSITY", 5)))
            pred = predictor.predict_with_point(pp.points, pp.labels)
        pred_lbl = (pred > 0.5).astype(np.int64) * max(1, int(mask.max()))
        labels = list(range(1, int(mask.max()) + 1)) or [1]
        dice_list.append(np.mean([dice_score(pred_lbl, mask, l) for l in labels]))
        hd_list.append(np.mean([hd95(pred_lbl, mask, l) for l in labels]))
        bf_list.append(boundary_f_score(pred_lbl, mask, tolerance_px=2))
    return float(np.mean(dice_list)), float(np.mean(hd_list)), float(np.mean(bf_list))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=False)
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    datasets = cfg["DATASETS"]
    model_cfg = cfg["MODEL"]
    prompt_cfg = cfg["PROMPT"]
    log_cfg = cfg["LOG"]

    predictor = SamPredictorWrapper(variant=model_cfg.get("SAM_VARIANT", "vit_b"), checkpoint=model_cfg.get("CHECKPOINT"))
    # Loading LoRA weights into predictor.model if provided is left as future work

    out_dir = Path(log_cfg.get("OUTPUT_DIR", "outputs/cross_eval"))
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "cross_eval.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset", "dice_macro", "hd95_macro", "bf"])
        for d in datasets:
            ds = SliceDataset(root=d["ROOT"], split="test", img_size=(256, 256), has_masks=True)
            dice_m, hd_m, bf_m = eval_dataset(predictor, ds, prompt_cfg)
            writer.writerow([d["NAME"], f"{dice_m:.4f}", f"{hd_m:.2f}", f"{bf_m:.4f}"])
    print(f"Saved cross-dataset metrics to {csv_path}")


if __name__ == "__main__":
    main()


