"""Stub switch (stub turnout) track geometry in plan view. Pure Python, no bpy.

Axes and units follow Tie Strip: X runs along the straight route, Y across
it, model millimetres. The turnout is built left-handed (the diverging
route turns toward +Y, looking along +X from the points end); a right-hand
turnout is the mirror image and is made by mirroring at the very end.

The parts, from the points end::

    approach    movable rails     headblock          lead curve           frog       tail
    ======== heel ~~~~~~~~~~~~~~~~~~ | ========== closure rails ======== >V< ========
                 (bent sideways)     X = 0                               TP

* **Movable rails.** A stub switch has no points. The two rails coming from
  the approach are spiked down only up to their **heel**; from there to the
  **headblock** (X = 0) they are free and bend sideways, held by the head
  rod, to line up with either the straight or the diverging rails, which
  both end square at the headblock. The bent rail is a cantilever: its
  sideways shift from the heel is ``throw * (3 f^2 - f^3) / 2`` with f the
  fraction of the way to the headblock, so it leaves the heel straight and
  reaches the headblock shifted by the **throw** at an angle
  ``atan(1.5 * throw / movable length)``, the **switch angle**.
* **Lead curve.** The diverging rails start at the headblock one throw to
  the side, at the switch angle, and curve (a circular arc on the gauge line
  of the inner diverging rail) until they reach the frog angle at the frog's
  toe. The frog is straight, as on the prototype, so the arc ends exactly at
  the toe and the frog's theoretical point (TP) is one toe length further.
  The arc radius and the distance from the headblock to the TP follow from
  the gauge, throw, switch angle, frog angle and frog toe length.
* **Frog.** Made by the Switch Frog add-on and laid on the turnout with its
  TP where the inner diverging gauge line crosses the straight route's left
  gauge line. ``frog_lines`` (gauge lines in the frog's own frame) are
  turned into this frame so the ties, plates and spikes allow for it.
* **Guard rails** sit opposite the frog on the straight route's right rail
  and the diverging route's outer rail, one flangeway inside. By default
  they are a little shorter than the frog (the frog reaches
  ``guard_frog_margin`` past each end), and each end bends in toward the
  track centre.
* **Frog heel rails** (optional): a short rail leaves each of the frog's
  heel ends, as long as the guard rails; the route's rail carries on from
  there.

``compute`` returns a ``Turnout``: the rail lines (centrelines) with what
each one is (for tie plates, spikes and tie lengths), the rails to draw,
key positions, and errors and warnings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geom2d as g2

FAR = 4000.0  # model mm: open-ended lines run this far; the layout clips them

# What a rail line is, for tie plates and spikes.
RUNNING, MOVABLE, FROG, GUARD = "RUNNING", "MOVABLE", "FROG", "GUARD"


@dataclass
class TurnoutSpec:
    """Every input to the turnout geometry. Lengths are model mm unless marked full-size."""

    scale_n: float
    gauge: float
    head_width: float
    foot_width: float
    frog_number: float
    frog_toe: float  # TP to the frog's toe, measured along a gauge line
    frog_heel: float  # TP to the frog's heel, along a gauge line
    frog_point: float  # TP to the frog's actual (blunt) point, along the centreline
    flangeway: float
    movable_length: float  # full-size mm, heel to headblock
    throw: float = 0.0  # sideways travel at the headblock; 0 = foot width + THROW_CLEAR
    headblock_gap: float = 0.1  # gap between the movable rail ends and the fixed rail ends
    guard_rails: bool = True
    heel_rails: bool = True  # short rails from the frog's heel, as long as the guard rails
    guard_mode: str = "FROG"  # "FROG": set by the frog's length; "LENGTH": guard_length
    guard_frog_margin: float = 304.8  # full-size mm the frog reaches past each guard rail end
    guard_length: float = 1828.8  # full-size mm (6 ft), for guard_mode "LENGTH"
    guard_flare_length: float = 457.2  # full-size mm bent in at each end (18 in)
    guard_flare_angle: float = 15.0  # degrees
    frog_lines: list = field(default_factory=list)  # [(frog-frame gauge polyline, body side)]
    frog_error: str = ""

    def model(self, full_mm: float) -> float:
        """A full-size length in model mm."""
        return full_mm / self.scale_n

    def frog_angle(self) -> float:
        """The frog angle in radians: 2 atan(1 / (2N))."""
        return 2.0 * math.atan(1.0 / (2.0 * self.frog_number))


THROW_CLEAR = 0.25  # model mm between the rail feet of the two sets of fixed rails


@dataclass
class RailLine:
    """One rail's centreline in plan view and what it is.

    ``group`` names the physical rail: lines in the same group (a movable
    rail drawn in both of its positions) never count as crowding each other.
    ``field_side`` is +1 when the rail's field side (outside of its track)
    is toward +Y and -1 toward -Y; 0 for frog rails and guard rails.
    ``ghost`` lines (a movable rail's other position) shape the ties and
    slide plates but get no spikes. ``free_x`` is the X range in which the
    rail is not spiked (the movable part of a movable rail).
    """

    name: str
    pts: np.ndarray
    kind: str = RUNNING
    group: str = ""
    field_side: int = 0
    ghost: bool = False
    free_x: tuple[float, float] | None = None

    def __post_init__(self):
        """Default the group to the line's name."""
        self.group = self.group or self.name


@dataclass
class Turnout:
    """The computed turnout, all model mm (left-handed, see the module docstring)."""

    rail_y: float = 0.0  # straight route rails' centrelines at +/- rail_y
    throw: float = 0.0
    switch_angle: float = 0.0  # radians
    frog_angle: float = 0.0  # radians
    lead_radius: float = 0.0  # radius of the lead curve on the diverging route's centreline
    movable_length: float = 0.0
    tp: tuple[float, float] = (0.0, 0.0)
    frog_toe_x: float = 0.0  # where the frog starts and ends on the straight route
    frog_heel_x: float = 0.0
    lines: list[RailLine] = field(default_factory=list)  # for ties, plates and spikes
    connector_lines: list[np.ndarray] = field(default_factory=list)  # joined under these
    rails: dict = field(default_factory=dict)  # name -> centreline, for the rail objects
    thrown_rails: dict = field(default_factory=dict)  # movable rails, set for the diverging route
    guard_span: tuple[float, float] = (0.0, 0.0)  # guard rail ends, along the route from the TP
    heel_rail_length: float = 0.0  # the short rails at the frog's heel (0 = none)
    half_gap: float = 0.0  # half the headblock gap: fixed rails start here, movable rails end at -it
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there are no errors."""
        return not self.errors


def bend(movable: float, throw: float, x: np.ndarray) -> np.ndarray:
    """Sideways shift of a thrown movable rail at ``x`` (heel at -movable, headblock at 0)."""
    f = np.clip((x + movable) / movable, 0.0, 1.0)
    return throw * (3 * f ** 2 - f ** 3) / 2


def frog_to_turnout(tp, frog_angle: float, pts) -> np.ndarray:
    """Points in the frog's own frame (x across, y toward the heel, TP at 0) in this frame.

    The frog's centreline bisects the frog angle, so it points at half the
    frog angle from +X, and its +x (right, looking toward the heel) points
    at half the angle minus 90 degrees. Its right-hand route then runs
    along the straight route.
    """
    t = frog_angle / 2
    c, s = math.cos(t), math.sin(t)
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    fx, fy = p[:, 0], p[:, 1]
    return np.column_stack([tp[0] + fy * c + fx * s, tp[1] + fy * s - fx * c])


def _check(s: TurnoutSpec) -> list[str]:
    """Errors for inputs that can't make a turnout."""
    errs = []
    if s.frog_error:
        errs.append(s.frog_error)
    if s.gauge <= 0:
        errs.append("Enter the gauge.")
    if s.head_width <= 0 or s.foot_width <= 0:
        errs.append("The frog's rail profile has no head or foot width.")
    if not 1.0 <= s.frog_number <= 40.0:
        errs.append("The frog number must be between 1 and 40.")
    if s.movable_length <= 0:
        errs.append("Enter the movable rail length.")
    if s.throw < 0:
        errs.append("The throw can't be negative.")
    if s.frog_toe <= 0 or s.frog_heel <= 0:
        errs.append("The frog has no toe or heel length.")
    return errs


def compute(s: TurnoutSpec) -> Turnout:
    """Lay out the turnout's rails. Check ``turnout.errors`` before using it."""
    t = Turnout()
    t.errors = _check(s)
    if t.errors:
        return t
    g, hw, half_foot = s.gauge, s.head_width, s.foot_width / 2
    yr = t.rail_y = g / 2 + hw / 2
    F = t.frog_angle = s.frog_angle()
    throw = t.throw = s.throw if s.throw > 0 else s.foot_width + THROW_CLEAR
    lm = t.movable_length = s.model(s.movable_length)
    alpha = t.switch_angle = math.atan(1.5 * throw / lm)
    gap = t.half_gap = s.headblock_gap / 2

    if throw < s.foot_width:
        t.warnings.append(f"The throw ({throw:.2f} mm) is less than the rail foot width "
                          f"({s.foot_width:.2f} mm), so the rail feet overlap at the headblock.")
    if alpha >= F:
        t.errors.append(f"The switch angle ({math.degrees(alpha):.2f} deg) is not less than the "
                        f"frog angle ({math.degrees(F):.2f} deg): make the movable rails longer "
                        "or the throw smaller.")
        return t
    toe = s.frog_toe
    rise = g - throw - toe * math.sin(F)  # what the lead curve must climb
    if rise <= 0:
        t.errors.append("The frog's toe is too long for this gauge and throw; there is no room "
                        "for a lead curve. Shorten the frog (Manual length) or the throw.")
        return t
    radius = rise / (math.cos(alpha) - math.cos(F))  # on the inner diverging gauge line
    p0 = np.array([0.0, -g / 2 + throw])
    lead = g2.arc(p0, alpha, F, radius, step=min(2.0, max(0.25, math.sqrt(8 * radius * 0.001))))
    pt = lead[-1]  # the frog's toe on the diverging route
    tp = pt + toe * np.array([math.cos(F), math.sin(F)])
    t.tp = (float(tp[0]), float(tp[1]))
    t.lead_radius = radius + g / 2
    t.frog_toe_x, t.frog_heel_x = tp[0] - toe, tp[0] + s.frog_heel
    if t.frog_toe_x < 4 * gap + s.foot_width:
        t.errors.append("The frog's toe reaches the headblock; use a longer frog number or "
                        "shorter movable rails.")
        return t

    # Inner diverging gauge line: a short run back from the headblock (so the
    # offset outer rail reaches it), the lead curve, then straight through the frog.
    back = g2.straight(p0, alpha + math.pi, 2 * g)[::-1]
    gd = g2.join(back, lead, g2.straight(pt, F, FAR))
    d_in = g2.offset(gd, -hw / 2)
    d_out = g2.offset(gd, g + hw / 2)
    big = FAR

    # ---- lines for ties, plates and spikes ----
    xs = np.linspace(-lm, 0.0, max(8, int(lm / 0.5)))
    lines = t.lines
    for name, side in (("Movable L", 1), ("Movable R", -1)):
        y = side * yr
        lines.append(RailLine(name, g2.as_poly([(-big, y), (-gap, y)]), MOVABLE, name, side,
                              free_x=(-lm + 1e-6, 0.0)))
        thrown = g2.clip_x(g2.as_poly(np.column_stack([xs, y + bend(lm, throw, xs)])), -lm, -gap)
        lines.append(RailLine(name + " thrown", thrown, MOVABLE, name, side, ghost=True,
                              free_x=(-lm + 1e-6, 0.0)))
        t.thrown_rails[name] = g2.join([(-big, y)], thrown)
    lines.append(RailLine("Stock R", g2.as_poly([(gap, -yr), (big, -yr)]), RUNNING, "", -1))
    lines.append(RailLine("Closure L", g2.as_poly([(gap, yr), (t.frog_toe_x, yr)]), RUNNING, "", 1))
    lines.append(RailLine("Straight L", g2.as_poly([(t.frog_heel_x, yr), (big, yr)]), RUNNING, "", 1))
    # The inner diverging rail's centre is hw/2 to the right of its gauge line,
    # so where it meets the frog's toe and heel is shifted along X by hw/2 sin F.
    toe_x = pt[0] + hw / 2 * math.sin(F)
    heel_x = tp[0] + s.frog_heel * math.cos(F) + hw / 2 * math.sin(F)
    lines.append(RailLine("Closure R", g2.clip_x(d_in, gap, toe_x), RUNNING, "", -1))
    lines.append(RailLine("Diverging R", g2.clip_x(d_in, heel_x, big), RUNNING, "", -1))
    lines.append(RailLine("Outer L", g2.clip_x(d_out, gap, big), RUNNING, "", 1))

    for i, (local, body) in enumerate(s.frog_lines):
        gauge_line = frog_to_turnout(tp, F, local)
        lines.append(RailLine(f"Frog {i}", g2.offset(gauge_line, body * hw / 2), FROG))

    if s.guard_rails:
        _guard_rails(s, t, gd, tp)

    for ln in t.lines:
        if not ln.ghost and ln.kind != FROG:
            t.rails[ln.name] = ln.pts
    if s.heel_rails:
        _heel_rails(s, t)
    t.connector_lines = [g2.as_poly([(-big, yr), (big, yr)]), g2.as_poly([(-big, -yr), (big, -yr)]),
                         g2.clip_x(d_in, gap, big), g2.clip_x(d_out, gap, big)]
    if radius + g / 2 < 300:  # very tight for anything but the smallest scales
        t.warnings.append(f"The lead curve is only {radius + g / 2:.0f} mm radius; check your "
                          "equipment can run through it.")
    return t


def guard_span(s: TurnoutSpec) -> tuple[float, float]:
    """Where a guard rail starts and ends, model mm along its route from the frog's TP.

    "FROG" (the default): the frog's length less ``guard_frog_margin`` at
    each end, so the frog reaches a little past the guard rail both ways.
    "LENGTH": ``guard_length`` long, centred opposite the frog's actual point.
    """
    if s.guard_mode == "LENGTH":
        half = s.model(s.guard_length) / 2
        return s.frog_point - half, s.frog_point + half
    m = s.model(s.guard_frog_margin)
    return -s.frog_toe + m, s.frog_heel - m


def _guard_rails(s: TurnoutSpec, t: Turnout, gd: np.ndarray, tp: np.ndarray) -> None:
    """Add the two guard rails opposite the frog, each end bent in toward the track centre.

    Each guard rail runs one flangeway inside its running rail. Over the
    last ``guard_flare_length`` at each end it bends in toward the middle of
    the track at ``guard_flare_angle``, so a wheel flange is led into the
    flangeway rather than striking the rail end.
    """
    g, hw, fw = s.gauge, s.head_width, s.flangeway
    u0, u1 = guard_span(s)
    length = u1 - u0
    flare = s.model(s.guard_flare_length)
    if length <= 2 * flare + 1e-6:
        t.warnings.append("The guard rails are too short for their bent ends; shorten the bends "
                          "or make the guard rails longer. No guard rails added.")
        return
    if not u0 < s.frog_point < u1:
        t.warnings.append("The guard rails don't reach the frog's point; make them longer.")
    out = flare * math.tan(math.radians(s.guard_flare_angle))
    bends = [u0, u0 + flare, u1 - flare, u1]
    us = np.unique(np.concatenate([np.linspace(u0, u1, 40), bends]))
    extra = np.interp(us, bends, [out, 0.0, 0.0, out])
    centre = fw + hw / 2 + extra  # from the running rail's gauge line, toward the track centre

    # Straight route: inside the right-hand stock rail (gauge line y = -g/2).
    pts = np.column_stack([tp[0] + us, -g / 2 + centre])
    t.lines.append(RailLine("Guard R", g2.as_poly(pts), GUARD))
    # Diverging route: inside the outer rail (gauge line = gd moved g to the left).
    s_tp = g2.length_at_x(gd, tp[0])
    pts = []
    for u, c in zip(us, centre):
        p, h = g2.at_length(gd, s_tp + u)
        pts.append(p + (g - c) * np.array([-math.sin(h), math.cos(h)]))
    t.lines.append(RailLine("Guard L", g2.as_poly(pts), GUARD))
    t.guard_span = (u0, u1)


def _heel_rails(s: TurnoutSpec, t: Turnout) -> None:
    """Split a short rail off the start of each rail leaving the frog's heel.

    Each is as long as the guard rails, so the frog and its heel rails make
    one piece to lay; the rest of the route's rail starts where it ends.
    """
    u0, u1 = guard_span(s)
    length = u1 - u0
    if length <= 0:
        return
    for name, label in (("Straight L", "Frog Heel L"), ("Diverging R", "Frog Heel R")):
        pts = t.rails.get(name)
        if pts is None or len(pts) < 2:
            continue
        end, _h = g2.at_length(pts, length)
        t.rails[label] = g2.clip_x(pts, pts[0, 0], end[0])
        rest = g2.clip_x(pts, end[0], pts[-1, 0])
        if len(rest) >= 2:
            t.rails[name] = rest
        else:
            del t.rails[name]
    t.heel_rail_length = length
