"""Plan-view polylines: arcs, offsets, clipping and lookups. Pure Python and numpy, no bpy.

A polyline is an (N, 2) float array of (x, y) points in model millimetres.
Every rail line in a turnout runs toward +X (its heading stays between -90
and +90 degrees), so a line can be looked up by X: ``y_at`` and
``heading_at`` interpolate along X, and ``clip_x`` cuts a line to an X range.
"""

from __future__ import annotations

import math

import numpy as np


def as_poly(points) -> np.ndarray:
    """``points`` as an (N, 2) float array with consecutive duplicates removed."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(p) < 2:
        return p
    keep = np.ones(len(p), dtype=bool)
    keep[1:] = np.hypot(*(p[1:] - p[:-1]).T) > 1e-9
    return p[keep]


def straight(p0, heading: float, length: float) -> np.ndarray:
    """A two-point line from ``p0`` along ``heading`` (radians) for ``length`` mm."""
    x, y = p0
    return as_poly([(x, y), (x + length * math.cos(heading), y + length * math.sin(heading))])


def arc(p0, h0: float, h1: float, radius: float, step: float = 0.5) -> np.ndarray:
    """A left-turning arc from ``p0`` heading ``h0`` to heading ``h1`` (radians, h1 > h0).

    ``radius`` is the arc's radius; points are about ``step`` mm apart.
    """
    if h1 <= h0 or radius <= 0:
        return as_poly([p0])
    n = max(2, int(math.ceil(radius * (h1 - h0) / max(step, 1e-6))) + 1)
    h = np.linspace(h0, h1, n)
    cx, cy = p0[0] - radius * math.sin(h0), p0[1] + radius * math.cos(h0)
    return np.column_stack([cx + radius * np.sin(h), cy - radius * np.cos(h)])


def join(*parts) -> np.ndarray:
    """Several polylines end to end as one (shared end points kept once)."""
    pts = [np.asarray(p, dtype=np.float64).reshape(-1, 2) for p in parts if len(p)]
    return as_poly(np.vstack(pts)) if pts else np.zeros((0, 2))


def headings(poly: np.ndarray) -> np.ndarray:
    """Heading (radians) at every point: the bisector of the segments meeting there."""
    d = np.diff(poly, axis=0)
    seg = np.arctan2(d[:, 1], d[:, 0])
    h = np.empty(len(poly))
    h[0], h[-1] = seg[0], seg[-1]
    if len(poly) > 2:
        a, b = seg[:-1], seg[1:]
        h[1:-1] = a + np.angle(np.exp(1j * (b - a))) / 2
    return h


def offset(poly: np.ndarray, d: float) -> np.ndarray:
    """``poly`` moved ``d`` mm to its left (negative = right), keeping a constant distance.

    Corners are mitred, so straight runs stay exactly ``d`` away.
    """
    if len(poly) < 2 or d == 0:
        return poly.copy()
    h = headings(poly)
    seg = np.arctan2(*np.diff(poly, axis=0).T[::-1])
    half = np.zeros(len(poly))
    if len(poly) > 2:
        half[1:-1] = np.angle(np.exp(1j * (seg[1:] - seg[:-1]))) / 2
    m = d / np.maximum(np.cos(half), 0.2)
    return poly + np.column_stack([-np.sin(h) * m, np.cos(h) * m])


def lengths(poly: np.ndarray) -> np.ndarray:
    """Distance along the polyline at every point, starting at 0."""
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(poly, axis=0).T))])


def at_length(poly: np.ndarray, s: float) -> tuple[np.ndarray, float]:
    """(point, heading) at distance ``s`` along the polyline (clamped to its ends)."""
    L = lengths(poly)
    s = min(max(s, 0.0), L[-1])
    i = int(np.clip(np.searchsorted(L, s, side="right") - 1, 0, len(poly) - 2))
    a, b = poly[i], poly[i + 1]
    f = 0.0 if L[i + 1] - L[i] <= 0 else (s - L[i]) / (L[i + 1] - L[i])
    d = b - a
    return a + f * d, math.atan2(d[1], d[0])


def length_at_x(poly: np.ndarray, x: float) -> float:
    """Distance along the polyline to where it reaches ``x``."""
    return float(np.interp(x, poly[:, 0], lengths(poly)))


def x_range(poly: np.ndarray) -> tuple[float, float]:
    """(first x, last x) of a line that runs toward +X."""
    return float(poly[0, 0]), float(poly[-1, 0])


def covers(poly: np.ndarray, x: float, tol: float = 1e-9) -> bool:
    """True when the line exists at ``x``."""
    return len(poly) >= 2 and poly[0, 0] - tol <= x <= poly[-1, 0] + tol


def y_at(poly: np.ndarray, x: float) -> float:
    """The line's y at ``x`` (NaN where the line doesn't reach)."""
    if not covers(poly, x):
        return math.nan
    return float(np.interp(x, poly[:, 0], poly[:, 1]))


def heading_at(poly: np.ndarray, x: float) -> float:
    """The line's heading (radians) at ``x``, from the segment there."""
    i = int(np.clip(np.searchsorted(poly[:, 0], x, side="right") - 1, 0, len(poly) - 2))
    d = poly[i + 1] - poly[i]
    return math.atan2(d[1], d[0])


def clip_x(poly: np.ndarray, x0: float, x1: float) -> np.ndarray:
    """The part of the line between ``x0`` and ``x1`` (an empty array if none)."""
    if len(poly) < 2:
        return np.zeros((0, 2))
    a, b = max(x0, poly[0, 0]), min(x1, poly[-1, 0])
    if b - a <= 1e-9:
        return np.zeros((0, 2))
    inner = poly[(poly[:, 0] > a + 1e-9) & (poly[:, 0] < b - 1e-9)]
    ends = [(a, np.interp(a, poly[:, 0], poly[:, 1])), (b, np.interp(b, poly[:, 0], poly[:, 1]))]
    return as_poly(np.vstack([ends[0], inner, ends[1]]))


def y_span(poly: np.ndarray, x0: float, x1: float) -> tuple[float, float] | None:
    """Lowest and highest y of the line between ``x0`` and ``x1``, or None if it isn't there."""
    part = clip_x(poly, x0, x1)
    if len(part) < 2:
        return None
    return float(part[:, 1].min()), float(part[:, 1].max())


def mirror(poly: np.ndarray) -> np.ndarray:
    """The polyline mirrored across the X axis (y -> -y)."""
    out = np.array(poly, dtype=np.float64, copy=True)
    out[:, 1] *= -1
    return out
