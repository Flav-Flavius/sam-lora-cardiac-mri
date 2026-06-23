"""Simple visualization utilities for qualitative QA panels."""

from __future__ import annotations

from typing import Optional

import numpy as np
import matplotlib.pyplot as plt


def side_by_side(image: np.ndarray, gt: Optional[np.ndarray], pred: Optional[np.ndarray], out_png: str) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(9, 3))
    axes[0].imshow(image, cmap="gray")
    axes[0].set_title("Image")
    if gt is not None:
        axes[1].imshow(gt, cmap="viridis", vmin=0, vmax=max(3, gt.max()))
        axes[1].set_title("GT")
    else:
        axes[1].axis("off")
    if pred is not None:
        axes[2].imshow(pred, cmap="viridis", vmin=0, vmax=max(3, pred.max()))
        axes[2].set_title("Pred")
    else:
        axes[2].axis("off")
    for ax in axes:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


