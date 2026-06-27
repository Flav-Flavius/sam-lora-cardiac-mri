"""LoRA fine-tuning CLI for SAM on ACDC slices — PER-STRUCTURĂ.

Training loop corect: graful PyTorch rămâne intact de la
image encoder → mask decoder → loss → .backward().

Per-structură (LVC=1, MYO=2, RVC=3):
- prompt din centroidul structurii k (mask == k)
- țintă binară per structură (mask == k)
- embedding cache: image_encoder O DATĂ per slice, refolosit pentru toate structurile
- un pas de optimizare per slice, pe loss-ul agregat al structurilor prezente
  (aliniat cu SAMed și MedSAM: un obiectiv per imagine, un backward)
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
    """BCE + Dice — standard în segmentare medicală (neponderat, ca MedSAM)."""
    bce = F.binary_cross_entropy_with_logits(pred, target)
    pred_sigmoid = torch.sigmoid(pred)
    dice = dice_loss(pred_sigmoid, target)
    return bce + dice


# ---------------------------------------------------------------------------
# Prompt encoding helper — per structură
# ---------------------------------------------------------------------------

def build_point_prompt(mask_np: np.ndarray, structure_id: int, device: torch.device):
    """Construiește prompt de punct din centrul de masă al structurii `structure_id`.

    Returnează tensori PyTorch gata pentru SAM prompt encoder.
    """
    ys, xs = np.where(mask_np == structure_id)
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
# Image encoding — O SINGURĂ DATĂ per slice (embedding cache)
# ---------------------------------------------------------------------------

def encode_image(sam_model, image_np: np.ndarray, device: torch.device):
    """Trece imaginea prin image_encoder o singură dată, cu normalizare ImageNet.

    SAM ViT-B a fost antrenat pe intrări normalizate cu statisticile ImageNet.
    Aplicăm aceeași normalizare (medie/deviație pe canal, scara 0-255) pentru ca
    encoder-ul să primească intrarea în distribuția pe care o așteaptă.
    """
    img = image_np.astype(np.float32)
    img = (img - img.min()) / max(1e-6, img.max() - img.min())
    img = (img * 255.0)
    image_rgb = np.stack([img, img, img], axis=0)  # (3, H, W)
    image_t = torch.from_numpy(image_rgb).float().unsqueeze(0).to(device)  # (1, 3, H, W)
    image_t = torch.nn.functional.interpolate(image_t, size=(1024, 1024), mode="bilinear", align_corners=False)

    # Normalizare ImageNet (statisticile cu care a fost antrenat encoder-ul SAM)
    pixel_mean = torch.tensor([123.675, 116.28, 103.53], device=device).view(1, 3, 1, 1)
    pixel_std = torch.tensor([58.395, 57.12, 57.375], device=device).view(1, 3, 1, 1)
    image_t = (image_t - pixel_mean) / pixel_std

    return sam_model.image_encoder(image_t)


# ---------------------------------------------------------------------------
# Forward pentru O structură, refolosind image_embeddings precalculat
# ---------------------------------------------------------------------------

def sam_forward(sam_model, image_embeddings, mask_np: np.ndarray, structure_id: int, device: torch.device):
    """Forward pentru structura `structure_id`, cu image_embeddings precalculat.

    Encoder-ul NU rulează aici (a rulat o dată în encode_image). Graful rămâne
    intact: backward din loss propagă prin decoder + prin image_embeddings
    înapoi la LoRA din encoder.
    """
    # Prompt encoding pentru structura k
    coords, labels = build_point_prompt(mask_np, structure_id, device)
    if coords is None:
        return None  # structura absentă în acest slice

    sparse_embeddings, dense_embeddings = sam_model.prompt_encoder(
        points=(coords, labels),
        boxes=None,
        masks=None,
    )

    # Mask decoder — returnează logits (pre-sigmoid)
    low_res_masks, _ = sam_model.mask_decoder(
        image_embeddings=image_embeddings,
        image_pe=sam_model.prompt_encoder.get_dense_pe(),
        sparse_prompt_embeddings=sparse_embeddings,
        dense_prompt_embeddings=dense_embeddings,
        multimask_output=False,
    )
    # low_res_masks: (1, 1, 256, 256) — logits

    # Upsample la dimensiunea originală
    H, W = mask_np.shape
    pred_logits = F.interpolate(low_res_masks, size=(H, W), mode="bilinear", align_corners=False)
    pred_logits = pred_logits.squeeze(0).squeeze(0)  # (H, W)

    # Ground truth binar pentru structura k
    target = torch.from_numpy((mask_np == structure_id).astype(np.float32)).to(device)  # (H, W)

    return combined_loss(pred_logits, target)


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--drive-output", default=None,
                    help="Cale Google Drive pentru salvare checkpoint")
    ap.add_argument("--max-slices", type=int, default=None,
                    help="Limitează nr. de slice-uri per epocă (smoke test local). None = tot setul.")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])
    model_cfg = cfg["MODEL"]
    train_cfg = cfg["TRAIN"]
    log_cfg = cfg["LOG"]

    # Structurile de segmentat per-structură (1=LVC, 2=MYO, 3=RVC)
    structures = list(train_cfg.get("STRUCTURES", [1, 2, 3]))
    print(f"Structures (per-structure training): {structures}")

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
    print(f"Trainable parameters: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

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
    steps_per_epoch = args.max_slices if args.max_slices else len(dl)
    total_steps = epochs * steps_per_epoch
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
    last_path = out_dir / "last.pt"

    # Google Drive output (opțional)
    drive_ckpt = None
    last_drive = None
    if args.drive_output:
        drive_dir = Path(args.drive_output) / f"rank{rank}"
        drive_dir.mkdir(parents=True, exist_ok=True)
        drive_ckpt = drive_dir / "best.pt"
        last_drive = drive_dir / "last.pt"

    # Resume din last.pt dacă există
    start_epoch = 0
    best_loss = float("inf")
    if last_drive and Path(last_drive).exists():
        print(f"Resuming from Drive: {last_drive}")
        resume = torch.load(last_drive, map_location=device)
        sam_lora.load_state_dict(resume["state_dict"])
        optim.load_state_dict(resume["optim"])
        scheduler.load_state_dict(resume["scheduler"])
        start_epoch = resume["epoch"]
        best_loss = resume.get("best_loss", float("inf"))
        print(f"  → Resuming from epoch {start_epoch + 1}/{epochs} | best_loss so far: {best_loss:.4f}")
    elif last_path.exists():
        print(f"Resuming from local: {last_path}")
        resume = torch.load(last_path, map_location=device)
        sam_lora.load_state_dict(resume["state_dict"])
        optim.load_state_dict(resume["optim"])
        scheduler.load_state_dict(resume["scheduler"])
        start_epoch = resume["epoch"]
        best_loss = resume.get("best_loss", float("inf"))
        print(f"  → Resuming from epoch {start_epoch + 1}/{epochs} | best_loss so far: {best_loss:.4f}")

    # Training loop
    global_step = 0

    for epoch in range(start_epoch, epochs):
        sam_lora.train()
        running_loss = 0.0
        valid_steps = 0      # slice-uri procesate (cel puțin o structură prezentă)
        struct_count = 0     # perechi (slice, structură) procesate — pentru diagnostic

        for i, batch in enumerate(dl):
            if args.max_slices and i >= args.max_slices:
                break

            image_np = batch.image.squeeze(0).squeeze(0).numpy()  # (H,W)
            mask_np = batch.mask.squeeze(0).numpy()               # (H,W)

            # Encoder o singură dată per slice (embedding cache)
            image_embeddings = encode_image(sam_lora, image_np, device)

            # Acumulează loss-ul structurilor prezente în acest slice
            slice_loss = None
            for structure_id in structures:
                if (mask_np == structure_id).sum() == 0:
                    continue  # structura absentă în acest slice
                loss_k = sam_forward(sam_lora, image_embeddings, mask_np, structure_id, device)
                if loss_k is None:
                    continue
                slice_loss = loss_k if slice_loss is None else slice_loss + loss_k
                struct_count += 1

            if slice_loss is None:
                continue  # niciun structură prezentă (slice gol)

            optim.zero_grad()
            slice_loss.backward()    # un singur backward per slice, fără retain_graph
            torch.nn.utils.clip_grad_norm_(
                [p for p in sam_lora.parameters() if p.requires_grad], 1.0
            )
            optim.step()
            scheduler.step()

            running_loss += slice_loss.item()
            valid_steps += 1
            global_step += 1

        avg_loss = running_loss / max(1, valid_steps)
        lr_now = scheduler.get_last_lr()[0]
        print(f"Epoch {epoch+1}/{epochs} | loss={avg_loss:.4f} | lr={lr_now:.2e} "
              f"| slices={valid_steps} | struct_pairs={struct_count}")

        # Salvare best.pt doar când loss-ul scade
        if avg_loss < best_loss:
            best_loss = avg_loss
            ckpt = {"state_dict": sam_lora.state_dict(), "cfg": cfg, "epoch": epoch+1, "loss": best_loss}
            torch.save(ckpt, ckpt_path)
            if drive_ckpt:
                torch.save(ckpt, drive_ckpt)
                print(f"  → Saved best to Drive: {drive_ckpt}")

        # Salvare last.pt la fiecare epocă (pentru resume)
        last_ckpt = {
            "state_dict": sam_lora.state_dict(),
            "optim": optim.state_dict(),
            "scheduler": scheduler.state_dict(),
            "epoch": epoch + 1,
            "best_loss": best_loss,
            "cfg": cfg,
        }
        torch.save(last_ckpt, last_path)
        if last_drive:
            torch.save(last_ckpt, last_drive)
            print(f"  → Saved last to Drive: {last_drive}")

    print(f"\nTraining complet. Best loss: {best_loss:.4f}")
    print(f"Checkpoint saved at: {ckpt_path}")


if __name__ == "__main__":
    main()