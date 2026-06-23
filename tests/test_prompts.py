import numpy as np
from sam_lora.prompts import centroid_from_mask, grid_points, tight_box_from_mask


def test_centroid_and_box():
    m = np.zeros((10, 10), dtype=np.int64)
    m[2:5, 3:7] = 1
    cx, cy = centroid_from_mask(m)
    assert 3.0 <= cx <= 6.0 and 2.0 <= cy <= 5.0
    x0, y0, x1, y1 = tight_box_from_mask(m)
    assert (x0, y0) == (3, 2)
    assert (x1, y1) == (6, 4)


def test_grid_points_shape():
    pts = grid_points(100, 50, density=5)
    assert pts.shape == (25, 2)


