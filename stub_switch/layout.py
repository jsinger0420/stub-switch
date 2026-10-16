"""Where every tie, connector, tie plate, shoulder and spike goes. Pure Python, no bpy.

Works on a ``turnout.Turnout`` (the rail lines in plan view) and a ``Spec``
(the tie, plate and spike settings). Axes as in turnout.py: X along the
straight route, Y across it, Z up, model millimetres, left-handed; tie
bottoms sit on Z = 0, the print bed.

**Ties.** Ties are square to the straight route, one spacing apart. The
headblock (X = 0, where the movable rails meet the fixed rails) sits on a
**double tie**: the long headblock tie under the movable rails' ends and a
standard tie right next to it under the fixed rails' ends,
``double_tie_gap`` apart and centred on the headblock. The second
headblock tie is ``headblock_tie_gap`` before the double tie (a tie width
by default), and the ties before that are one spacing apart again; the
ties past the double tie are one spacing apart. The strip starts ``approach_ties``
ties before the heel of the movable rails and ends ``tail_ties`` ties past
the frog's heel. Every tie has the template tie's width and thickness. Its
length is the template's (the standard tie) under plain track; where the
diverging rails spread, the tie reaches as far past the outermost rail as
a standard tie does past its rail, rounded up to the next ``length_step``
(6 in on the prototype). As on the prototype, the ties are lined up on the
straight route's side and grow toward the diverging side. The headblock
ties are lengthened on the switch stand side.

**Tie plates** sit square on the ties under every rail; where two rails are
closer than a plate allows (the headblock, the frog, the guard rails) their
plates merge into one long plate. In the movable section they are slide
plates: plain, wide enough for both positions of the movable rail, with no
shoulders. **Shoulders** follow the rail, so they stay beside the rail foot
on the angled diverging rails, and are left out where another rail is in
the way.

**Spikes.** Each fixed rail gets a spike hole (or a printed spike) on each
side on every tie, turned to the rail's direction; a spike is left out
where it would land on another rail, off the tie, or inside a solid frog.
The movable rails are not spiked between the heel and the headblock.

**Connectors** join the ties under the straight route's rails and the
diverging route's rails, following each rail's line.

**Two pieces.** With ``split`` on, the strip prints as two pieces that meet
in the gap just before the double tie (or before both headblock ties):
the movable rail section and the fixed rail section. In the gap where they
meet, each connector becomes a tab on the movable piece that reaches
``tab_depth`` into a matching socket in the fixed piece's tie, open at the
bottom, with ``joint_clearance`` all round; the tabs line the pieces up and
are glued in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geom2d as g2
from .turnout import FROG, GUARD, MOVABLE, Turnout

HOLES, PRINTED, NONE = "HOLES", "PRINTED", "NONE"  # fastening
SHOULDERS_NONE, SHOULDERS_FIELD, SHOULDERS_DOUBLE = "NONE", "FIELD", "DOUBLE"
STRAIGHT_SIDE, DIVERGING_SIDE = "STRAIGHT", "DIVERGING"

HOLE_EXTRA = 1.0  # hole cutters run this far past the bottom and the top, model mm
PLATE_MERGE = 0.3  # model mm: plates closer than this become one plate
SPIKE_CLEAR = 0.05  # model mm: a spike or hole keeps this far from another rail's foot


@dataclass(frozen=True)
class Box:
    """An axis-aligned box, model mm."""

    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float


@dataclass(frozen=True)
class Prism:
    """A vertical prism: a plan-view outline (counter-clockwise (x, y) points) from z0 to z1."""

    outline: tuple[tuple[float, float], ...]
    z0: float
    z1: float


@dataclass(frozen=True)
class Hole:
    """A vertical spike hole: centre (x, y), diameter d, from z0 to z1. Model mm."""

    x: float
    y: float
    d: float
    z0: float
    z1: float


@dataclass(frozen=True)
class Spike:
    """A printed spike, as in Tie Strip, in the rail's own frame.

    The spike's cross-section across the rail is the same along its whole
    length: an L, with a chamfer under the head. ``u0`` and ``u1`` are its
    ends along the rail; ``v_head``, ``v_shank_in`` and ``v_shank_out`` are
    distances across the rail from its centreline (signed: the side the spike
    is on); ``under`` lists the (v, z) points of the head's underside from
    its inner edge out to the shank. The rail frame is placed at (``cx``,
    ``cy``) and turned ``angle`` radians from +X. Model mm.
    """

    cx: float
    cy: float
    angle: float
    u0: float
    u1: float
    v_head: float
    v_shank_in: float
    v_shank_out: float
    z0: float
    z_head: float
    z_top: float
    under: tuple[tuple[float, float], ...] = ()

    def outline(self) -> list[tuple[float, float]]:
        """The cross-section as (v, z) points in order, repeated points removed."""
        pts = [(self.v_shank_in, self.z0), (self.v_shank_out, self.z0),
               (self.v_shank_out, self.z_top), (self.v_head, self.z_top)]
        pts += list(self.under) or [(self.v_head, self.z_head), (self.v_shank_in, self.z_head)]
        out = []
        for p in pts:
            if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
                out.append(p)
        return out


@dataclass(frozen=True)
class Tie:
    """One tie: centre X, and its ends across the track (before variation). Model mm."""

    x: float
    y0: float
    y1: float
    headblock: bool = False
    lowered: float = 0.0  # model mm off the top, so a headblock plate sits level with bare ties

    @property
    def length(self) -> float:
        """The tie's length across the track."""
        return self.y1 - self.y0

    @property
    def y_centre(self) -> float:
        """The middle of the tie across the track."""
        return (self.y0 + self.y1) / 2


@dataclass
class Spec:
    """The tie, plate and spike settings. Prototype sizes in full-size mm, the rest model mm."""

    scale_n: float
    tie_length: float  # the template (standard) tie, full-size mm
    tie_width: float
    tie_height: float
    spacing: float  # full-size mm, centre to centre
    foot_width: float  # model mm, from the rail profile
    head_width: float
    tie_error: str = ""
    approach_ties: int = 2  # ties before the heel of the movable rails
    tail_ties: int = 3  # ties past the frog's heel
    length_step: float = 152.4  # full-size mm; turnout ties come in 6 in steps
    headblock_ties: int = 2
    headblock_extra: float = 914.4  # full-size mm added on the switch stand side
    headblock_tie_gap: float = -1.0  # full-size mm between the two headblock ties; < 0 = a tie width
    double_tie_gap: float = 12.7  # full-size mm between the two ties of the double tie
    stand_side: str = STRAIGHT_SIDE

    connector_width: float = 0.0  # model mm; 0 = the rail foot width
    connector_height_frac: float = 0.5
    connector_overlap: float = 0.3

    fastening: str = HOLES
    hole_diameter: float = 0.5
    hole_clearance: float = 0.0
    stagger: float = 0.0  # full-size mm
    foot_edge: float = 0.0  # rail foot thickness at its edge, model mm
    foot_web: float = 0.0
    web_width: float = 0.0
    spike_shank: float = 0.4
    spike_overhang: float = 0.2
    spike_head: float = 0.2
    spike_side_clear: float = 0.15
    spike_chamfer: float = 45.0
    spike_top_clear: float = 0.10
    spike_every: int = 1
    spike_bare_ends: int = 1

    length_jitter: float = 0.0  # full-size mm
    end_jitter: float = 0.0
    yaw_jitter: float = 0.0  # degrees

    plates: bool = False
    plate_length: float = 355.6
    plate_width: float = 196.85
    plate_thickness: float = 19.05
    plate_bias: float = 25.4
    shoulders: str = SHOULDERS_DOUBLE
    shoulder_height: float = 12.7
    shoulder_width: float = 19.05
    shoulder_clearance: float = 0.05

    seat_pad: bool = True
    seat_depth: float = 0.0
    seat_inset: float = 0.0
    seat_margin: float = 0.2

    headblock_plate: bool = True  # a plate across the double tie: clips and the throw stops
    headblock_plate_thickness: float = 19.05  # full-size mm, used when tie plates are off
    plate_margin: float = 0.2  # model mm the headblock plate reaches past its clips
    throw_stops: bool = True  # stops on the double tie's long tie limiting the movable rails
    stops_every_tie: bool = False  # also on every tie under the movable rails, past the heel
    stop_width: float = 0.5  # model mm across the track
    stop_clearance: float = 0.15  # model mm between a stop and the rail foot at the end of travel
    stop_height: float = 0.0  # model mm above the rail seat; 0 = the foot's thickness at the web
    bolts: bool = True  # bolt heads fastening the headblock plates and throw stops to the ties
    bolt_size: float = 38.1  # full-size mm across the flats of a hex bolt head (1-1/2 in)
    bolt_height: float = 19.05  # full-size mm (3/4 in)
    stop_plate_thickness: float = 12.7  # full-size mm, the throw stop's bolted base (1/2 in)

    split: bool = True  # print as two pieces: movable rail section and fixed rail section
    split_at: str = "HEADBLOCK"  # "HEADBLOCK": just before the double tie; "PAIR": before both
    tab_depth: float = 1.0  # model mm a joint tab reaches into the fixed piece's tie
    joint_clearance: float = 0.1  # model mm of play around each tab in its socket

    frog_solid: bool = False  # the frog has a fill or base plate: no spikes under it
    frog_base_plate: bool = False  # the frog brings its own plate: no tie plates under it

    def model(self, full_mm: float) -> float:
        """A full-size length in model mm."""
        return full_mm / self.scale_n


@dataclass
class Layout:
    """The computed tie strip for the turnout. All model mm."""

    ties: list[Tie] = field(default_factory=list)
    tie_width: float = 0.0
    tie_height: float = 0.0
    seat: float = 0.0  # rail seat height (tie top, or plate top)
    x_rail0: float = 0.0  # rails start and end here (half a tie spacing past the end ties)
    x_rail1: float = 0.0
    connectors: list[Prism] = field(default_factory=list)
    split_x: float | None = None  # pieces meet here: X below is the movable piece
    unit_x: tuple[float, ...] = ()  # the double tie at the headblock: long tie, then standard
    tabs: list[Prism] = field(default_factory=list)  # joint tabs, part of the movable piece
    hb_plates: list[Box] = field(default_factory=list)  # headblock plates
    clips: list[Spike] = field(default_factory=list)  # rail clips on the headblock plates
    stops: list[Box] = field(default_factory=list)  # throw stops and their bolted bases
    bolts: list[Prism] = field(default_factory=list)  # hex bolt heads
    sockets: list[Prism] = field(default_factory=list)  # cut from the fixed piece's tie
    plates: list[Box] = field(default_factory=list)
    shoulders: list[Prism] = field(default_factory=list)
    seats: list[Box] = field(default_factory=list)
    footings: list[Box] = field(default_factory=list)  # fill the grain under plates and stops
    holes: list[Hole] = field(default_factory=list)
    spikes: list[Spike] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when there are no errors and the turnout can be built."""
        return not self.errors

    @property
    def tie_x(self) -> list[float]:
        """Every tie's centre X."""
        return [t.x for t in self.ties]

    def in_unit(self, x: float) -> bool:
        """True for the two ties of the double tie at the headblock."""
        return any(abs(x - u) < 1e-9 for u in self.unit_x)

    def unit_ties(self) -> list[Tie]:
        """The double tie: the long headblock tie, then the standard tie past it."""
        return [tie for tie in self.ties if self.in_unit(tie.x)]


def _check(s: Spec) -> list[str]:
    """Errors for settings that can't describe a tie strip."""
    errs = []
    if s.scale_n < 1:
        errs.append("Scale must be 1:1 or smaller.")
    if s.tie_error:
        errs.append(s.tie_error)
    elif min(s.tie_length, s.tie_width, s.tie_height) <= 0:
        errs.append("The template tie's length, width and thickness must be positive.")
    if s.spacing <= 0:
        errs.append("Tie spacing must be positive.")
    if s.approach_ties < 0 or s.tail_ties < 0:
        errs.append("The number of approach and tail ties can't be negative.")
    if s.fastening not in (HOLES, PRINTED, NONE):
        errs.append(f"Unknown fastening '{s.fastening}'.")
    elif s.fastening == HOLES and s.hole_diameter <= 0:
        errs.append("Spike hole diameter must be positive.")
    elif s.fastening == PRINTED:
        if s.foot_edge <= 0:
            errs.append("Printed spikes need the rail foot edge thickness from the rail profile.")
        if min(s.spike_shank, s.spike_head) <= 0:
            errs.append("Printed spike shank width and head thickness must be positive.")
        if s.spike_overhang <= 0:
            errs.append("The printed spike head must reach over the rail foot: make the head "
                        "overhang more than 0.")
        if s.spike_every < 1:
            errs.append("Spike every Nth tie must be 1 or more.")
        if s.spike_chamfer and not 30.0 <= s.spike_chamfer <= 80.0:
            errs.append("The chamfer under the spike heads must be 0 (none) or 30 to 80 degrees.")
    if not 0 < s.connector_height_frac <= 1:
        errs.append("Connector height must be between 0 and 1 times the tie height.")
    if s.plates and min(s.plate_length, s.plate_width, s.plate_thickness) <= 0:
        errs.append("Tie plate length, width and thickness must be positive.")
    return errs


def compute(t: Turnout, s: Spec) -> Layout:
    """Lay out the turnout's tie strip. Check ``layout.errors`` before building."""
    lay = Layout()
    lay.errors = list(t.errors) + _check(s)
    if lay.errors:
        return lay
    lt, wt, ht = s.model(s.tie_length), s.model(s.tie_width), s.model(s.tie_height)
    p = s.model(s.spacing)
    lay.tie_width, lay.tie_height = wt, ht
    if p - wt <= 0:
        lay.errors.append(f"Ties overlap: spacing {p:.2f} mm is not more than the tie width "
                          f"{wt:.2f} mm.")
        return lay
    yr, half_foot = t.rail_y, s.foot_width / 2
    over = lt / 2 - yr  # how far a standard tie reaches past its rail's centre
    if over - half_foot <= 0:
        lay.errors.append("The rails hang off the ends of the template tie: the gauge is too wide "
                          "for its length.")
        return lay
    if over - half_foot < s.model(s.length_jitter) / 2 + s.model(s.end_jitter):
        lay.warnings.append("Tie length variation and end offset can put the rail foot over the "
                            "end of a tie; reduce them.")

    # ---- tie positions ----
    # The double tie, centred on the headblock: the long tie under the movable
    # rails' ends, the standard tie under the fixed rails' ends.
    half = (wt + max(s.model(s.double_tie_gap), 0.02)) / 2
    xl, xn = -half, half
    lay.unit_x = (xl, xn)
    na = int(math.floor(t.frog_heel_x / p + 1e-9)) + s.tail_ties  # tail ties past the heel
    after = [xn + i * p for i in range(0, na + 1)]
    before = [xl]  # ties before the headblock, nearest first
    x = xl
    if s.headblock_ties >= 2:
        hgap = s.model(s.headblock_tie_gap) if s.headblock_tie_gap >= 0 else wt
        if hgap < 0.1:
            lay.errors.append("The gap between the headblock ties must be at least 0.1 mm.")
            return lay
        x -= wt + hgap
        before.append(x)
    heel = -t.movable_length + 1e-9
    while sum(1 for b in before if b <= heel) < s.approach_ties + 1:
        x -= p
        before.append(x)
    xs = before[::-1] + after
    hb_x = {xl} if s.headblock_ties >= 1 else set()
    if s.headblock_ties >= 2:
        hb_x.add(before[1])
    lay.x_rail0, lay.x_rail1 = xs[0] - p / 2, xs[-1] + p / 2
    lines = []
    for ln in t.lines:
        pts = g2.clip_x(ln.pts, lay.x_rail0, lay.x_rail1)
        if len(pts) >= 2:
            lines.append((ln, pts))

    # ---- tie lengths ----
    step = s.model(s.length_step)
    for x in xs:
        spans = [g2.y_span(pts, x - wt / 2, x + wt / 2) for _ln, pts in lines]
        spans = [sp for sp in spans if sp]
        lo = min([-yr] + [a for a, _b in spans])
        hi = max([yr] + [b for _a, b in spans])
        y0, y1 = min(-lt / 2, lo - over), max(lt / 2, hi + over)
        extra = (y1 - y0) - lt
        if step > 0 and extra > 1e-6:
            y1 = y0 + lt + math.ceil(extra / step - 1e-6) * step
        hb = x in hb_x
        if hb:
            if s.stand_side == DIVERGING_SIDE:
                y1 += s.model(s.headblock_extra)
            else:
                y0 -= s.model(s.headblock_extra)
        lay.ties.append(Tie(x, y0, y1, hb))
    if s.headblock_plate and not s.plates:
        if s.model(s.headblock_plate_thickness) >= 0.5 * ht:
            lay.errors.append("The headblock plate is more than half as thick as the ties; make "
                              "it thinner (Headblock panel).")
            return lay
        lay.ties = [Tie(tie.x, tie.y0, tie.y1, tie.headblock,
                        s.model(s.headblock_plate_thickness) if lay.in_unit(tie.x) else 0.0)
                    for tie in lay.ties]

    # ---- plates, shoulders and rail seats ----
    tp = s.model(s.plate_thickness) if s.plates else 0.0
    lay.seat = ht + tp
    embed = max(0.1, s.seat_depth + 0.02) if s.seat_pad else 0.1
    top = lay.seat
    if s.plates:
        top = max(top, _plates(t, s, lay, lines, tp, embed))
    elif s.seat_pad and s.seat_depth > 0:
        _seat_pads(s, lay, lines)

    if s.headblock_plate or s.throw_stops:
        top = max(top, _headblock_hardware(t, s, lay, lines, embed))

    # ---- spikes ----
    if s.fastening == HOLES:
        _holes(t, s, lay, lines, top)
    elif s.fastening == PRINTED:
        top = max(top, _printed_spikes(t, s, lay, lines, embed))

    # ---- split into two pieces, then connectors (and joint tabs) ----
    if s.split:
        h = next(i for i, tie in enumerate(lay.ties) if abs(tie.x - xl) < 1e-9)
        k = h - 1 if s.split_at == "PAIR" and s.headblock_ties >= 2 and h >= 2 else h
        if k >= 1:
            lay.split_x = (lay.ties[k - 1].x + lay.ties[k].x) / 2
    _connectors(t, s, lay)

    longest = max(lay.ties, key=lambda tie: tie.length)
    lay.summary = {
        "plate_width": min(s.model(s.plate_width), wt - 2 * plate_edge(s, wt)) if s.plates else 0.0,
        "ties": float(len(lay.ties)),
        "tie_length": lt, "tie_width": wt, "tie_height": ht,
        "longest_tie": longest.length, "longest_tie_full": longest.length * s.scale_n,
        "gap": p - wt, "spacing": p,
        "overall_length": xs[-1] - xs[0] + wt,
        "overall_width": max(tie.y1 for tie in lay.ties) - min(tie.y0 for tie in lay.ties),
        "top": top,
        "lead": t.tp[0], "lead_radius": t.lead_radius,
        "switch_angle": math.degrees(t.switch_angle), "frog_angle": math.degrees(t.frog_angle),
        "throw": t.throw, "movable_length": t.movable_length,
        "frog_toe_x": t.frog_toe_x, "frog_heel_x": t.frog_heel_x,
        "rail_length": lay.x_rail1 - lay.x_rail0,
        "connector_width": s.connector_width or s.foot_width,
        "connector_height": s.connector_height_frac * ht,
    }
    return lay


SLAB_SINK = 0.05  # model mm a plate or stop sinks into the tie top, so they join


def _edge(s: Spec) -> float:
    """How far in from a tie's sides and ends parts on top of it stay, model mm.

    The weathered ties' edges are worn round; a part reaching to the edge
    would hang down over them and look wrapped around the tie.
    """
    return max(s.seat_inset - 0.1, 0.05)


PLATE_EDGE = 0.12  # of the tie width: tie left showing each side of a plate (about 1 in of 9 in)


def plate_edge(s: Spec, wt: float) -> float:
    """How far in from a tie's sides a plate stays, model mm, so the tie shows each side."""
    return max(_edge(s) + 0.1, PLATE_EDGE * wt)


def _on_tie(s: Spec, lay: Layout, tie: Tie, x0: float, x1: float, y0: float, y1: float,
            z1: float, embed: float, footing: bool = True) -> Box | None:
    """A part sitting on ``tie``, kept inside its top: the slab, and a footing under it.

    The slab sinks ``SLAB_SINK`` into the tie top. Below it the footing,
    set well in from the tie's worn sides and ends, fills the grain down to
    ``embed`` so the part joins the tie solidly without showing on its sides.
    Returns the slab (None if nothing of it is left on the tie).
    """
    wt, e = lay.tie_width, _edge(s)
    x0, x1 = max(x0, tie.x - wt / 2 + e), min(x1, tie.x + wt / 2 - e)
    y0, y1 = max(y0, tie.y0 + e), min(y1, tie.y1 - e)
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        return None
    if footing:
        _footing(s, lay, tie, x0, x1, y0, y1, embed)
    return Box(x0, x1, y0, y1, lay.tie_height - tie.lowered - SLAB_SINK, z1)


def _footing(s: Spec, lay: Layout, tie: Tie, x0: float, x1: float, y0: float, y1: float,
             embed: float) -> None:
    """Fill the tie's grain under a part, set in from the tie's worn sides and ends."""
    wt, top = lay.tie_width, lay.tie_height - tie.lowered
    i = max(s.seat_inset, _edge(s) + 0.1)
    x0, x1 = max(x0, tie.x - wt / 2 + i), min(x1, tie.x + wt / 2 - i)
    y0, y1 = max(y0, tie.y0 + i), min(y1, tie.y1 - i)
    if x1 - x0 > 1e-6 and y1 - y0 > 1e-6 and embed > SLAB_SINK:
        lay.footings.append(Box(x0, x1, y0, y1, top - embed, top - SLAB_SINK + 0.02))


def _frame(pts: np.ndarray, x: float) -> tuple[float, float]:
    """(y, heading) of a line at ``x``."""
    return g2.y_at(pts, x), g2.heading_at(pts, x)


def _merge(intervals: list[tuple[float, float]], gap: float) -> list[list[float]]:
    """Intervals sorted and joined where they overlap or are less than ``gap`` apart."""
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _plates(t: Turnout, s: Spec, lay: Layout, lines, tp: float, embed: float) -> float:
    """Tie plates (merged where rails are close) and shoulders. Returns the highest top."""
    lp, wp, bias = s.model(s.plate_length), s.model(s.plate_width), s.model(s.plate_bias)
    wt, ht = lay.tie_width, lay.tie_height
    half_foot, cs = s.foot_width / 2, s.shoulder_clearance
    ws, hs = s.model(s.shoulder_width), s.model(s.shoulder_height)
    # Plates sit on the tie top, narrower than the tie, so the tie shows each side.
    wp = min(wp, wt - 2 * plate_edge(s, wt))
    if half_foot > lp / 2 - abs(bias):
        lay.errors.append("The rail foot is wider than the tie plate allows; lengthen the plate "
                          "or reduce the field-side bias.")
        return lay.seat
    top = ht + tp
    for tie in lay.ties:
        x = tie.x
        if s.headblock_plate and lay.in_unit(x):
            continue  # the headblock plate takes the double tie's plates
        xa, xb = x - wp / 2, x + wp / 2
        spans = []
        for ln, pts in lines:
            if ln.kind == FROG and s.frog_base_plate:
                continue
            sp = g2.y_span(pts, xa, xb)
            if sp:
                b = bias * ln.field_side if ln.kind not in (FROG, GUARD) else 0.0
                spans.append((sp[0] + b - lp / 2, sp[1] + b + lp / 2))
        merged = _merge(spans, PLATE_MERGE)
        for a, b in merged:
            a, b = max(a, tie.y0), min(b, tie.y1)
            if b - a > 1e-6:
                plate = _on_tie(s, lay, tie, xa, xb, a, b, ht + tp, embed)
                if plate:
                    lay.plates.append(plate)
        if s.shoulders == SHOULDERS_NONE:
            continue
        for ln, pts in lines:
            if ln.ghost or ln.kind in (FROG, GUARD) or not ln.field_side:
                continue
            if ln.free_x and ln.free_x[0] <= x <= ln.free_x[1]:
                continue  # slide plate: no shoulders
            if not (g2.covers(pts, xa) and g2.covers(pts, xb)):
                continue
            faces = [ln.field_side] if s.shoulders == SHOULDERS_FIELD else [ln.field_side,
                                                                          -ln.field_side]
            for f in faces:
                quad = _shoulder(pts, xa, xb, f, half_foot + cs, half_foot + cs + ws)
                ys = [q[1] for q in quad]
                if not any(a - 1e-6 <= min(ys) and max(ys) <= b + 1e-6 for a, b in merged):
                    continue  # would hang off its plate
                if _crowded(lines, ln, (xa, x, xb), min(ys), max(ys), half_foot + cs):
                    continue
                lay.shoulders.append(Prism(tuple(quad), ht + tp - 0.05, ht + tp + hs))
                top = max(top, ht + tp + hs)
    return top


def _shoulder(pts, xa: float, xb: float, f: int, v_in: float, v_out: float):
    """A shoulder's outline: a band ``v_in`` to ``v_out`` off the rail on side ``f``, cut at xa, xb.

    The band follows the rail, so its long sides are parallel to it; its
    ends are square to the tie (cut at ``xa`` and ``xb``). Counter-clockwise.
    """
    (ya, ha), (yb, hb) = _frame(pts, xa), _frame(pts, xb)
    ca, cb = math.cos(ha), math.cos(hb)
    quad = [(xa, ya + f * v_in / ca), (xb, yb + f * v_in / cb),
            (xb, yb + f * v_out / cb), (xa, ya + f * v_out / ca)]
    return quad if f > 0 else [quad[0], quad[3], quad[2], quad[1]]


def _crowded(lines, own, xs, y_lo: float, y_hi: float, reach: float) -> bool:
    """True when another rail's foot (plus ``reach``) comes within y_lo..y_hi at any of ``xs``."""
    for ln, pts in lines:
        if ln.group == own.group:
            continue
        for x in xs:
            if not g2.covers(pts, x):
                continue
            y, h = _frame(pts, x)
            r = reach / max(math.cos(h), 0.2)
            if y + r > y_lo and y - r < y_hi:
                return True
    return False


def _seat_pads(s: Spec, lay: Layout, lines) -> None:
    """No plates: fill the grain flat where the rails sit, merged where rails are close."""
    half_x = lay.tie_width / 2 - s.seat_inset
    if half_x <= 0:
        return
    m = s.foot_width / 2 + s.seat_margin
    for tie in lay.ties:
        if s.headblock_plate and lay.in_unit(tie.x):
            continue  # lowered under the headblock plate
        spans = []
        for _ln, pts in lines:
            sp = g2.y_span(pts, tie.x - half_x, tie.x + half_x)
            if sp:
                spans.append((sp[0] - m, sp[1] + m))
        for a, b in _merge(spans, PLATE_MERGE):
            a, b = max(a, tie.y0), min(b, tie.y1)
            if b - a > 1e-6:
                lay.seats.append(Box(tie.x - half_x, tie.x + half_x, a, b,
                                     lay.tie_height - s.seat_depth - 0.02, lay.tie_height))


def _crossing(pts, x: float, half: float) -> tuple[float, float, float] | None:
    """Where a line crosses the tie at ``x`` (``half`` its half width): (x, y, heading), or None.

    A rail that starts or ends on the tie (the stub rails on the headblock
    tie, the closure rails at the frog) crosses it at its end.
    """
    if len(pts) < 2 or pts[-1, 0] < x - half or pts[0, 0] > x + half:
        return None
    xc = min(max(x, float(pts[0, 0])), float(pts[-1, 0]))
    y, h = _frame(pts, xc)
    return xc, y, h


def _spiked(ln, x: float) -> bool:
    """True when this rail is spiked down on the tie at ``x``."""
    if ln.ghost:
        return False
    return not (ln.free_x and ln.free_x[0] <= x <= ln.free_x[1])


def _frog_band(lines, x: float) -> tuple[float, float] | None:
    """Lowest and highest frog rail centre at ``x``, or None outside the frog."""
    ys = [g2.y_at(pts, x) for ln, pts in lines if ln.kind == FROG and g2.covers(pts, x)]
    return (min(ys), max(ys)) if ys else None


def _blocked(lines, own, px: float, py: float, half: float, s: Spec,
             y_own: float | None = None) -> bool:
    """True when a spike or hole at (px, py), ``half`` wide, lands on another rail or a solid frog.

    ``y_own`` is the spiked rail's own centre there: a rail lying in line
    with it (the movable rail ending where a fixed rail starts, at the
    headblock) is the same line of rail, not one in the way.
    """
    half_foot = s.foot_width / 2
    for ln, pts in lines:
        if not g2.covers(pts, px) or (ln.group == own.group and ln is not own):
            continue
        y, h = _frame(pts, px)
        if ln is not own and y_own is not None and abs(y - y_own) < 0.25 * half_foot:
            continue  # in line with the spiked rail: its continuation
        # Its own rail can bend away under it (guard rail flares), so check that too.
        clear = -0.02 if ln is own else SPIKE_CLEAR
        if abs(py - y) * math.cos(h) < half_foot + half + clear:
            return True
    if s.frog_solid:
        band = _frog_band(lines, px)
        if band and band[0] - half_foot - half < py < band[1] + half_foot + half:
            return True
    return False


def _bare(s: Spec, lay: Layout, index: int) -> bool:
    """True for ties left without printed spikes: the bare end ties, and between every Nth."""
    n, bare, every = len(lay.ties), max(0, int(s.spike_bare_ends)), max(1, int(s.spike_every))
    if index < bare or index >= n - bare:
        return True
    return (index - bare) % every != 0


def _holes(t: Turnout, s: Spec, lay: Layout, lines, top: float) -> None:
    """Two spike holes per spiked rail per tie, one each side of the foot, turned with the rail."""
    d = s.hole_diameter
    off = s.foot_width / 2 + s.hole_clearance + d / 2
    st = s.model(s.stagger) / 2
    wt = lay.tie_width
    off_tie = 0
    for tie in lay.ties:
        x = tie.x
        if s.headblock_plate and lay.in_unit(x):
            continue  # the headblock plate's clips hold the rails here
        for ln, pts in lines:
            cross = _crossing(pts, x, wt / 2)
            if cross is None or not _spiked(ln, x):
                continue
            xc, y, h = cross
            tu, nv = (math.cos(h), math.sin(h)), (-math.sin(h), math.cos(h))
            fs = ln.field_side or 1
            for f in (1, -1):
                along = st * f * fs
                px = xc + tu[0] * along + nv[0] * f * off
                py = y + tu[1] * along + nv[1] * f * off
                if abs(px - x) + d / 2 > wt / 2 or not tie.y0 + d / 2 <= py <= tie.y1 - d / 2:
                    off_tie += xc == x  # a rail ending on this tie just loses that hole
                    continue
                if _blocked(lines, ln, px, py, d / 2, s, y + tu[1] * along):
                    continue
                if any(math.hypot(px - h.x, py - h.y) < d + SPIKE_CLEAR for h in lay.holes[-12:]):
                    continue  # rails in line (a closure rail meeting the frog) share this hole
                lay.holes.append(Hole(px, py, d, -HOLE_EXTRA, top + HOLE_EXTRA))
    if off_tie and st > 0:
        lay.warnings.append(f"{off_tie} spike holes would fall off their ties (stagger on angled "
                            "rails) and were left out; reduce the stagger.")


def foot_under_head(s: Spec) -> float:
    """Rail foot thickness under the inner edge of a printed spike head, model mm (as Tie Strip)."""
    te, tw = s.foot_edge, s.foot_web
    run = (s.foot_width - s.web_width) / 2
    if tw <= te or s.web_width <= 0 or run <= 0:
        return te
    return te + (tw - te) * min(1.0, s.spike_overhang / run)


def foot_slope(s: Spec) -> float:
    """Rise per mm of the rail foot's top surface toward the web (0 for a flat foot)."""
    run = (s.foot_width - s.web_width) / 2
    if s.foot_web <= s.foot_edge or s.web_width <= 0 or run <= 0:
        return 0.0
    return (s.foot_web - s.foot_edge) / run


def spike_underside(s: Spec, half_foot: float):
    """The underside of a printed spike head, as in Tie Strip.

    Returns (points as (v, z) from the head's inner edge out to the shank,
    the underside height over the foot, the flat overhang left after the
    chamfer); v from the rail centreline, z above the rail seat.
    """
    o, cp, cv = s.spike_overhang, s.spike_side_clear, s.spike_top_clear
    u_tip, u_shank = half_foot - o, half_foot + cp
    z_flat = foot_under_head(s) + cv
    if not s.spike_chamfer:
        return [(u_tip, z_flat), (u_shank, z_flat)], z_flat, o + cp
    tn = math.tan(math.radians(s.spike_chamfer))
    z_edge = s.foot_edge + max(cv, cp * tn)

    def slope(u):
        """Height of the chamfer line at distance u from the rail centre."""
        return z_edge + (half_foot - u) * tn

    u_join = half_foot + (z_edge - z_flat) / tn
    if u_join <= u_tip:
        return [(u_tip, slope(u_tip)), (u_shank, slope(u_shank))], slope(u_tip), 0.0
    return ([(u_tip, z_flat), (u_join, z_flat), (u_shank, slope(u_shank))], z_flat,
            u_join - u_tip)


def _printed_spikes(t: Turnout, s: Spec, lay: Layout, lines, embed: float) -> float:
    """Printed spikes on the fixed rails, turned with each rail. Returns the top of the spikes."""
    half_foot = s.foot_width / 2
    a, o = s.spike_shank, s.spike_overhang
    cp, cv, th = s.spike_side_clear, s.spike_top_clear, s.spike_head
    web = s.web_width if s.web_width > 0 else s.head_width
    if o >= (s.foot_width - web) / 2:
        lay.errors.append("The printed spike heads reach the rail web; reduce the head overhang.")
        return lay.seat
    if s.spike_chamfer and math.tan(math.radians(s.spike_chamfer)) <= foot_slope(s):
        lay.errors.append("The chamfer under the spike heads is shallower than the rail foot's "
                          "slope; make the chamfer angle steeper.")
        return lay.seat
    u_in, u_out = half_foot + cp, half_foot + cp + a
    st = s.model(s.stagger) / 2
    seat, ht, wt = lay.seat, lay.tie_height, lay.tie_width
    z0 = ht - embed
    under, z_under, flat = spike_underside(s, half_foot)
    z_head, z_top = seat + z_under, seat + foot_under_head(s) + cv + th
    placed: list[tuple[float, float]] = []
    for index, tie in enumerate(lay.ties):
        if _bare(s, lay, index) or (s.headblock_plate and lay.in_unit(tie.x)):
            continue
        x = tie.x
        for ln, pts in lines:
            cross = _crossing(pts, x, wt / 2)
            if ln.kind == GUARD or cross is None or not _spiked(ln, x):
                continue
            xc, y, h = cross
            fs = ln.field_side or 1
            for f in (1, -1):
                along = st * f * fs
                cx, cy = xc + math.cos(h) * along, y + math.sin(h) * along
                mid = f * (u_in + u_out) / 2
                px, py = cx - math.sin(h) * mid, cy + math.cos(h) * mid
                if abs(px - x) + a / 2 > wt / 2 or not tie.y0 + a / 2 <= py <= tie.y1 - a / 2:
                    continue
                if _blocked(lines, ln, px, py, a / 2 + cp, s, cy):
                    continue
                if any(math.hypot(px - q[0], py - q[1]) < a + 2 * cp for q in placed[-12:]):
                    continue  # rails in line share this spike
                placed.append((px, py))
                lay.spikes.append(Spike(
                    cx, cy, h, -a / 2, a / 2,
                    v_head=f * (half_foot - o), v_shank_in=f * u_in, v_shank_out=f * u_out,
                    z0=z0, z_head=z_head, z_top=z_top,
                    under=tuple((f * u, seat + z) for u, z in under)))
    lay.summary.update({"head_slot": z_head - seat, "head_top": z_top - seat,
                        "flat_overhang": flat})
    if not lay.spikes:
        lay.warnings.append("No ties get printed spikes: reduce the bare end ties or spike "
                            "every Nth tie.")
    return z_top


def _headblock_hardware(t: Turnout, s: Spec, lay: Layout, lines, embed: float) -> float:
    """The headblock plates with their rail clips and throw stops. Returns the highest top.

    The headblock sits on the double tie: the long headblock tie under the
    movable rails' ends, and a standard tie right next to it under the fixed
    rails' ends.

    **Headblock plate.** On each side of the track one plate spans both ties
    of the double tie, centred on the headblock, under the straight and
    diverging rail ends (side by side, one throw apart) and the tips of the
    movable rail, which slide on it. It carries the whole headblock as one
    unit: over the fixed rails' tie an L-shaped clip runs along the outside
    of the pair and another along the inside, each with a lip over the rail
    foot like a printed spike head (same sizes and clearances), holding the
    rail ends in line; over the long tie the throw stops stand on it. With
    tie plates on, the plate is as thick as the tie plates; with them off,
    both ties are lowered by the plate's thickness so the rails sit level
    with the bare ties.

    **Throw stops.** Over the long tie each movable rail gets a block on each
    side, just clear of its foot at the two ends of its travel (lined up
    with the straight route, and thrown), so it can't be pushed past either
    route. Without the headblock plate they stand on the tie, each on its own
    bolted base. With ``stops_every_tie`` every other tie under the movable
    rails, from the heel on, gets a bolted stop on each rail's outside, set
    to the rail's travel at that tie.

    **Bolts.** With ``bolts`` on, hex bolt heads fasten the hardware to the
    ties: two per tie at each end of each headblock plate, past the clips
    and stops; and a stop on its own stands on a thin base plate reaching
    away from the rail, held by two bolts.
    """
    half_foot, wt, ht = s.foot_width / 2, lay.tie_width, lay.tie_height
    top = lay.seat
    unit = lay.unit_ties()
    if len(unit) != 2:
        return top
    long_tie, std_tie = unit
    if s.headblock_plate:
        if s.foot_edge <= 0:
            lay.errors.append("The headblock plate's clips need the rail foot thickness from "
                              "the rail profile.")
            return top
        tp = s.model(s.plate_thickness) if s.plates else long_tie.lowered
        z_plate = ht - long_tie.lowered  # the plate sits on the (lowered) ties
        seat = z_plate + tp
        gap = t.half_gap
        u0 = max(gap, std_tie.x - wt / 2) + 0.05  # clips over the fixed rails' tie
        u1 = std_tie.x + wt / 2 - plate_edge(s, wt) - 0.1  # inside the plate's end
        a, o = s.spike_shank, s.spike_overhang
        cp, cv, th = s.spike_side_clear, s.spike_top_clear, s.spike_head
        under, z_under, _flat = spike_underside(s, half_foot)
        z_head, z_top = seat + z_under, seat + foot_under_head(s) + cv + th
        stubs = []
        for ln, pts in lines:
            if ln.kind == "RUNNING" and abs(pts[0, 0] - gap) < 1e-6 and g2.covers(pts, u1):
                y, h = _frame(pts, (u0 + u1) / 2)
                stubs.append((y, h))
        stop_boxes = []
        if s.throw_stops:  # standing on the plate, over the long tie
            n0 = len(lay.stops)
            top = max(top, _throw_stops(t, s, lay, long_tie, embed, outside_only=False,
                                        z0=z_plate - SLAB_SINK))
            stop_boxes = lay.stops[n0:]
        bs, bh = s.model(s.bolt_size), s.model(s.bolt_height)
        bolt_zone = bs + 0.2 if s.bolts else 0.0  # room at each end of the plate for its bolts
        margin = max(s.plate_margin, bolt_zone)
        e = _edge(s)  # stays inside the double tie's worn edges
        pe = plate_edge(s, wt)  # and narrower than the ties, like the tie plates
        px0, px1 = long_tie.x - wt / 2 + pe, std_tie.x + wt / 2 - pe
        for sign in (1, -1):
            pair = sorted((st for st in stubs if st[0] * sign > 0), key=lambda st: abs(st[0]))
            if not pair:
                continue
            ys = [y for y, _h in pair]
            dy = max(abs(math.tan(h)) for _y, h in pair) * wt / 2
            clip = half_foot + cp + a
            lo, hi = min(ys) - clip - dy, max(ys) + clip + dy
            for b in stop_boxes:
                if (b.y0 + b.y1) / 2 * sign > 0:
                    lo, hi = min(lo, b.y0), max(hi, b.y1)
            y0 = max(lo - margin, long_tie.y0 + e, std_tie.y0 + e)
            y1 = min(hi + margin, long_tie.y1 - e, std_tie.y1 - e)
            lay.hb_plates.append(Box(px0, px1, y0, y1, z_plate - SLAB_SINK, seat))
            for tie in unit:
                _footing(s, lay, tie, px0, px1, y0, y1, embed)
            if s.bolts:  # two bolts per tie at each end of the plate, past the clips and stops
                for yb in (y0 + 0.1 + bs / 2, y1 - 0.1 - bs / 2):
                    for tie in unit:
                        for xb in (tie.x - wt / 4, tie.x + wt / 4):
                            lay.bolts.append(hex_bolt(xb, yb, bs, seat - 0.02, seat + bh))
            # Clips: inside the pair (toward the centre) and outside it.
            for (y, h), f in ((pair[0], -sign), (pair[-1], sign)):
                cx = (u0 + u1) / 2
                lay.clips.append(Spike(
                    cx, y, h, u0 - cx, u1 - cx,
                    v_head=f * (half_foot - o), v_shank_in=f * (half_foot + cp),
                    v_shank_out=f * (half_foot + cp + a), z0=seat - 0.05, z_head=z_head,
                    z_top=z_top, under=tuple((f * u, seat + z) for u, z in under)))
        top = max(top, z_top, seat + (bh if s.bolts else 0.0))
    elif s.throw_stops:
        # No headblock plate: stops both sides of each rail on the long tie, each bolted.
        top = max(top, _throw_stops(t, s, lay, long_tie, embed, outside_only=False))
    if s.throw_stops and s.stops_every_tie:
        # Every other tie under the movable rails, between the heel (where the rails
        # are spiked) and the double tie: one bolted stop, on the rail's outside.
        for tie in lay.ties:
            if -t.movable_length + 1e-6 < tie.x < long_tie.x - 1e-9:
                _throw_stops(t, s, lay, tie, embed, outside_only=True)
    return top


def _throw_stops(t: Turnout, s: Spec, lay: Layout, tie: Tie, embed: float,
                 outside_only: bool, z0: float | None = None) -> float:
    """Throw stops on ``tie``: a block each side of each movable rail. Returns their top.

    Each block is just clear of the rail foot at one end of the rail's
    travel there: lined up with the straight route, or thrown (moved over
    by the bend at this tie). With ``outside_only`` only the block on the
    rail's outside (field side) is made. Given ``z0``, the blocks stand on
    the headblock plate from there, and the plate is bolted down instead;
    otherwise, with bolts on, each block stands on a thin base plate
    reaching away from the rail, held by two bolts.
    """
    half_foot, wt, ht = s.foot_width / 2, lay.tie_width, lay.tie_height
    w = float(turnout_bend(t, tie.x))
    c, sw = s.stop_clearance, s.stop_width
    h_stop = s.stop_height if s.stop_height > 0 else max(s.foot_web, s.foot_edge, 0.2)
    z1 = lay.seat + h_stop
    on_plate = z0 is not None
    bs, bh = s.model(s.bolt_size), s.model(s.bolt_height)
    base_t = min(s.model(s.stop_plate_thickness), h_stop / 2)
    e = _edge(s)
    inset = plate_edge(s, wt) + 0.1 if on_plate else max(e, 0.1)  # on the plate: inside it
    x0, x1 = tie.x - wt / 2 + inset, tie.x + wt / 2 - inset
    for y in (t.rail_y, -t.rail_y):
        outside = 1 if y > 0 else -1  # the field side of this rail
        # (block's near face, away from the rail: -1 below the rail, +1 above it)
        for near, away in ((y - half_foot - c, -1), (y + w + half_foot + c, 1)):
            if outside_only and away != outside:
                continue  # the movable ties get a stop on the rail's outside only
            far = near + away * sw
            b0, b1 = sorted((near, far))
            if on_plate:  # standing on the headblock plate
                lay.stops.append(Box(x0, x1, max(b0, tie.y0 + e), min(b1, tie.y1 - e), z0, z1))
                continue
            block = _on_tie(s, lay, tie, x0, x1, b0, b1, z1, embed, footing=not s.bolts)
            if block is None:
                continue
            lay.stops.append(block)
            if not s.bolts:
                continue
            # A base plate reaching away from the rail, bolted to the tie. It starts
            # inside the block and stops short of the block's ends, so no faces of the
            # two coincide (touching faces don't join cleanly).
            edge = far + away * (bs + 0.2)
            lo, hi = sorted((far - away * sw / 2, edge))
            base = _on_tie(s, lay, tie, x0 + 0.05, x1 - 0.05, lo, hi, lay.seat + base_t, embed,
                           footing=False)
            if base is None:
                continue
            # Sunk a little deeper than the block, so their bottoms don't coincide.
            lay.stops.append(Box(base.x0, base.x1, base.y0, base.y1, base.z0 - 0.01, base.z1))
            _footing(s, lay, tie, x0, x1, min(b0, lo), max(b1, hi), embed)
            yb = far + away * (0.1 + bs / 2)
            for xb in (tie.x - wt / 4, tie.x + wt / 4):
                lay.bolts.append(hex_bolt(xb, yb, bs, lay.seat + base_t - 0.02,
                                          lay.seat + base_t + bh))
    return z1


def hex_bolt(x: float, y: float, across_flats: float, z0: float, z1: float) -> Prism:
    """A hex bolt head centred at (x, y), ``across_flats`` wide, from z0 to z1. Model mm."""
    r = across_flats / 2 / math.cos(math.pi / 6)
    pts = tuple((x + r * math.cos(math.pi / 3 * k), y + r * math.sin(math.pi / 3 * k))
                for k in range(6))
    return Prism(pts, z0, z1)


def turnout_bend(t: Turnout, x: float) -> float:
    """How far the thrown movable rails are moved over at ``x``."""
    from .turnout import bend
    import numpy as np
    return float(bend(t.movable_length, t.throw, np.array([x]))[0])


def _connectors(t: Turnout, s: Spec, lay: Layout) -> None:
    """Low connectors between neighbouring ties under the straight and diverging rails."""
    wc = s.connector_width if s.connector_width > 0 else s.foot_width
    hc = s.connector_height_frac * lay.tie_height
    e, wt = s.connector_overlap, lay.tie_width
    if e >= wt / 2:
        lay.errors.append("Connector overlap is more than half the tie width.")
        return
    joint = lay.split_x is not None
    if joint and s.tab_depth + s.joint_clearance > wt - 0.3:
        lay.errors.append(f"The joint tabs ({s.tab_depth:.2f} mm plus {s.joint_clearance:.2f} mm "
                          f"clearance) are too deep for {wt:.2f} mm wide ties; make them shorter.")
        return
    for a, b in zip(lay.ties, lay.ties[1:]):
        x0, x1 = a.x + wt / 2 - e, b.x - wt / 2 + e
        is_joint = joint and a.x < lay.split_x < b.x
        if is_joint:
            x1 = b.x - wt / 2 + s.tab_depth
        done: list[tuple[float, float]] = []
        for pts in t.connector_lines:
            if not (g2.covers(pts, x0) and g2.covers(pts, x1)):
                continue
            (y0, h0), (y1, h1) = _frame(pts, x0), _frame(pts, x1)
            if any(abs(y0 - p) < wc and abs(y1 - q) < wc for p, q in done):
                continue  # too close to a connector already there
            done.append((y0, y1))
            w0, w1 = wc / 2 / math.cos(h0), wc / 2 / math.cos(h1)
            quad = ((x0, y0 - w0), (x1, y1 - w1), (x1, y1 + w1), (x0, y0 + w0))
            if not is_joint:
                lay.connectors.append(Prism(quad, 0.0, hc))
                continue
            # A tab on the movable piece reaching into a socket in the fixed piece's tie.
            c = s.joint_clearance
            lay.tabs.append(Prism(quad, 0.0, hc))
            sx0, sx1 = b.x - wt / 2 - 0.5, x1 + c
            lay.sockets.append(Prism(((sx0, y0 - w0 - c), (sx1, y1 - w1 - c),
                                      (sx1, y1 + w1 + c), (sx0, y0 + w0 + c)), -1.0, hc + c))
    if joint and len(lay.tabs) < 2:
        lay.warnings.append("The pieces are joined by fewer than two tabs, so they may not "
                            "line up well.")


# Smallest printable features, model mm, by printer (as Tie Strip).
DEFAULT_THRESHOLDS = {
    "RESIN": {"hole": 0.3, "plate": 0.05, "connector": 0.4, "gap": 0.3, "shoulder": 0.05},
    "FDM": {"hole": 0.6, "plate": 0.2, "connector": 0.8, "gap": 0.5, "shoulder": 0.2},
}


def printability(s: Spec, lay: Layout, printer: str,
                 thresholds: dict[str, float] | None = None) -> list[str]:
    """Warnings for features likely too small to print on ``printer``."""
    th = thresholds or DEFAULT_THRESHOLDS.get(printer, DEFAULT_THRESHOLDS["RESIN"])
    name = "resin" if printer == "RESIN" else "FDM"
    out = []
    if not lay.summary:
        return out
    if s.fastening == PRINTED:
        if s.spike_shank < th["connector"]:
            out.append(f"Printed spike shanks ({s.spike_shank:.2f} mm) are thinner than "
                       f"{th['connector']:.2f} mm and may not print on {name}.")
        if min(s.spike_head, s.spike_overhang) < th["shoulder"]:
            out.append(f"Printed spike heads are under {th['shoulder']:.2f} mm and may not print "
                       f"on {name}.")
    elif s.fastening == HOLES and s.hole_diameter < th["hole"]:
        out.append(f"Spike holes ({s.hole_diameter:.2f} mm) are smaller than {th['hole']:.2f} mm, "
                   f"the smallest hole a {name} printer is set to print.")
    wc, hc = lay.summary["connector_width"], lay.summary["connector_height"]
    if min(wc, hc) < th["connector"]:
        out.append(f"Connectors ({wc:.2f} x {hc:.2f} mm) are thinner than {th['connector']:.2f} mm "
                   f"and may not print on {name}.")
    if lay.summary["gap"] < th["gap"]:
        out.append(f"The gap between ties ({lay.summary['gap']:.2f} mm) is under "
                   f"{th['gap']:.2f} mm and may fill in on {name}.")
    if lay.bolts and min(s.model(s.bolt_size), s.model(s.bolt_height)) < th["shoulder"]:
        out.append(f"The bolt heads are under {th['shoulder']:.2f} mm and may not print on {name}.")
    if s.plates:
        tp = s.model(s.plate_thickness)
        if tp < th["plate"]:
            out.append(f"Tie plates ({tp:.3f} mm thick) are thinner than {th['plate']:.2f} mm "
                       f"and may not show on {name}.")
        if s.shoulders != SHOULDERS_NONE and min(s.model(s.shoulder_height),
                                                 s.model(s.shoulder_width)) < th["shoulder"]:
            out.append(f"Plate shoulders are under {th['shoulder']:.2f} mm and may not print "
                       f"on {name}.")
    return out


def grain_warning(top_cut: float, tie_height: float, preset: str, limit_pct: float) -> str:
    """The grain-too-deep warning, or "" when the cut is within the limit."""
    if tie_height <= 0:
        return ""
    pct = 100.0 * top_cut / tie_height
    if pct <= limit_pct:
        return ""
    return (f'Grain on "{preset}" cuts {top_cut:.2f} mm into a {tie_height:.2f} mm tie '
            f"({pct:.0f} %). To make it shallower, lower Depth or turn off Auto Detail on the "
            "template tie, then regenerate.")
