"""Data utilities for ACDC-like 2D slice datasets.

The expected processed layout under DATA.ROOT:

ROOT/
  images/  # .png or .npy (H,W) grayscale
  masks/   # .png or .npy with label ids {0:bg,1:LVC,2:MYO,3:RVC}
  splits.json  # {"train": [...], "val": [...], "test": [...]} basenames

This is a minimal implementation to enable immediate runs; extend as needed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset


def _load_image(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        arr = np.load(path)
        return arr.astype(np.float32)
    img = Image.open(path).convert("L")
    return np.array(img, dtype=np.float32)


def _load_mask(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        arr = np.load(path)
        return arr.astype(np.int64)
    img = Image.open(path)
    return np.array(img, dtype=np.int64)


@dataclass
class Sample:
    image: torch.Tensor  # (1,H,W)
    mask: Optional[torch.Tensor]  # (H,W) int64 or None
    meta: Dict


class SliceDataset(Dataset):
    """Simple dataset over preprocessed slices with optional masks."""

    def __init__(
        self,
        root: str,
        split: str,
        img_size: Tuple[int, int],
        has_masks: bool = True,
    ) -> None:
        super().__init__()
        self.root = root
        self.split = split
        self.img_size = tuple(img_size)
        self.has_masks = has_masks

        with open(os.path.join(root, "splits.json"), "r") as f:
            splits = json.load(f)
        self.ids: List[str] = list(splits[split])

        self.images_dir = os.path.join(root, "images")
        self.masks_dir = os.path.join(root, "masks")

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int) -> Sample:
        base = self.ids[idx]
        img_path_png = os.path.join(self.images_dir, f"{base}.png")
        img_path_npy = os.path.join(self.images_dir, f"{base}.npy")
        img_path = img_path_png if os.path.exists(img_path_png) else img_path_npy
        image = _load_image(img_path)

        if self.has_masks:
            m_path_png = os.path.join(self.masks_dir, f"{base}.png")
            m_path_npy = os.path.join(self.masks_dir, f"{base}.npy")
            m_path = m_path_png if os.path.exists(m_path_png) else m_path_npy
            mask = _load_mask(m_path)
        else:
            mask = None

    # resize la dimensiunea fixă
        img_pil = Image.fromarray(image.astype(np.uint8))
        img_pil = img_pil.resize((self.img_size[1], self.img_size[0]), Image.BILINEAR)
        image = np.array(img_pil, dtype=np.float32)

        if mask is not None:
            msk_pil = Image.fromarray(mask.astype(np.uint8))
            msk_pil = msk_pil.resize((self.img_size[1], self.img_size[0]), Image.NEAREST)
            mask = np.array(msk_pil, dtype=np.int64)

    # to tensors
        image_t = torch.from_numpy(image)[None, ...]  # (1,H,W)
        mask_t = torch.from_numpy(mask) if mask is not None else None

        return Sample(image=image_t, mask=mask_t, meta={"id": base})


