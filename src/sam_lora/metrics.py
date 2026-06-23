"""Segmentation metrics: Dice, HD95 (approx), Boundary F, LV mass error.

Minimal, CPU-friendly implementations for quick evaluation on 2D slices.
For exact HD95 in mm, provide pixel spacing if available.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from scipy.ndimage import distance_transform_edt as edt


def dice_score(pred: np.ndarray, gt: np.ndarray, label: int) -> float:
    pred_i = (pred == label)
    gt_i = (gt == label)
    inter = float((pred_i & gt_i).sum())
    denom = float(pred_i.sum() + gt_i.sum())
    return 2.0 * inter / denom if denom > 0 else 1.0 if gt_i.sum() == 0 and pred_i.sum() == 0 else 0.0


def surface_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # extract boundaries
    from skimage.segmentation import find_boundaries

    ba = find_boundaries(a, mode="outer")
    bb = find_boundaries(b, mode="outer")
    da = edt(~ba)
    db = edt(~bb)
    d_ab = db[ba]
    d_ba = da[bb]
    return np.concatenate([d_ab, d_ba]) if d_ab.size and d_ba.size else np.array([0.0])


def hd95(pred: np.ndarray, gt: np.ndarray, label: int, pixel_spacing_mm: float | None = None) -> float:
    pa = (pred == label)
    ga = (gt == label)
    d = surface_distances(pa, ga)
    hd = float(np.percentile(d, 95))
    if pixel_spacing_mm is not None:
        hd *= float(pixel_spacing_mm)
    return hd


def boundary_f_score(pred: np.ndarray, gt: np.ndarray, tolerance_px: int = 2) -> float:
    from skimage.morphology import dilation, disk
    from skimage.segmentation import find_boundaries

    pb = find_boundaries(pred, mode="outer")
    gb = find_boundaries(gt, mode="outer")
    se = disk(max(1, int(tolerance_px)))
    gb_d = dilation(gb, footprint=se)
    pb_d = dilation(pb, footprint=se)
    tp = (pb & gb_d).sum() + (gb & pb_d).sum()
    fp = pb.sum() + gb.sum() - tp
    fn = 0  # included in fp for symmetric definition here
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0


def lv_mass_error(pred: np.ndarray, gt: np.ndarray, myo_label: int, voxel_volume_ml: float = 1.0, density_g_ml: float = 1.05) -> float:
    myo_pred = (pred == myo_label).sum()
    myo_gt = (gt == myo_label).sum()
    mass_pred_g = myo_pred * voxel_volume_ml * density_g_ml
    mass_gt_g = myo_gt * voxel_volume_ml * density_g_ml
    return float(mass_pred_g - mass_gt_g)


