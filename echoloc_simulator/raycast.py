"""Exact grid ray cast, signature-compatible with F3Loc's `utils.utils.ray_cast`.

Why not the original: F3Loc's DDA tests `occ[int(row), int(col)]` at every
boundary event. On steps that move left or down the landing coordinate is an
integer boundary, so `int()` names the pixel the ray is LEAVING, not entering.
A ray that clips the corner pixel of a wall block (enters through its right edge,
exits through its top) therefore never tests that pixel and passes through the
wall. On the staircase edge of a rotated wall a grazing ray does this at every
block and escapes to the map border: 0.27% of depth160 rays in frl_apartment_0
reported dist_max (20 m) through a wall 3 m away. desdf inherits the same leaks.

This is an Amanatides-Woo traversal: every pixel the ray passes through is
tested, in order, and the distance reported is the entry point of the first
non-free pixel (F3Loc reports the same event position on up/right steps and one
pixel late on left/down steps, so the two agree to <= 1 px wherever F3Loc does not
leak — see selftest()). Free space is exactly 255, everything else blocks, rays
leaving the map return dist_max, all as in the original.
"""
import numpy as np


def ray_cast(occ, pos, ang, dist_max=500):
    """pos = [row, col] in pixels (float), ang in radians (row = sin, col = cos).
    Returns the distance in pixels to the first non-255 pixel, or dist_max."""
    h, w = occ.shape
    r, c = float(pos[0]), float(pos[1])
    s, k = float(np.sin(ang)), float(np.cos(ang))
    ir, ic = int(np.floor(r)), int(np.floor(c))
    if not (0 <= ir < h and 0 <= ic < w):
        return dist_max
    if occ[ir, ic] != 255:
        return 0.0
    inf = float("inf")
    if s > 0:
        step_r, t_r, d_r = 1, (ir + 1 - r) / s, 1.0 / s
    elif s < 0:
        step_r, t_r, d_r = -1, (r - ir) / -s, 1.0 / -s
    else:
        step_r, t_r, d_r = 0, inf, inf
    if k > 0:
        step_c, t_c, d_c = 1, (ic + 1 - c) / k, 1.0 / k
    elif k < 0:
        step_c, t_c, d_c = -1, (c - ic) / -k, 1.0 / -k
    else:
        step_c, t_c, d_c = 0, inf, inf
    while True:
        if t_r < t_c:
            t = t_r
            ir += step_r
            t_r += d_r
        else:
            t = t_c
            ic += step_c
            t_c += d_c
        if t >= dist_max:
            return dist_max
        if not (0 <= ir < h and 0 <= ic < w):
            return dist_max
        if occ[ir, ic] != 255:
            return t


def march(occ, pos, ang, dist_max, step=0.05):
    """Brute-force sampling reference (independent of both DDAs)."""
    h, w = occ.shape
    r0, c0 = pos
    s, k = np.sin(ang), np.cos(ang)
    t = 0.0
    while t < dist_max:
        t += step
        r, c = r0 + t * s, c0 + t * k
        if r < 0 or c < 0 or r >= h or c >= w:
            return dist_max
        if occ[int(r), int(c)] != 255:
            return t
    return dist_max


def selftest(occ, n=3000, seed=0):
    """Compare with F3Loc's ray_cast and with the sampling march on random rays."""
    import common as C
    C.f3loc_import()
    from utils.utils import ray_cast as f3
    rng = np.random.RandomState(seed)
    free = np.argwhere(occ == 255)
    d_f3, d_m = [], []
    for _ in range(n):
        r, c = free[rng.randint(len(free))] + rng.rand(2)
        a = rng.uniform(-np.pi, np.pi)
        pos = np.array([r, c])
        ours = ray_cast(occ, pos, a, 2000)
        d_f3.append(f3(occ, pos.copy(), a, 2000) - ours)
        d_m.append(march(occ, pos, a, 2000) - ours)
    d_f3, d_m = np.array(d_f3), np.array(d_m)
    leaks = (d_f3 > 2).sum()
    print(f"ours vs F3Loc: {n} rays, |diff|<=1px on {(np.abs(d_f3) <= 1.0).mean():.4%}, "
          f"F3Loc leaks (>2px longer) {leaks} ({leaks / n:.3%}), F3Loc shorter than ours: {(d_f3 < -1e-9).sum()}")
    print(f"ours vs march : max |diff| {np.abs(d_m).max():.3f} px  (march overshoots by <= 0.05 px; "
          f"march shorter than ours: {(d_m < -1e-9).sum()})")
    return d_f3, d_m


if __name__ == "__main__":
    import sys
    import common as C
    selftest(C.load_map(sys.argv[1] if len(sys.argv) > 1 else "frl_apartment_0"))
