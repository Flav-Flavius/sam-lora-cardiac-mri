"""Convert ACDC DICOM/NIfTI to a simple 2D slice dataset.

Reads YAML config and converts images/masks into PNG/NPY under data/interim.
Idempotent: skips files that already exist.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import yaml
from PIL import Image
import nibabel as nib


def save_png_float(image: np.ndarray, path: str) -> None:
    img = image
    img = (img - img.min()) / max(1e-6, img.max() - img.min())
    Image.fromarray((img * 255).astype(np.uint8)).save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--acdc-root", required=False)
    ap.add_argument("--out-root", required=False)
    ap.add_argument("--max-slices", type=int, default=None, help="Optional limit on number of slices to export (for quick demos)")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    data_cfg = cfg.get("DATA", {})
    raw_root = args.acdc_root or data_cfg.get("RAW_ROOT", "data/raw/ACDC")
    out_root = args.out_root or data_cfg.get("ROOT", "data/interim/ACDC")
    img_size = tuple(data_cfg.get("IMG_SIZE", [256, 256]))

    os.makedirs(os.path.join(out_root, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "masks"), exist_ok=True)

    ids: List[str] = []

    # First, try ACDC official NIfTI structure
    db_dir = Path(raw_root) / "database"
    total_exported = 0
    if db_dir.exists():
        for split_name in ["training", "testing"]:
            split_dir = db_dir / split_name
            if not split_dir.exists():
                continue
            for patient_dir in sorted(split_dir.glob("patient*/")):
                # find frame files and corresponding GT
                frame_files = sorted(patient_dir.glob("*frame*.nii.gz"))
                for fp in frame_files:
                    if "_gt" in fp.name:
                        continue
                    gt_path = patient_dir / fp.name.replace(".nii.gz", "_gt.nii.gz")
                    if not gt_path.exists():
                        continue
                    img_nii = nib.load(str(fp))
                    msk_nii = nib.load(str(gt_path))
                    img_arr = np.asarray(img_nii.get_fdata(), dtype=np.float32)
                    msk_arr = np.asarray(msk_nii.get_fdata(), dtype=np.int64)
                    # ensure shapes compatible: (H,W[,Z])
                    if img_arr.ndim == 2:
                        img_arr = img_arr[:, :, None]
                    if msk_arr.ndim == 2:
                        msk_arr = msk_arr[:, :, None]
                    z_slices = img_arr.shape[2]
                    for z in range(z_slices):
                        img2d = img_arr[:, :, z]
                        msk2d = msk_arr[:, :, z]
                        if int(msk2d.max()) == 0:
                            continue  # skip empty slices
                        base = f"{patient_dir.name}_{fp.stem}_z{z:02d}".replace(".nii", "")
                        out_img = Path(out_root) / "images" / f"{base}.png"
                        out_msk = Path(out_root) / "masks" / f"{base}.png"
                        if not out_img.exists():
                            save_png_float(img2d, str(out_img))
                        if not out_msk.exists():
                            Image.fromarray(msk2d.astype(np.uint8)).save(str(out_msk))
                        ids.append(base)
                        total_exported += 1
                        if args.max_slices is not None and total_exported >= args.max_slices:
                            break
                    if args.max_slices is not None and total_exported >= args.max_slices:
                        break
                if args.max_slices is not None and total_exported >= args.max_slices:
                    break
        # Create splits: use training->train/val, testing->test
        train_ids = [i for i in ids if "/training/" in i or "training_" in i or "patient" in i]  # heuristic
        # For reliability, just split 90/10 for val
        n_train = int(len(ids) * 0.7)
        n_val = int(len(ids) * 0.1)
        splits = {
            "train": ids[:n_train],
            "val": ids[n_train : n_train + n_val],
            "test": ids[n_train + n_val :],
        }
        with open(Path(out_root) / "splits.json", "w") as f:
            json.dump(splits, f)
        print(f"Prepared {total_exported} slices from NIfTI under {out_root}")
        return

    # Fallback: pre-extracted NPY pairs under RAW_ROOT/{images,masks}
    raw_images = sorted((Path(raw_root) / "images").glob("*.npy"))
    if not raw_images:
        print("No NIfTI under RAW_ROOT/database and no NPY under RAW_ROOT/images; nothing to convert.")
        return
    for ip in raw_images:
        base = ip.stem
        mp = Path(raw_root) / "masks" / f"{base}.npy"
        if not mp.exists():
            continue
        img = np.load(str(ip)).astype(np.float32)
        msk = np.load(str(mp)).astype(np.int64)
        out_img = Path(out_root) / "images" / f"{base}.png"
        out_msk = Path(out_root) / "masks" / f"{base}.png"
        if not out_img.exists():
            save_png_float(img, str(out_img))
        if not out_msk.exists():
            Image.fromarray(msk.astype(np.uint8)).save(str(out_msk))
        ids.append(base)

    # naive split for NPY fallback
    n = len(ids)
    n_val = max(1, int(0.1 * n))
    n_test = max(1, int(0.2 * n))
    splits = {"train": ids[: n - n_val - n_test], "val": ids[n - n_val - n_test : n - n_test], "test": ids[n - n_test : n]}
    with open(Path(out_root) / "splits.json", "w") as f:
        json.dump(splits, f)
    print(f"Prepared {n} slices under {out_root}")


if __name__ == "__main__":
    main()


