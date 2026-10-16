"""Simple closed meshes as numpy arrays, and board placement. No bpy.

Every function returns (vertices (N, 3) float64, triangles (M, 3) int32),
triangles wound outward, every shape watertight. Boxes, hole cutters,
``combine``, ``place_board`` and ``open_edges`` are as in Tie Strip;
``prisms`` and ``spikes`` take the turned shapes a turnout needs.
"""

from __future__ import annotations

import math

import numpy as np

from .layout import Box, Hole, Prism, Spike

_BOX_TRIS = np.array([
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
    (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
], dtype=np.int32)


def empty() -> tuple[np.ndarray, np.ndarray]:
    """A mesh with no vertices or triangles."""
    return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)


def boxes(items: list[Box]) -> tuple[np.ndarray, np.ndarray]:
    """All boxes as one mesh of separate closed shells."""
    if not items:
        return empty()
    b = np.array([(i.x0, i.x1, i.y0, i.y1, i.z0, i.z1) for i in items], dtype=np.float64)
    x0, x1, y0, y1, z0, z1 = b.T
    corners = np.stack([
        np.stack([x0, y0, z0], 1), np.stack([x1, y0, z0], 1),
        np.stack([x1, y1, z0], 1), np.stack([x0, y1, z0], 1),
        np.stack([x0, y0, z1], 1), np.stack([x1, y0, z1], 1),
        np.stack([x1, y1, z1], 1), np.stack([x0, y1, z1], 1),
    ], axis=1)
    tris = (_BOX_TRIS[None, :, :] + 8 * np.arange(len(items))[:, None, None]).reshape(-1, 3)
    return corners.reshape(-1, 3), tris.astype(np.int32)


def _area(pts) -> float:
    """Signed area of a 2D polygon (positive = counter-clockwise)."""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def triangulate(pts) -> list[tuple[int, int, int]]:
    """Counter-clockwise triangles filling a simple 2D polygon, by ear clipping."""
    idx = list(range(len(pts)))
    if _area(list(pts)) < 0:
        idx.reverse()

    def cross(o, a, b):
        """Z of (a - o) x (b - o)."""
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    tris = []
    while len(idx) > 3:
        for i in range(len(idx)):
            a, b, c = idx[i - 1], idx[i], idx[(i + 1) % len(idx)]
            pa, pb, pc = pts[a], pts[b], pts[c]
            if cross(pa, pb, pc) <= 1e-12:
                continue
            if any(cross(pa, pb, pts[o]) >= -1e-12 and cross(pb, pc, pts[o]) >= -1e-12
                   and cross(pc, pa, pts[o]) >= -1e-12 for o in idx if o not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(i)
            break
        else:  # degenerate: fan the rest
            tris += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
            return tris
    tris.append(tuple(idx))
    return tris


def _extrude(outline, z0: float, z1: float) -> tuple[np.ndarray, np.ndarray]:
    """One closed prism from a plan outline (any winding)."""
    pts = [tuple(p) for p in outline]
    if _area(pts) < 0:
        pts.reverse()
    n = len(pts)
    v = np.array([(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts], dtype=np.float64)
    cap = triangulate(pts)
    t = [(c, b, a) for a, b, c in cap] + [(n + a, n + b, n + c) for a, b, c in cap]
    for i in range(n):
        j = (i + 1) % n
        t += [(i, j, n + j), (i, n + j, n + i)]
    return v, np.array(t, dtype=np.int32)


def prisms(items: list[Prism]) -> tuple[np.ndarray, np.ndarray]:
    """Vertical prisms (connectors, shoulders) as one mesh of separate closed shells."""
    return combine(*[_extrude(p.outline, p.z0, p.z1) for p in items])


def hole_segments(d: float) -> int:
    """Sides for a hole cutter: about one per 0.1 mm of circumference, 12 to 32."""
    return int(min(32, max(12, round(math.pi * d / 0.1))))


def cylinders(items: list[Hole], segments: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Vertical prisms for spike holes, sized so a spike of diameter d always passes through."""
    if not items:
        return empty()
    n = segments or hole_segments(min(h.d for h in items))
    ang = 2 * math.pi * np.arange(n) / n
    ring = np.stack([np.cos(ang), np.sin(ang)], 1) / math.cos(math.pi / n)
    side = []
    for a in range(n):
        b = (a + 1) % n
        side += [(a, b, n + b), (a, n + b, n + a)]
    cap_b = [(2 * n, b, a) for a, b in ((a, (a + 1) % n) for a in range(n))]
    cap_t = [(2 * n + 1, n + a, n + b) for a, b in ((a, (a + 1) % n) for a in range(n))]
    template = np.array(side + cap_b + cap_t, dtype=np.int32)
    vs, ts = [], []
    for k, h in enumerate(items):
        xy = np.array([h.x, h.y]) + h.d / 2 * ring
        vs.append(np.vstack([np.column_stack([xy, np.full(n, h.z0)]),
                             np.column_stack([xy, np.full(n, h.z1)]),
                             [[h.x, h.y, h.z0], [h.x, h.y, h.z1]]]))
        ts.append(template + k * (2 * n + 2))
    return np.vstack(vs), np.vstack(ts).astype(np.int32)


def spikes(items: list[Spike]) -> tuple[np.ndarray, np.ndarray]:
    """Printed spikes, each its cross-section run along the rail, turned and placed."""
    if not items:
        return empty()
    vs, ts, offset = [], [], 0
    for sp in items:
        vz = sp.outline()
        n = len(vz)
        order = list(range(3, n)) + [0, 1]
        fan = [(2, a, b) for a, b in zip(order, order[1:])]
        side = []
        for a in range(n):
            b = (a + 1) % n
            side += [(a, b, n + b), (a, n + b, n + a)]
        t = np.array(side + [(c, b, a) for a, b, c in fan]
                     + [(n + a, n + b, n + c) for a, b, c in fan], dtype=np.int32)
        local = np.array([(sp.u0, v, z) for v, z in vz] + [(sp.u1, v, z) for v, z in vz])
        c, s = math.cos(sp.angle), math.sin(sp.angle)
        v = np.column_stack([sp.cx + c * local[:, 0] - s * local[:, 1],
                             sp.cy + s * local[:, 0] + c * local[:, 1], local[:, 2]])
        if signed_volume(v, t) < 0:
            t = t[:, ::-1].copy()
        vs.append(v)
        ts.append(t + offset)
        offset += 2 * n
    return np.vstack(vs), np.vstack(ts).astype(np.int32)


def signed_volume(verts: np.ndarray, tris: np.ndarray) -> float:
    """Signed volume of a closed mesh; positive when its triangles face outward."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def combine(*parts: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Several meshes as one, keeping each shell separate."""
    vs, ts, offset = [], [], 0
    for v, t in parts:
        if len(v) == 0:
            continue
        vs.append(v)
        ts.append(t + offset)
        offset += len(v)
    if not vs:
        return empty()
    return np.vstack(vs), np.vstack(ts).astype(np.int32)


def mirror_y(mesh: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """The mesh mirrored across the XZ plane (left-hand to right-hand), still facing outward."""
    v, t = mesh
    if len(v) == 0:
        return mesh
    v = v.copy()
    v[:, 1] *= -1
    return v, t[:, ::-1].copy()


def place_board(verts: np.ndarray, tie_height: float, x: float, y: float,
                turn: bool, yaw_deg: float) -> np.ndarray:
    """Move a Weathered Board board into its place: length across the track, centred at (x, y).

    Boards come centred on the origin with length on X, width on Y and
    thickness on Z; they are turned 90 degrees (or 270 with ``turn``) plus a
    small yaw, and raised so their bottom is at Z = 0.
    """
    angle = math.radians(90.0 + (180.0 if turn else 0.0) + yaw_deg)
    c, s = math.cos(angle), math.sin(angle)
    out = np.empty_like(verts)
    out[:, 0] = c * verts[:, 0] - s * verts[:, 1] + x
    out[:, 1] = s * verts[:, 0] + c * verts[:, 1] + y
    out[:, 2] = verts[:, 2] + tie_height / 2
    return out


def open_edges(triangles: np.ndarray) -> int:
    """Number of edges not shared by exactly two triangles in opposite directions."""
    if len(triangles) == 0:
        return 0
    t = triangles.astype(np.int64)
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    n = int(e.max()) + 1
    fwd = e[:, 0] * n + e[:, 1]
    rev = e[:, 1] * n + e[:, 0]
    fwd_u, fwd_c = np.unique(fwd, return_counts=True)
    return int(np.sum(fwd_c != 1)) + int(np.isin(rev, fwd_u, invert=True).sum())
