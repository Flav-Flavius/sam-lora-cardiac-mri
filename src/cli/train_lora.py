"""LoRA fine-tuning CLI for SAM on ACDC slices.

Training loop corect: graful PyTorch rămâne intact de la
image encoder → mask decoder → loss → .backward().

Modificări față de versiunea originală:
- Eliminat predictor API (numpy) din training loop
- Loss calculat direct pe tensori PyTorch
- Backprop real pe BCE + Dice loss față de GT masks
- Adăugat scheduler cu warmup
- Adăugat salvare checkpoint pe Google Drive
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


# ---------------------------------------------------------------------------
# Loss functions
# ---------------------------------------------------------------------------

def dice_loss(pred: torch.Tensor, target: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """Dice loss pe tensori PyTorch. pred și target în [0, 1]."""
    intersection = (pred * target).sum()
    return 1.0 - (2.0 * intersection + eps) / (pred.sum() + target.sum() + eps)


def combined_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """BCE + Dice — standard în segmentare medicală."""
    bce = F.binary_cross_entropy_with_logits(pred, target)
    pred_sigmoid = torch.sigmoid(pred)
    dice = dice_loss(pred_sigmoid, target)
    return bce + dice


# ---------------------------------------------------------------------------
# Prompt encoding helper
# ---------------------------------------------------------------------------

def build_point_prompt(mask_np: np.ndarray, device: torch.device):
    """Construiește prompt de punct din centrul de masă al GT mask.

    Returnează tensori PyTorch gata pentru SAM prompt encoder.
    """
    ys, xs = np.where(mask_np > 0)
    if xs.size == 0:
        return None, None

    cx = float(xs.mean())
    cy = float(ys.mean())

    # SAM prompt encoder așteaptă: (B, N, 2) și (B, N)
    coords = torch.tensor([[[[cx, cy]]]], dtype=torch.float32, device=device)  # (1, 1, 1, 2)
    coords = coords.squeeze(0)  # (1, 1, 2)
    labels = torch.ones((1, 1), dtype=torch.int, device=device)  # (1, 1)

    return coords, labels


# ---------------------------------------------------------------------------
# Single forward pass prin SAM cu grad graph intact
# ---------------------------------------------------------------------------

def sam_forward(sam_model, image_np: np.ndarray, mask_np: np.ndarray, device: torch.device):
    """Forward pass complet cu grad graph intact pentru training.

    Diferența față de predictor API:
    - Totul rămâne tensor PyTorch
    - Nu se convertește în numpy până la final
    - .backward() poate propaga gradienți până la LoRA params
    """
    # 1. Pregătire imagine — grayscale → RGB, normalizare
    img = image_np.astype(np.float32)
    img = (img - img.min()) / max(1e-6, img.max() - img.min())
    img = (img * 255.0)
    image_rgb = np.stack([img, img, img], axis=0)  # (3, H, W)
    image_t = torch.from_numpy(image_rgb).float().unsqueeze(0).to(device)  # (1, 3, H, W)
    # SAM ViT-B necesită 1024x1024
    image_t = torch.nn.functional.interpolate(image_t, size=(1024, 1024), mode="bilinear", align_corners=False)

    # 2. Image encoder — LoRA e aici, deci NO no_grad()
    image_embeddings = sam_model.image_encoder(image_t)  # (1, 256, 64, 64)

    # 3. Prompt encoding
    coords, labels = build_point_prompt(mask_np, device)
    if coords is None:
        return None  # slice fără GT, skip

    sparse_embeddings, dense_embeddings = sam_model.prompt_encoder(
        points=(coords, labels),
        boxes=None,
        masks=None,
    )

    # 4. Mask decoder — returnează logits (pre-sigmoid)
    low_res_masks, _ = sam_model.mask_decoder(
        image_embeddings=image_embeddings,
        image_pe=sam_model.prompt_encoder.get_dense_pe(),
        sparse_prompt_embeddings=sparse_embeddings,
        dense_prompt_embeddings=dense_embeddings,
        multimask_output=False,
    )
    # low_res_masks: (1, 1, 256, 256) — logits

    # 5. Upsample la dimensiunea originală
    H, W = mask_np.shape
    pred_logits = F.interpolate(low_res_masks, size=(H, W), mode="bilinear", align_corners=False)
    pred_logits = pred_logits.squeeze(0).squeeze(0)  # (H, W)

    # 6. Ground truth tensor
    target = torch.from_numpy((mask_np > 0).astype(np.float32)).to(device)  # (H, W)

    return combined_loss(pred_logits, target)


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--drive-output", default=None,
                    help="Cale Google Drive pentru salvare checkpoint")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])
    model_cfg = cfg["MODEL"]
    train_cfg = cfg["TRAIN"]
    log_cfg = cfg["LOG"]

    # Seed pentru reproductibilitate
    seed = int(train_cfg.get("SEED", 42))
    torch.manual_seed(seed)
    np.random.seed(seed)

    # Încărcare SAM + aplicare LoRA
    predictor = SamPredictorWrapper(
        variant=model_cfg.get("SAM_VARIANT", "vit_b"),
        checkpoint=model_cfg.get("CHECKPOINT")
    )
    sam_model = predictor.predictor.model
    sam_lora = apply_lora_to_sam(
        sam_model,
        rank=int(model_cfg["LORA"]["RANK"]),
        alpha=int(model_cfg["LORA"]["ALPHA"]),
        target_modules=list(model_cfg["LORA"].get("TARGET_MODULES", ["q_proj", "k_proj", "v_proj", "o_proj"]))
    )

    # Îngheață tot, dezgheață doar LoRA
    for name, p in sam_lora.named_parameters():
        p.requires_grad = ("lora_" in name)

    trainable = sum(p.numel() for p in sam_lora.parameters() if p.requires_grad)
    total = sum(p.numel() for p in sam_lora.parameters())
    print(f"Parametri trainabili: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    # Dataset și DataLoader
    ds_train = SliceDataset(
        root=data_root, split="train",
        img_size=(img_h, img_w), has_masks=True
    )

    dl = DataLoader(
        ds_train,
        batch_size=1,
        shuffle=True,
        num_workers=0,
        collate_fn=lambda batch: batch[0]  # returnează Sample direct, fără collate
    )

    device = predictor.device
    sam_lora.to(device)

    # Optimizer
    optim = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, sam_lora.parameters()),
        lr=float(train_cfg.get("LR", 5e-5)),
        weight_decay=float(train_cfg.get("WEIGHT_DECAY", 1e-2))
    )

    # Scheduler cu warmup liniar
    epochs = int(train_cfg.get("EPOCHS", 40))
    total_steps = epochs * len(dl)
    warmup_steps = int(total_steps * float(train_cfg.get("WARMUP_RATIO", 0.05)))

    def lr_lambda(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        return 1.0

    scheduler = torch.optim.lr_scheduler.LambdaLR(optim, lr_lambda)

    # Output dirs
    rank = int(model_cfg["LORA"]["RANK"])
    out_dir = Path(log_cfg.get("OUTPUT_DIR", f"outputs/train_lora/rank{rank}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "best.pt"

    # Google Drive output (opțional)
    drive_ckpt = None
    if args.drive_output:
        drive_dir = Path(args.drive_output) / f"rank{rank}"
        drive_dir.mkdir(parents=True, exist_ok=True)
        drive_ckpt = drive_dir / "best.pt"

    # Training loop
    best_loss = float("inf")
    global_step = 0

    for epoch in range(epochs):
        sam_lora.train()
        running_loss = 0.0
        valid_steps = 0

        for batch in dl:
            image_np = batch.image.squeeze(0).squeeze(0).numpy()  # (H,W)
            mask_np = batch.mask.squeeze(0).numpy()               # (H,W)
            loss = sam_forward(sam_lora, image_np, mask_np, device)
            if loss is None:
                continue

            optim.zero_grad()
            loss.backward()          # grad real, nu placeholder
            torch.nn.utils.clip_grad_norm_(
                [p for p in sam_lora.parameters() if p.requires_grad], 1.0
            )
            optim.step()
            scheduler.step()

            running_loss += loss.item()
            valid_steps += 1
            global_step += 1

        avg_loss = running_loss / max(1, valid_steps)
        lr_now = scheduler.get_last_lr()[0]
        print(f"Epoch {epoch+1}/{epochs} | loss={avg_loss:.4f} | lr={lr_now:.2e} | steps={valid_steps}")

        # Salvare cel mai bun checkpoint
        if avg_loss < best_loss:
            best_loss = avg_loss
            ckpt = {"state_dict": sam_lora.state_dict(), "cfg": cfg, "epoch": epoch+1, "loss": best_loss}
            torch.save(ckpt, ckpt_path)
            if drive_ckpt:
                torch.save(ckpt, drive_ckpt)
                print(f"  → Saved to Drive: {drive_ckpt}")

    print(f"\nTraining complet. Best loss: {best_loss:.4f}")
    print(f"Checkpoint saved at: {ckpt_path}")


if __name__ == "__main__":
    main()