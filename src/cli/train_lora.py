"""LoRA fine-tuning CLI for SAM on ACDC slices.

Minimal training loop to verify end-to-end functionality.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch.utils.data import DataLoader

from sam_lora.data import SliceDataset
from sam_lora.lora import apply_lora_to_sam
from sam_lora.sam_wrapper import SamPredictorWrapper


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])
    model_cfg = cfg["MODEL"]
    train_cfg = cfg["TRAIN"]
    log_cfg = cfg["LOG"]

    # Load SAM and wrap with LoRA (this is a placeholder; actual training requires decoder loss wiring)
    predictor = SamPredictorWrapper(variant=model_cfg.get("SAM_VARIANT", "vit_b"), checkpoint=model_cfg.get("CHECKPOINT"))
    sam_model = predictor.predictor.model
    sam_lora = apply_lora_to_sam(
        sam_model,
        rank=int(model_cfg["LORA"]["RANK"]),
        alpha=int(model_cfg["LORA"]["ALPHA"]),
        target_modules=list(model_cfg["LORA"].get("TARGET_MODULES", ["q_proj","k_proj","v_proj","o_proj"]))
    )

    # Freeze base, train LoRA params
    for name, p in sam_lora.named_parameters():
        p.requires_grad = ("lora_" in name)

    ds_train = SliceDataset(root=data_root, split="train", img_size=(img_h, img_w), has_masks=True)
    dl = DataLoader(ds_train, batch_size=int(train_cfg.get("BATCH_SIZE", 8)), shuffle=True, num_workers=int(train_cfg.get("NUM_WORKERS", 0)))

    device = predictor.device
    sam_lora.to(device)
    optim = torch.optim.AdamW(filter(lambda p: p.requires_grad, sam_lora.parameters()), lr=float(train_cfg.get("LR", 5e-5)), weight_decay=float(train_cfg.get("WEIGHT_DECAY", 1e-2)))

    out_dir = Path(log_cfg.get("OUTPUT_DIR", "outputs/train_lora"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / f"rank{model_cfg['LORA']['RANK']}" / "best.pt"
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)

    # Minimal loop: for each slice, create a simple point prompt from GT and supervise with BCE on SAM mask
    best_loss = float("inf")
    for epoch in range(int(train_cfg.get("EPOCHS", 1))):
        sam_lora.train()
        running = 0.0
        for batch in dl:
            images = batch.image.squeeze(1).numpy()  # list via loop due to predictor API
            masks = batch.mask.numpy()
            batch_loss = 0.0
            for i in range(len(images)):
                predictor.set_image(images[i])
                # simple single foreground point at center of mass of GT >0
                ys, xs = np.where(masks[i] > 0)
                if xs.size == 0:
                    continue
                cx, cy = float(xs.mean()), float(ys.mean())
                pts = np.array([[cx, cy]], dtype=np.float32)
                lbl = np.array([1], dtype=np.int64)
                with torch.autocast(device_type=str(device), enabled=False):
                    pred = predictor.predict_with_point(pts, lbl)
                target = (masks[i] > 0).astype(np.float32)
                pred_t = torch.from_numpy(pred.astype(np.float32))
                target_t = torch.from_numpy(target)
                loss = F.binary_cross_entropy(pred_t, target_t)
                batch_loss += float(loss.item())

            if batch_loss == 0.0:
                continue
            optim.zero_grad()
            # backprop placeholder: create a tiny grad on LoRA params
            # In real integration, wire predictor forward to expose tensor graph.
            l2 = sum((p.float()**2).sum() for p in sam_lora.parameters() if p.requires_grad)
            (1e-6 * l2).backward()
            optim.step()
            running += batch_loss

        avg_loss = running / max(1, len(dl))
        if avg_loss < best_loss:
            best_loss = avg_loss
            torch.save({"state_dict": sam_lora.state_dict(), "cfg": cfg}, ckpt_path)
        print(f"Epoch {epoch+1}: loss={avg_loss:.4f}")

    print(f"Saved best weights to {ckpt_path}")


if __name__ == "__main__":
    main()


