"""Preprocessing utilities: normalization, resizing, label remapping.

This module provides minimal functions used by the CLI and datasets. For
complete medical preprocessing (resampling by spacing), consider SimpleITK.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import cv2


def zscore_normalize(image: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    mean = float(np.mean(image))
    std = float(np.std(image))
    return (image - mean) / max(std, eps)


def percentile_normalize(image: np.ndarray, pmin: float = 1.0, pmax: float = 99.0) -> np.ndarray:
    lo = np.percentile(image, pmin)
    hi = np.percentile(image, pmax)
    if hi <= lo:
        return np.zeros_like(image, dtype=np.float32)
    image = (image - lo) / (hi - lo)
    return np.clip(image, 0.0, 1.0).astype(np.float32)


def remap_labels(mask: np.ndarray, id_map: Dict[str, int]) -> np.ndarray:
    # expects mask already in {0..}
    return mask.astype(np.int64)


def resize_image_mask(image: np.ndarray, mask: np.ndarray | None, size: Tuple[int, int]) -> tuple[np.ndarray, np.ndarray | None]:
    h, w = size
    img_r = cv2.resize(image, (w, h), interpolation=cv2.INTER_LINEAR)
    if mask is None:
        return img_r, None
    m_r = cv2.resize(mask.astype(np.int32), (w, h), interpolation=cv2.INTER_NEAREST)
    return img_r, m_r.astype(np.int64)


