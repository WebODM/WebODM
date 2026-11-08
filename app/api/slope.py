import numpy as np


def compute_slope(elevation, valid, dx, dy):
    z = np.pad(np.where(valid, elevation, np.nan).astype(np.float32), 1, constant_values=np.nan)
    e = z[1:-1, 1:-1]

    # Missing neighbors take the center value
    a, b, c, d, f, g, h, i = (np.where(np.isnan(n), e, n) for n in (
        z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:],
        z[1:-1, :-2], z[1:-1, 2:],
        z[2:, :-2], z[2:, 1:-1], z[2:, 2:]))

    dzdx = (c + 2 * f + i - a - 2 * d - g) / (8 * abs(dx))
    dzdy = (g + 2 * h + i - a - 2 * b - c) / (8 * abs(dy))

    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    slope[~valid] = 0
    return slope
