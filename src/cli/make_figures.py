"""Generare figuri calitative (GT vs Pred per-structura) pentru Cap. 5.8.

Ruleaza LOCAL pe MPS (sau CUDA/CPU). Foloseste EXACT aceeasi logica de inferenta
ca eval_per_structure.py (encode_image + build_point_prompt + predict_structure
importate), deci predictiile sunt consistente cu cifrele din tabele.

Doua faze:
  1) --scan : ruleaza modelul pe toate feliile, sorteaza dupa macro Dice/felie,
              afiseaza cele mai SLABE (esuari) si cele mai BUNE (reusite).
  2) --make : genereaza panouri PNG pentru indicii dati (--indices 12,45,300).

Combinare predictii (afisare): la suprapuneri, structura cu indice mai mare e
afisata deasupra (ordine 1->2->3). Conventie de AFISARE — NU afecteaza metricile
per-structura (acelea vin din eval independent).

Exemple:
  # Faza 1 — gaseste feliile interesante:
  PYTHONPATH=src python src/cli/make_figures.py \
      --config configs/eval_zero_shot.yaml \
      --checkpoint outputs/train_lora/rank16/best.pt --scan

  # Faza 2 — genereaza panouri pentru feliile alese:
  PYTHONPATH=src python src/cli/make_figures.py \
      --config configs/eval_zero_shot.yaml \
      --checkpoint outputs/train_lora/rank16/best.pt \
      --make --indices 12,45,300,510 --prefix rank16
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import yaml

from sam_lora.data import SliceDataset
from sam_lora.metrics import dice_score
from sam_lora.visualize import per_structure_panel_zoom

# Refolosim EXACT piesele de inferenta din eval (consistenta garantata cu tabelele).
from cli.train_lora import encode_image
from cli.eval_per_structure import predict_structure, build_model, STRUCTURE_NAMES


def combine_predictions(sam_model, image_embeddings, mask_np, device, structures=(1, 2, 3)):
    """Combina predictiile binare per-structura intr-o harta multi-clasa (0/1/2/3).

    Prioritate: structurile sunt scrise in ordine crescatoare, deci indicele mai
    mare castiga pixelii suprapusi (conventie de afisare). Intoarce si Dice-ul
    per structura (calculat pe predictia binara independenta, identic cu eval).
    """
    H, W = mask_np.shape
    combined = np.zeros((H, W), dtype=np.int64)
    per_struct_dice = {}
    for k in structures:
        if (mask_np == k).sum() == 0:
            continue
        pred_bin = predict_structure(sam_model, image_embeddings, mask_np, k, device)
        if pred_bin is None:
            continue
        combined[pred_bin == 1] = k  # indicele mai mare scrie peste
        per_struct_dice[k] = dice_score(pred_bin * k, mask_np, k)
    return combined, per_struct_dice


def load_slice(ds, idx):
    """Incarca o felie: intoarce (image_np HxW, mask_np HxW cu 0/1/2/3, id)."""
    sample = ds[idx]
    image_np = sample.image.numpy().squeeze(0)
    mask_np = sample.mask.numpy()
    return image_np, mask_np, sample.meta["id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--checkpoint", required=True, help="best.pt LoRA pentru figuri (ex: rank16)")
    ap.add_argument("--scan", action="store_true", help="faza 1: gaseste felii reusite/esuate")
    ap.add_argument("--make", action="store_true", help="faza 2: genereaza panouri pentru --indices")
    ap.add_argument("--indices", default="", help="indici felii (ex: '12,45,300') pentru --make")
    ap.add_argument("--prefix", default="fig", help="prefix nume fisier PNG")
    ap.add_argument("--out", default="outputs/figures", help="director iesire PNG")
    ap.add_argument("--top", type=int, default=8, help="cate felii sa afiseze la scan (sus si jos)")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    data_root = cfg["DATA"]["ROOT"]
    img_h, img_w = cfg["DATA"].get("IMG_SIZE", [256, 256])

    device = torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )

    ds = SliceDataset(root=data_root, split="test", img_size=(img_h, img_w), has_masks=True)
    sam_model, mode = build_model(cfg["MODEL"], args.checkpoint, device)
    print(f"Model: {mode} | felii: {len(ds)} | device: {device.type}")

    if args.scan:
        print("\nScanez feliile (macro Dice/felie)...")
        scores = []
        for i in range(len(ds)):
            image_np, mask_np, _ = load_slice(ds, i)
            present = [k for k in (1, 2, 3) if (mask_np == k).sum() > 0]
            if not present:
                continue
            with torch.no_grad():
                emb = encode_image(sam_model, image_np, device)
            _, dices = combine_predictions(sam_model, emb, mask_np, device)
            if dices:
                macro = float(np.mean(list(dices.values())))
                scores.append((i, macro, len(present)))

        scores.sort(key=lambda x: x[1])  # crescator dupa macro
        n = args.top
        print(f"\nFelii evaluate: {len(scores)}")
        print(f"\n--- Cele mai SLABE {n} (candidati ESUARI) ---")
        print(f"{'idx':>5} {'macro':>7} {'#struct':>8}")
        for i, m, p in scores[:n]:
            print(f"{i:>5} {m:>7.3f} {p:>8}")
        print(f"\n--- Cele mai BUNE {n} (candidati REUSITE) ---")
        print(f"{'idx':>5} {'macro':>7} {'#struct':>8}")
        for i, m, p in scores[-n:]:
            print(f"{i:>5} {m:>7.3f} {p:>8}")
        print("\nAlege indici si ruleaza din nou cu --make --indices i1,i2,...")
        return

    if args.make:
        if not args.indices:
            print("EROARE: --make cere --indices (ex: --indices 12,45,300)")
            return
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        indices = [int(x) for x in args.indices.split(",")]
        print(f"\nGenerez {len(indices)} panouri in {out_dir}/ ...")
        for idx in indices:
            image_np, mask_np, sid = load_slice(ds, idx)
            with torch.no_grad():
                emb = encode_image(sam_model, image_np, device)
            pred_combined, dices = combine_predictions(sam_model, emb, mask_np, device)
            macro = float(np.mean(list(dices.values()))) if dices else 0.0
            out_png = out_dir / f"{args.prefix}_slice{idx}.png"
            per_structure_panel_zoom(
                image=image_np,
                gt_multiclass=mask_np,
                pred_multiclass=pred_combined,
                out_png=str(out_png),
                dice_by_structure=dices,
                structure_names=STRUCTURE_NAMES,
                suptitle=f"slice {idx} (id={sid}) | macro Dice={macro:.3f}",
            )
            dice_str = "  ".join(f"{STRUCTURE_NAMES[k]}={d:.2f}" for k, d in sorted(dices.items()))
            print(f"  OK slice {idx}: {dice_str}  -> {out_png}")
        print("\nGata. PNG-urile sunt in", out_dir)
        return

    print("Specifica --scan SAU --make. Vezi --help.")


if __name__ == "__main__":
    main()