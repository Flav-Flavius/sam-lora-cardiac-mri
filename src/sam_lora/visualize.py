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


def per_structure_panel(
    image: np.ndarray,
    gt_multiclass: np.ndarray,
    pred_multiclass: np.ndarray,
    out_png: str,
    dice_by_structure: Optional[dict] = None,
    structure_names: Optional[dict] = None,
    suptitle: str = "",
) -> None:
    """Panou calitativ Image | GT | Pred pentru segmentare per-structura.

    Scala FIXA (vmin=0, vmax=3) in ambele panouri -> aceeasi structura are
    aceeasi culoare in GT si Pred. Fara crop (cadrul intreg).
    """
    names = structure_names or {1: "LVC", 2: "MYO", 3: "RVC"}

    fig, axes = plt.subplots(1, 3, figsize=(11, 4))
    axes[0].imshow(image, cmap="gray")
    axes[0].set_title("Image")
    axes[1].imshow(gt_multiclass, cmap="viridis", vmin=0, vmax=3)
    axes[1].set_title("Ground Truth")
    axes[2].imshow(pred_multiclass, cmap="viridis", vmin=0, vmax=3)
    if dice_by_structure:
        dice_str = "  ".join(
            f"{names.get(k, k)}={d:.2f}" for k, d in sorted(dice_by_structure.items())
        )
        axes[2].set_title(f"Pred  ({dice_str})")
    else:
        axes[2].set_title("Pred")
    for ax in axes:
        ax.axis("off")
    if suptitle:
        fig.suptitle(suptitle, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _crop_bbox(gt_multiclass, pred_multiclass, margin=20, min_size=60):
    """Crop centrat pe structuri (reuniune GT+Pred), cu margine + dimensiune minima.

    min_size evita crop-uri minuscule cand structura e foarte mica (ex. apex).
    Returneaza (r0, r1, c0, c1).
    """
    H, W = gt_multiclass.shape
    fg = (gt_multiclass > 0) | (pred_multiclass > 0)
    if fg.sum() == 0:
        return 0, H, 0, W
    rows = np.any(fg, axis=1)
    cols = np.any(fg, axis=0)
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    r0, r1 = r0 - margin, r1 + margin
    c0, c1 = c0 - margin, c1 + margin
    if (r1 - r0) < min_size:
        cr = (r0 + r1) // 2
        r0, r1 = cr - min_size // 2, cr + min_size // 2
    if (c1 - c0) < min_size:
        cc = (c0 + c1) // 2
        c0, c1 = cc - min_size // 2, cc + min_size // 2
    r0, r1 = max(0, r0), min(H, r1)
    c0, c1 = max(0, c0), min(W, c1)
    return int(r0), int(r1), int(c0), int(c1)


def per_structure_panel_zoom(
    image: np.ndarray,
    gt_multiclass: np.ndarray,
    pred_multiclass: np.ndarray,
    out_png: str,
    dice_by_structure: Optional[dict] = None,
    structure_names: Optional[dict] = None,
    suptitle: str = "",
    margin: int = 20,
    show_legend: bool = True,
) -> None:
    """Ca per_structure_panel, dar cu CROP pe regiunea cardiaca + LEGENDA culori.

    Crop-ul (acelasi pentru toate 3 panourile) e calculat din reuniunea
    structurilor GT+Pred -> inima ocupa cea mai mare parte a cadrului.
    Legenda mapeaza culoarea -> structura (LVC/MYO/RVC).
    """
    from matplotlib.patches import Patch
    # (folosim plt.get_cmap, compatibil cu toate versiunile matplotlib)

    names = structure_names or {1: "LVC", 2: "MYO", 3: "RVC"}

    r0, r1, c0, c1 = _crop_bbox(gt_multiclass, pred_multiclass, margin=margin)
    img_c = image[r0:r1, c0:c1]
    gt_c = gt_multiclass[r0:r1, c0:c1]
    pred_c = pred_multiclass[r0:r1, c0:c1]

    fig, axes = plt.subplots(1, 3, figsize=(11, 4))
    axes[0].imshow(img_c, cmap="gray")
    axes[0].set_title("Image")
    axes[1].imshow(gt_c, cmap="viridis", vmin=0, vmax=3)
    axes[1].set_title("Ground Truth")
    axes[2].imshow(pred_c, cmap="viridis", vmin=0, vmax=3)
    if dice_by_structure:
        dice_str = "  ".join(
            f"{names.get(k, k)}={d:.2f}" for k, d in sorted(dice_by_structure.items())
        )
        axes[2].set_title(f"Pred  ({dice_str})")
    else:
        axes[2].set_title("Pred")

    for ax in axes:
        ax.axis("off")

    if show_legend:
        cmap = plt.get_cmap("viridis")
        handles = [
            Patch(facecolor=cmap(k / 3.0), label=names.get(k, str(k)))
            for k in sorted(names.keys())
        ]
        fig.legend(handles=handles, loc="lower center", ncol=len(handles),
                   frameon=False, bbox_to_anchor=(0.5, -0.02))

    if suptitle:
        fig.suptitle(suptitle, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)