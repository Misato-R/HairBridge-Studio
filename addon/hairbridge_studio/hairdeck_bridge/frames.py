"""Frame transport from HairDeck hairdeck/cards/frames.py (Apache-2.0).
Subset for the Blender importer; see HAIRDECK-LICENSE.txt.
"""
import numpy as np

_STENCIL = np.array([-1 / 12, 2 / 3, 0, -2 / 3, 1 / 12])


def tangents(p):
    n = len(p)
    if n < 5:
        t = p[-1] - p[0]
        return np.repeat((t / (np.linalg.norm(t) + 1e-12))[None], n, 0)
    out = np.zeros_like(p)
    for i in range(n):
        lo = min(max(i - 2, 0), n - 5)
        t = (_STENCIL[:, None] * p[lo:lo + 5]).sum(0)
        out[i] = t / (np.linalg.norm(t) + 1e-12)
    return out


def perp(v, t):
    v = v - np.dot(v, t) * t
    return v / (np.linalg.norm(v) + 1e-12)


def bishop(n0, T):
    out = [perp(n0, T[0])]
    for i in range(1, len(T)):
        a, b = T[i - 1], T[i]
        ax = np.cross(a, b)
        s, c = np.linalg.norm(ax), np.clip(np.dot(a, b), -1, 1)
        n = out[-1]
        if s > 1e-9:
            k = ax / s
            n = n * c + np.cross(k, n) * s + k * np.dot(k, n) * (1 - c)
        out.append(perp(n, b))
    return np.array(out)
