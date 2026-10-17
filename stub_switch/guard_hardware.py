"""Guard rail brackets and their bolts. Pure Python and numpy, no bpy.

Each guard rail is bolted to its running rail (Guard L to Outer L, Guard R
to Stock R) through filler brackets. A bracket fills the space between the
two rails' webs, standing on the rail feet; its top stays below the lowest
point a wheel flange reaches in the flangeway (the rail top less the flange
depth, less a clearance) and below the rail heads, so it never touches a
flange. Each bracket has two bolts through both webs: a rounded (carriage)
bolt head on the field side of the running rail's web, and a washer and hex
nut on the guard rail's other side, toward the track centre.

The bracket, washers and nuts belong to the guard rail; the bolt heads to
the running rail. Everything is in the turnout's left-handed plan frame
(turnout.py), model millimetres, with the rail bottoms at ``seat``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import geom2d as g2

# NMRA RP-25 flange depths, model mm, by scale (the deepest common wheel flanges).
FLANGE_DEPTH = {"Z": 0.50, "N": 0.56, "TT": 0.64, "HO": 0.71, "OO": 0.71, "S": 0.89,
                "O": 1.00, "G": 1.50}
FLANGE_CLEAR = 0.10  # model mm between the bracket's top and the deepest flange

# Which running rail each guard rail is bolted to.
RUNNING_RAIL = {"Guard L": "Outer L", "Guard R": "Stock R"}


@dataclass
class RailSize:
    """The rail profile, model mm."""

    height: float
    head_width: float
    head_depth: float
    web: float
    base_width: float
    base_thickness: float  # at the web
    base_edge: float  # at the foot's edge


@dataclass
class BracketSpec:
    """How the guard rails are bolted. Prototype sizes in full-size mm."""

    scale_n: float
    flangeway: float  # model mm
    count: int = 2  # brackets per guard rail
    length: float = 457.2  # 18 in
    bolt: float = 25.4  # 1 in bolts
    flange_depth: float = 0.0  # model mm; 0 = by scale (FLANGE_DEPTH)
    scale_name: str = "HO"
    flare_length: float = 0.0  # model mm at each end of a guard rail that bends in

    def model(self, full_mm: float) -> float:
        """A full-size length in model mm."""
        return full_mm / self.scale_n


def flange_depth(b: BracketSpec, rail: RailSize) -> float:
    """The deepest wheel flange to clear, model mm."""
    if b.flange_depth > 0:
        return b.flange_depth
    return FLANGE_DEPTH.get(b.scale_name.upper(), 0.35 * rail.height)


def bracket_top(b: BracketSpec, rail: RailSize) -> float:
    """Height of a bracket's top above the rail bottom: clear of flanges and the rail heads."""
    return min(rail.height - rail.head_depth - 0.02,
               rail.height - flange_depth(b, rail) - FLANGE_CLEAR)


def hardware(guards: dict, b: BracketSpec, rail: RailSize, seat: float) -> tuple[dict, list[str]]:
    """Brackets, nuts, washers and bolt heads for the guard rails.

    ``guards`` maps "Guard L" / "Guard R" to their plan polylines. Returns
    ({rail name: [(verts, tris), ...]}, warnings): the guard rails' parts
    under their own names, the bolt heads under the running rails' names.
    """
    out: dict[str, list] = {}
    warnings = []
    top = bracket_top(b, rail)
    bottom = rail.base_edge - 0.02  # on the feet where they meet between the rails
    if top - bottom < 0.1:
        return out, ["Guard rail brackets left out: the wheel flanges reach too close to the "
                     "rail feet for a bracket under them."]
    d = b.flangeway + rail.head_width  # guard rail centre to running rail centre
    if d - rail.web < 0.1:
        return out, ["Guard rail brackets left out: no room between the rail webs."]
    lb = b.model(b.length)
    bolt = b.model(b.bolt)
    head_r, head_h = 0.875 * bolt, 0.5 * bolt  # rounded carriage bolt head
    washer_r, washer_t = 1.125 * bolt, 0.25 * bolt
    nut_af, nut_t = 1.625 * bolt, 0.875 * bolt
    z_bolt = seat + (rail.base_thickness + top) / 2
    if z_bolt - seat - max(head_r, washer_r, nut_af / 2 / math.cos(math.pi / 6)) < \
            rail.base_thickness * 0.5:
        warnings.append("The guard rail bolts are large for this rail's web.")
    for name, pts in guards.items():
        running = RUNNING_RAIL.get(name)
        if running is None or pts is None or len(pts) < 2:
            continue
        total = float(g2.lengths(pts)[-1])
        s0, s1 = b.flare_length, total - b.flare_length  # the straight part, beside the rail
        if s1 - s0 < lb:
            warnings.append(f"{name}: too short between its bent ends for a bracket.")
            continue
        n = max(1, int(b.count))
        while n > 1 and (s1 - s0) / n < lb:
            n -= 1
        side = 1.0 if name.endswith("L") else -1.0  # toward the running rail
        for i in range(n):
            s = s0 + (i + 0.5) * (s1 - s0) / n
            p, h = g2.at_length(pts, s)
            tv = np.array([math.cos(h), math.sin(h), 0.0])
            nv = side * np.array([-math.sin(h), math.cos(h), 0.0])
            c = np.array([p[0], p[1], 0.0])
            # The bracket, between the webs (a little into each so they join).
            out.setdefault(name, []).append(oriented_box(
                c, tv, nv, -lb / 2, lb / 2, rail.web / 2 - 0.02, d - rail.web / 2 + 0.02,
                seat + bottom, seat + top))
            for k in (-0.25, 0.25):  # two bolts per bracket
                at = c + tv * k * lb + np.array([0.0, 0.0, z_bolt])
                # Washer and nut on the guard rail's far side, toward the track centre.
                w0 = at - nv * (rail.web / 2 - 0.02)
                out[name].append(revolve(w0, -nv, tv, [(0, 0), (washer_r, 0),
                                                       (washer_r, washer_t + 0.02),
                                                       (0, washer_t + 0.02)], 16))
                n0 = w0 - nv * (washer_t + 0.01)
                out[name].append(revolve(n0, -nv, tv, [(0, 0), (nut_af / 2 / math.cos(math.pi / 6), 0),
                                                       (nut_af / 2 / math.cos(math.pi / 6), nut_t),
                                                       (0, nut_t)], 6))
                # Rounded head on the running rail's field side.
                h0 = at + nv * (d + rail.web / 2 - 0.02)
                out.setdefault(running, []).append(dome(h0, nv, tv, head_r, head_h + 0.02, 16))
    return out, warnings


# ---------------------------------------------------------------- meshes


def oriented_box(c, tv, nv, t0, t1, n0, n1, z0, z1):
    """A box from c + tv*t0..t1 + nv*n0..n1, z0..z1 (tv, nv horizontal). (verts, tris)."""
    verts = []
    for z in (z0, z1):
        for t, n in ((t0, n0), (t1, n0), (t1, n1), (t0, n1)):
            q = c + tv * t + nv * n
            verts.append((q[0], q[1], z))
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
            (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return _outward(np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int64))


def revolve(origin, axis, side, profile, segments: int):
    """A solid of revolution about ``axis`` from ``origin``. (verts, tris).

    ``profile`` is (radius, distance along the axis) from a point on the
    axis, out and round to another point on the axis. ``side`` is any
    direction across the axis (where the first segment starts).
    """
    a = np.asarray(axis, dtype=np.float64)
    a /= np.linalg.norm(a)
    b = np.asarray(side, dtype=np.float64) - a * float(np.dot(side, a))
    b /= np.linalg.norm(b)
    c = np.cross(a, b)
    o = np.asarray(origin, dtype=np.float64)
    angles = [2 * math.pi * k / segments for k in range(segments)]
    verts = [o + a * profile[0][1]]
    rings = []
    for r, ax in profile[1:-1]:
        rings.append(len(verts))
        for th in angles:
            verts.append(o + a * ax + r * (math.cos(th) * b + math.sin(th) * c))
    verts.append(o + a * profile[-1][1])
    last = len(verts) - 1
    tris = []
    m = segments
    for k in range(m):
        tris.append((0, rings[0] + (k + 1) % m, rings[0] + k))
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(m):
            k1 = (k + 1) % m
            tris += [(r0 + k, r0 + k1, r1 + k1), (r0 + k, r1 + k1, r1 + k)]
    for k in range(m):
        tris.append((last, rings[-1] + k, rings[-1] + (k + 1) % m))
    return _outward(np.array(verts), np.array(tris, dtype=np.int64))


def dome(base, axis, side, radius: float, height: float, segments: int):
    """A rounded bolt head: a spherical cap ``radius`` across its base, ``height`` tall."""
    big = (radius ** 2 + height ** 2) / (2 * height)  # sphere through the rim and the top
    a0 = math.asin(min(1.0, radius / big))
    prof = [(0.0, 0.0), (radius, 0.0)]
    for k in range(1, 5):
        ang = a0 * (1 - k / 5)
        prof.append((big * math.sin(ang), height - big * (1 - math.cos(ang))))
    prof.append((0.0, height))
    return revolve(base, axis, side, prof, segments)


def _outward(verts: np.ndarray, tris: np.ndarray):
    """Flip the triangles if the closed mesh's normals point inward."""
    v = verts[tris]
    vol = float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum()) / 6
    if vol < 0:
        tris = tris[:, ::-1]
    return verts, np.ascontiguousarray(tris)


def mirror(verts: np.ndarray, tris: np.ndarray):
    """Mirror across the straight route's centreline (y to -y), keeping normals outward."""
    v = verts.copy()
    v[:, 1] *= -1
    return v, np.ascontiguousarray(tris[:, ::-1])
