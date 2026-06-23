"""Thin wrapper to load SAM and run mask predictions from prompts.

This wrapper intentionally avoids deep internals and uses the official API
where possible. It prepares inputs and returns binary masks per class.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import torch


def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SamPredictorWrapper:
    def __init__(self, variant: str = "vit_b", checkpoint: str | None = None) -> None:
        from segment_anything import SamPredictor, sam_model_registry

        self.device = get_device()
        model_type = {
            "vit_b": "vit_b",
            "vit_l": "vit_l",
            "vit_h": "vit_h",
        }.get(variant, "vit_b")
        if checkpoint is None:
            raise ValueError(
        "SAM checkpoint path is required but was not provided. "
        "Set CHECKPOINT in your config YAML or pass it explicitly."
    )
        sam = sam_model_registry[model_type](checkpoint=checkpoint)
        sam.to(self.device)
        self.predictor = SamPredictor(sam)

    def set_image(self, image_np: np.ndarray) -> None:
        # expects (H,W) float32 image in [0,1] or z-scored
        if image_np.ndim == 2:
            image_rgb = np.stack([image_np] * 3, axis=-1)
        else:
            image_rgb = image_np
        image_rgb = (image_rgb - image_rgb.min()) / max(1e-6, (image_rgb.max() - image_rgb.min()))
        image_rgb = (image_rgb * 255.0).astype(np.uint8)
        self.predictor.set_image(image_rgb)

    def predict_with_point(self, points: np.ndarray, labels: np.ndarray) -> np.ndarray:
        masks, _, _ = self.predictor.predict(point_coords=points, point_labels=labels, multimask_output=False)
        return masks[0]

    def predict_with_box(self, boxes: np.ndarray) -> np.ndarray:
        masks, _, _ = self.predictor.predict(box=boxes, multimask_output=False)
        return masks[0]


