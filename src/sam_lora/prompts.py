"""Prompt generators for SAM: point, box, grid, with optional jitter.

All functions operate in pixel coordinates. Coordinates are (x, y).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class PointPrompt:
    points: np.ndarray  # (N,2)
    labels: np.ndarray  # (N,), 1=fg, 0=bg


def centroid_from_mask(mask: np.ndarray) -> Tuple[float, float]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return 0.0, 0.0
    return float(xs.mean()), float(ys.mean())


def tight_box_from_mask(mask: np.ndarray) -> Tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return 0, 0, mask.shape[1] - 1, mask.shape[0] - 1
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def jitter_point(point_xy: Tuple[float, float], sigma_px: float) -> Tuple[float, float]:
    if sigma_px <= 0:
        return point_xy
    dx, dy = np.random.normal(0.0, sigma_px, size=2)
    return float(point_xy[0] + dx), float(point_xy[1] + dy)


def grid_points(width: int, height: int, density: int) -> np.ndarray:
    xs = np.linspace(0.1, 0.9, density) * (width - 1)
    ys = np.linspace(0.1, 0.9, density) * (height - 1)
    grid = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2)
    return grid.astype(np.float32)


def point_prompt_from_mask(mask: np.ndarray, jitter_sigma: float = 0.0) -> PointPrompt:
    x, y = centroid_from_mask(mask)
    x, y = jitter_point((x, y), jitter_sigma)
    pts = np.array([[x, y]], dtype=np.float32)
    lbl = np.array([1], dtype=np.int64)
    return PointPrompt(points=pts, labels=lbl)


def box_prompt_from_mask(mask: np.ndarray, scale: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = tight_box_from_mask(mask)
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    w = (x1 - x0 + 1) * scale
    h = (y1 - y0 + 1) * scale
    x0_s = cx - w / 2.0
    y0_s = cy - h / 2.0
    x1_s = cx + w / 2.0
    y1_s = cy + h / 2.0
    box = np.array([[x0_s, y0_s, x1_s, y1_s]], dtype=np.float32)
    box_labels = np.array([2], dtype=np.int64)  # special box label in SAM API
    return box, box_labels


def grid_prompt_for_image(width: int, height: int, density: int) -> PointPrompt:
    pts = grid_points(width, height, density)
    lbl = np.ones((pts.shape[0],), dtype=np.int64)
    return PointPrompt(points=pts, labels=lbl)


