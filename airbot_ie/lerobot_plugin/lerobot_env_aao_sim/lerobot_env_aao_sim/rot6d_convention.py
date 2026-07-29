"""rot6d_convention.py — swap between sim and real 6D rotation conventions.

Sim  (row-major): [r00, r01, r02, r10, r11, r12]  ← first 2 rows of R
Real (col-major): [r00, r10, r20, r01, r11, r21]  ← first 2 cols of R

The conversion is a **self-inverse** permutation: applying it twice returns
the original array.  sim→real and real→sim are therefore the same function.

Why cross product?  The 3rd row/col is not stored, but for any proper rotation
(det = +1) it equals cross(first_vector, second_vector), so it is always
recoverable without any trigonometry.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def swap_rot6d_convention(rot6d: ArrayLike) -> np.ndarray:
    """Swap between sim (row-major) and real (col-major) rot6d conventions.

    This function is its own inverse: ``swap(swap(x)) == x`` for any valid
    rotation.  Pass it either convention; it always returns the other one.

    Parameters
    ----------
    rot6d : array_like, shape (..., 6)
        Six floats encoding a rotation in either convention.

    Returns
    -------
    np.ndarray, shape (..., 6), float32
        The same rotation in the opposite convention.
    """
    v = np.asarray(rot6d, dtype=np.float64)
    a, b = v[..., :3], v[..., 3:]
    c = np.cross(a, b)  # third vector recovered via cross product
    return np.stack(
        [v[..., 0], v[..., 3], c[..., 0],
         v[..., 1], v[..., 4], c[..., 1]],
        axis=-1,
    ).astype(np.float32)


# Named aliases — same function, different names for readable call sites.
sim_rot6d_to_real = swap_rot6d_convention
real_rot6d_to_sim = swap_rot6d_convention
