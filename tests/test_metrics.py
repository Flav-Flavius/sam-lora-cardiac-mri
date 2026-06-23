import numpy as np
from sam_lora.metrics import dice_score


def test_dice_perfect_and_empty():
    gt = np.zeros((8, 8), dtype=np.int64)
    pred = np.zeros_like(gt)
    assert dice_score(pred, gt, 1) == 1.0  # both empty

    gt[2:4, 2:4] = 1
    pred[2:4, 2:4] = 1
    assert dice_score(pred, gt, 1) == 1.0

    pred[:, :] = 0
    assert dice_score(pred, gt, 1) == 0.0


