"""Zero-shot evaluation CLI using SAM with configurable prompts.

Example:
    sam-lora-eval-zero-shot --config configs/eval_zero_shot.yaml
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import numpy as np
import torch
import yaml

from sam_lora.data import SliceDataset
from sam_lora.metrics import boundary_f_score, dice_score, hd95
from sam_lora.prompts import box_prompt_from_mask, grid_prompt_for_image, point_prompt_from_mask
from sam_lora.sam_wrapper import SamPredictorWrapper
from sam_lora.visualize import side_by_side


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])
    prompt_cfg = cfg["PROMPT"]
    model_cfg = cfg["MODEL"]
    eval_cfg = cfg["EVAL"]
    log_cfg = cfg["LOG"]

    ds = SliceDataset(root=data_root, split="test", img_size=(img_h, img_w), has_masks=True)
    predictor = SamPredictorWrapper(variant=model_cfg.get("SAM_VARIANT", "vit_b"), checkpoint=model_cfg.get("CHECKPOINT"))

    out_dir = Path(log_cfg.get("OUTPUT_DIR", "outputs/zero_shot"))
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "metrics.csv"
    vis_dir = out_dir / "vis"
    if eval_cfg.get("SAVE_VIS", False):
        vis_dir.mkdir(parents=True, exist_ok=True)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "dice_macro", "hd95_macro", "bf"])
        for i in range(len(ds)):
            sample = ds[i]
            image = sample.image.numpy().squeeze(0)
            mask = sample.mask.numpy()
            predictor.set_image(image)

            if prompt_cfg["TYPE"] == "point":
                pp = point_prompt_from_mask(mask > 0, jitter_sigma=float(prompt_cfg.get("POINT_JITTER", 0)))
                pred = predictor.predict_with_point(pp.points, pp.labels)
            elif prompt_cfg["TYPE"] == "box":
                box, lbl = box_prompt_from_mask(mask > 0, scale=float(prompt_cfg.get("BOX_SCALE", 1.0)))
                pred = predictor.predict_with_box(box)
            else:
                h, w = mask.shape
                pp = grid_prompt_for_image(w, h, density=int(prompt_cfg.get("GRID_DENSITY", 5)))
                pred = predictor.predict_with_point(pp.points, pp.labels)

            pred_lbl = (pred > 0.5).astype(np.int64) * mask.max()  # naive: treat as foreground of max class

            dice_vals = []
            labels = list(range(1, int(mask.max()) + 1)) or [1]
            for lab in labels:
                dice_vals.append(dice_score(pred_lbl, mask, lab))
            dice_macro = float(np.mean(dice_vals)) if dice_vals else 0.0
            hd_vals = [hd95(pred_lbl, mask, lab) for lab in labels]
            hd_macro = float(np.mean(hd_vals)) if hd_vals else 0.0
            bf = float(boundary_f_score(pred_lbl, mask, tolerance_px=2))

            writer.writerow([sample.meta["id"], f"{dice_macro:.4f}", f"{hd_macro:.2f}", f"{bf:.4f}"])

            if eval_cfg.get("SAVE_VIS", False):
                out_png = vis_dir / f"{sample.meta['id']}.png"
                side_by_side(image, mask, pred_lbl, str(out_png))

    print(f"Saved metrics to {csv_path}")


if __name__ == "__main__":
    main()


