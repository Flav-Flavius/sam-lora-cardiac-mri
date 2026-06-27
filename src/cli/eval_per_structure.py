"""Evaluare PER-STRUCTURĂ pe ACDC: Dice + HD95 per structură (LVC/MYO/RVC).

Doua moduri, acelasi script:
  - ZERO-SHOT (fara --checkpoint): SAM gol, cu normalizare ImageNet.
    Re-masoara baseline-ul (inlocuieste vechiul 0.2321 masurat FARA normalizare).
  - LoRA (cu --checkpoint best.pt): aplica adaptoarele LoRA + incarca greutatile.
    rank/alpha/target_modules se citesc DIN checkpoint (ckpt["cfg"]), deci
    imposibil de nepotrivit configul cu checkpointul.

Logica oglindeste antrenamentul per-structura:
  encode imagine O DATA (cu normalizare) -> pentru fiecare structura k prezenta:
    prompt din centroid(mask==k) -> forward decoder -> sigmoid+prag -> Dice(pred, mask, k)

CRITIC: encode_image si build_point_prompt sunt IMPORTATE din train_lora.py,
nu rescrise. Normalizarea ImageNet si centroidul sunt astfel GARANTAT identice
cu antrenamentul. O divergenta aici ar invalida comparatia train/eval.

Exemple:
  # zero-shot baseline (re-masurare cu normalizare):
  python src/cli/eval_per_structure.py \
      --config configs/eval_zero_shot.yaml --tag zero_shot

  # LoRA rank 4:
  python src/cli/eval_per_structure.py \
      --config configs/eval_zero_shot.yaml \
      --checkpoint /content/drive/MyDrive/sam-lora-cardiac-mri/checkpoints_encoder/rank4/best.pt \
      --tag rank4
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml

from sam_lora.data import SliceDataset
from sam_lora.lora import apply_lora_to_sam
from sam_lora.metrics import dice_score, hd95
from sam_lora.sam_wrapper import SamPredictorWrapper

# Refolosim EXACT piesele care trebuie sa fie identice cu antrenamentul.
# (normalizare ImageNet + centroid per structura). NU le rescriem.
from cli.train_lora import encode_image, build_point_prompt


# Etichete ACDC
STRUCTURE_NAMES = {1: "LVC", 2: "MYO", 3: "RVC"}


@torch.no_grad()
def predict_structure(sam_model, image_embeddings, mask_np, structure_id, device):
    """Forward pentru O structura -> masca binara (0/1) prezisa.

    Spre deosebire de sam_forward (care merge pana la loss), aici ne oprim la
    PREDICTIE: aplicam sigmoid pe logits si prag 0.5. Intoarce None daca
    structura e absenta in felie (centroid imposibil).
    """
    coords, labels = build_point_prompt(mask_np, structure_id, device)
    if coords is None:
        return None  # structura absenta in aceasta felie

    sparse_emb, dense_emb = sam_model.prompt_encoder(
        points=(coords, labels), boxes=None, masks=None,
    )
    low_res_masks, _ = sam_model.mask_decoder(
        image_embeddings=image_embeddings,
        image_pe=sam_model.prompt_encoder.get_dense_pe(),
        sparse_prompt_embeddings=sparse_emb,
        dense_prompt_embeddings=dense_emb,
        multimask_output=False,
    )
    H, W = mask_np.shape
    logits = F.interpolate(low_res_masks, size=(H, W), mode="bilinear", align_corners=False)
    logits = logits.squeeze(0).squeeze(0)  # (H, W)

    # CRITIC: sigmoid INAINTE de prag. Logits sunt in (-inf,+inf);
    # prag 0.5 direct pe logits ar taia la sigmoid(0.5)~=0.62, nu 0.5.
    prob = torch.sigmoid(logits)
    pred_bin = (prob > 0.5).cpu().numpy().astype(np.int64)  # 0/1
    return pred_bin


def build_model(model_cfg, checkpoint, device):
    """Construieste modelul de evaluat.

    - checkpoint None  -> SAM gol (zero-shot), fara LoRA.
    - checkpoint dat   -> recreeaza LoRA din ckpt["cfg"] + incarca greutatile.

    Returneaza (sam_model_de_apelat, eticheta_mod).
    """
    predictor = SamPredictorWrapper(
        variant=model_cfg.get("SAM_VARIANT", "vit_b"),
        checkpoint=model_cfg.get("CHECKPOINT"),
    )
    sam_model = predictor.predictor.model

    if checkpoint is None:
        sam_model.to(device).eval()
        return sam_model, "zero-shot"

    # --- mod LoRA ---
    ckpt = torch.load(checkpoint, map_location=device)
    # rank/alpha/target_modules DIN checkpoint -> potrivire garantata cu greutatile
    lora_cfg = ckpt["cfg"]["MODEL"]["LORA"]
    rank = int(lora_cfg["RANK"])
    alpha = int(lora_cfg["ALPHA"])
    target_modules = list(lora_cfg.get("TARGET_MODULES", ["qkv"]))

    sam_lora = apply_lora_to_sam(
        sam_model, rank=rank, alpha=alpha, target_modules=target_modules
    )
    missing, unexpected = sam_lora.load_state_dict(ckpt["state_dict"], strict=False)
    # Diagnostic: daca apar chei LoRA lipsa/in plus, structura nu se potriveste.
    lora_missing = [k for k in missing if "lora_" in k]
    lora_unexpected = [k for k in unexpected if "lora_" in k]
    if lora_missing or lora_unexpected:
        print(f"  ATENTIE: chei LoRA nepotrivite — "
              f"missing={len(lora_missing)} unexpected={len(lora_unexpected)}")
    else:
        print(f"  LoRA incarcat OK (rank={rank}, alpha={alpha}, modules={target_modules})")

    sam_lora.to(device).eval()
    return sam_lora, f"lora-rank{rank}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="config cu DATA.ROOT + MODEL (ex: eval_zero_shot.yaml)")
    ap.add_argument("--checkpoint", default=None, help="best.pt LoRA. Absent => zero-shot.")
    ap.add_argument("--tag", default=None, help="eticheta pt numele fisierului CSV (ex: rank4, zero_shot)")
    ap.add_argument("--structures", default="1,2,3", help="structuri de evaluat, ex '1,2,3'")
    ap.add_argument("--max-slices", type=int, default=None, help="limiteaza nr. felii (smoke test)")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])
    model_cfg = cfg["MODEL"]

    device = torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    structures = [int(s) for s in args.structures.split(",")]

    ds = SliceDataset(root=data_root, split="test", img_size=(img_h, img_w), has_masks=True)
    sam_model, mode = build_model(model_cfg, args.checkpoint, device)
    print(f"Mod evaluare: {mode} | felii test: {len(ds)} | structuri: {structures}")

    tag = args.tag or mode
    out_dir = Path("outputs/per_structure")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"metrics_{tag}.csv"

    # acumulatoare per structura pentru medie globala
    dice_acc = {k: [] for k in structures}
    hd_acc = {k: [] for k in structures}

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["id"]
        for k in structures:
            header += [f"dice_{STRUCTURE_NAMES[k].lower()}", f"hd95_{STRUCTURE_NAMES[k].lower()}"]
        header += ["dice_macro"]
        writer.writerow(header)

        for i in range(len(ds)):
            if args.max_slices and i >= args.max_slices:
                break
            sample = ds[i]
            image_np = sample.image.numpy().squeeze(0)  # (H,W)
            mask_np = sample.mask.numpy()               # (H,W) cu 0/1/2/3

            # encode O DATA per felie (cu normalizare ImageNet — importat din train)
            # no_grad: la evaluare nu antrenam, deci nu construim graf (altfel OOM la zero-shot)
            with torch.no_grad():
                image_embeddings = encode_image(sam_model, image_np, device)

            row = [sample.meta["id"]]
            dice_this_slice = []
            for k in structures:
                if (mask_np == k).sum() == 0:
                    # structura absenta -> nu o numaram (nici la felie, nici la medie)
                    row += ["", ""]
                    continue
                pred_bin = predict_structure(sam_model, image_embeddings, mask_np, k, device)
                if pred_bin is None:
                    row += ["", ""]
                    continue

                # CRITIC: eticheteaza pred cu k (nu 1), fiindca dice_score face (pred==label).
                pred_lbl = pred_bin * k
                d = dice_score(pred_lbl, mask_np, k)
                h = hd95(pred_lbl, mask_np, k)

                dice_acc[k].append(d)
                hd_acc[k].append(h)
                dice_this_slice.append(d)
                row += [f"{d:.4f}", f"{h:.2f}"]

            dice_macro_slice = float(np.mean(dice_this_slice)) if dice_this_slice else 0.0
            row.append(f"{dice_macro_slice:.4f}")
            writer.writerow(row)

    # --- sumar global ---
    print("\n" + "=" * 52)
    print(f"REZULTATE [{tag}] — medie pe setul de test")
    print("=" * 52)
    macro_per_struct = []
    for k in structures:
        if dice_acc[k]:
            md = float(np.mean(dice_acc[k]))
            mh = float(np.mean(hd_acc[k]))
            macro_per_struct.append(md)
            print(f"  {STRUCTURE_NAMES[k]:4s}: Dice={md:.4f}  HD95={mh:.2f}  (n={len(dice_acc[k])})")
        else:
            print(f"  {STRUCTURE_NAMES[k]:4s}: fara felii prezente")
    if macro_per_struct:
        print(f"  {'MACRO':4s}: Dice={np.mean(macro_per_struct):.4f}")
    print(f"\nCSV salvat: {csv_path}")


if __name__ == "__main__":
    main()
