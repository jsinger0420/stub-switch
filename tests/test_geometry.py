"""Tests for the plain-Python parts: polylines, turnout geometry, tie layout and mesh shapes.

Run from the STUB SWITCH folder (no Blender needed):

    python -m unittest discover -s tests -t .

The last test class also uses the Switch Frog and Model Rail add-ons from the
sibling SWITCH FROG and RAIL folders when they are there.
"""

import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stub_switch import geom2d as g2  # noqa: E402
from stub_switch import layout, meshgen, turnout  # noqa: E402
from stub_switch.layout import Spec  # noqa: E402
from stub_switch.turnout import TurnoutSpec  # noqa: E402

IN = 25.4
N = 87.1


def ho_turnout(**kw) -> TurnoutSpec:
    """An HO #6 on code 83 rail, with frog lengths like Switch Frog's HO #6 Code 83 preset."""
    base = dict(scale_n=N, gauge=16.5, head_width=0.97, foot_width=1.855, frog_number=6.0,
                frog_toe=11.5, frog_heel=23.1, frog_point=1.8, flangeway=1.27,
                movable_length=216 * IN)
    base.update(kw)
    return TurnoutSpec(**base)


def ho_ties(**kw) -> Spec:
    """8'6\" x 9\" x 7\" ties at 20 in on HO code 83."""
    base = dict(scale_n=N, tie_length=102 * IN, tie_width=9 * IN, tie_height=7 * IN,
                spacing=20 * IN, foot_width=1.855, head_width=0.97, foot_edge=0.17,
                foot_web=0.36, web_width=0.42)
    base.update(kw)
    return Spec(**base)


def line(t, name):
    """The turnout's rail line called ``name``."""
    return next(ln for ln in t.lines if ln.name == name)


class TestGeom2d(unittest.TestCase):
    """Arcs, offsets and lookups by X."""

    def test_arc_radius_and_headings(self):
        """Every arc point is one radius from the centre, and the arc ends at the end heading."""
        a = g2.arc((0.0, 0.0), 0.1, 0.5, 100.0, step=1.0)
        cx, cy = -100 * math.sin(0.1), 100 * math.cos(0.1)
        r = np.hypot(a[:, 0] - cx, a[:, 1] - cy)
        self.assertTrue(np.allclose(r, 100.0))
        self.assertAlmostEqual(g2.heading_at(a, a[-1, 0] - 1e-6), 0.5, delta=0.01)

    def test_offset_keeps_distance(self):
        """An offset straight line stays exactly that far away."""
        p = g2.as_poly([(0, 0), (10, 0), (20, 5)])
        o = g2.offset(p, 2.0)
        self.assertAlmostEqual(o[0, 1], 2.0)
        a, b = p[2] - p[1], o[2] - p[1]
        d = abs(a[0] * b[1] - a[1] * b[0]) / np.linalg.norm(a)
        self.assertAlmostEqual(d, 2.0, places=9)

    def test_clip_and_lookup(self):
        """clip_x cuts a line to an X range; y_at is NaN outside it."""
        p = g2.as_poly([(0, 0), (10, 10)])
        c = g2.clip_x(p, 2, 5)
        self.assertAlmostEqual(c[0, 0], 2)
        self.assertAlmostEqual(c[-1, 1], 5)
        self.assertTrue(math.isnan(g2.y_at(p, 11)))


class TestTurnout(unittest.TestCase):
    """The stub switch's rail geometry."""

    def setUp(self):
        """An HO #6 turnout."""
        self.s = ho_turnout()
        self.t = turnout.compute(self.s)
        self.assertTrue(self.t.ok, self.t.errors)

    def test_frog_point_on_left_gauge_line(self):
        """The TP is where the inner diverging gauge line meets the straight left gauge line."""
        self.assertAlmostEqual(self.t.tp[1], 16.5 / 2, places=6)
        self.assertGreater(self.t.tp[0], 0)

    def test_switch_angle_from_bend(self):
        """The switch angle is atan(1.5 throw / movable length), less than the frog angle."""
        t = self.t
        self.assertAlmostEqual(t.throw, 1.855 + turnout.THROW_CLEAR)
        self.assertAlmostEqual(t.switch_angle, math.atan(1.5 * t.throw / t.movable_length))
        self.assertLess(t.switch_angle, t.frog_angle)
        self.assertAlmostEqual(math.degrees(t.frog_angle), 9.527, places=3)

    def test_thrown_rail_meets_diverging_rails(self):
        """Thrown, the movable rails end one throw over, in line with the fixed diverging rails."""
        t = self.t
        ml = line(t, "Movable L thrown").pts
        self.assertAlmostEqual(ml[-1, 1] - t.rail_y, t.throw, places=2)
        self.assertAlmostEqual(g2.y_at(line(t, "Outer L").pts, 0.05), ml[-1, 1], delta=0.05)
        mr = line(t, "Movable R thrown").pts
        self.assertAlmostEqual(g2.y_at(line(t, "Closure R").pts, 0.05), mr[-1, 1], delta=0.05)
        bend = turnout.bend(t.movable_length, t.throw, np.array([-t.movable_length, 0.0]))
        self.assertAlmostEqual(bend[0], 0.0)
        self.assertAlmostEqual(bend[1], t.throw)

    def test_diverging_route_keeps_gauge(self):
        """The two diverging rails stay one gauge apart along the lead curve and past the frog."""
        t = self.t
        inner, outer = line(t, "Closure R").pts, line(t, "Outer L").pts
        for x in (10.0, 60.0, 100.0):
            yi, yo = g2.y_at(inner, x), g2.y_at(outer, x)
            h = g2.heading_at(inner, x)
            self.assertAlmostEqual((yo - yi) * math.cos(h), 16.5 + 0.97, delta=0.02)
        far = line(t, "Diverging R").pts
        x = t.frog_heel_x + 10
        self.assertAlmostEqual(g2.heading_at(far, x), t.frog_angle, places=6)

    def test_frog_lines_placed(self):
        """Frog rails turned onto the turnout: the right-hand frog route lies on the straight route."""
        tt = math.tan(turnout.compute(ho_turnout()).frog_angle / 2)
        s = ho_turnout(frog_lines=[([(1.8 * tt, 1.8), (23 * tt, 23.0)], 1)])
        t = turnout.compute(s)
        fl = next(ln for ln in t.lines if ln.kind == turnout.FROG).pts
        self.assertTrue(np.allclose(fl[:, 1], t.rail_y))  # the straight point rail
        self.assertAlmostEqual(fl[0, 0], t.tp[0] + 1.8 / math.cos(t.frog_angle / 2), places=6)

    def test_guard_rails_one_flangeway_in(self):
        """Guard rails sit a flangeway plus half a head inside their running rails."""
        t = self.t
        gr = line(t, "Guard R").pts
        mid = gr[len(gr) // 2]
        self.assertAlmostEqual(mid[1], -16.5 / 2 + 1.27 + 0.97 / 2, places=6)

    def test_guard_rails_inside_frog_and_bent_in(self):
        """By default the frog reaches a foot past each guard rail end, and the ends bend inward."""
        t = self.t
        u0, u1 = t.guard_span
        self.assertAlmostEqual(u0, -11.5 + 12 * IN / N)
        self.assertAlmostEqual(u1, 23.1 - 12 * IN / N)
        gr = line(t, "Guard R").pts
        self.assertAlmostEqual(gr[0, 0], t.tp[0] + u0)
        mid_y = -16.5 / 2 + 1.27 + 0.97 / 2
        bend = 18 * IN / N * math.tan(math.radians(15))
        self.assertAlmostEqual(gr[0, 1], mid_y + bend, places=6)  # toward the track centre (+Y)
        self.assertAlmostEqual(gr[-1, 1], mid_y + bend, places=6)
        fixed = turnout.compute(ho_turnout(guard_mode="LENGTH", guard_length=72 * IN))
        g0, g1 = fixed.guard_span
        self.assertAlmostEqual(g1 - g0, 72 * IN / N)

    def test_frog_heel_rails(self):
        """Short rails as long as the guard rails leave the frog's heel; the route carries on after."""
        t = self.t
        g0, g1 = t.guard_span
        for heel, rest in (("Frog Heel L", "Straight L"), ("Frog Heel R", "Diverging R")):
            pts = t.rails[heel]
            self.assertAlmostEqual(g2.lengths(pts)[-1], g1 - g0, places=4)
            self.assertTrue(np.allclose(pts[-1], t.rails[rest][0]))
        self.assertAlmostEqual(t.rails["Frog Heel L"][0, 0], t.frog_heel_x)
        off = turnout.compute(ho_turnout(heel_rails=False))
        self.assertNotIn("Frog Heel L", off.rails)

    def test_errors(self):
        """Impossible turnouts are reported, not built."""
        self.assertFalse(turnout.compute(ho_turnout(movable_length=24.0)).ok)  # angle too big
        self.assertFalse(turnout.compute(ho_turnout(frog_toe=200.0)).ok)
        self.assertFalse(turnout.compute(ho_turnout(frog_error="no frog")).ok)


class TestLayout(unittest.TestCase):
    """Ties, plates, spikes and connectors under the turnout."""

    def setUp(self):
        """The HO #6 turnout with plates and staggered spike holes."""
        self.t = turnout.compute(ho_turnout())
        self.s = ho_ties(plates=True, stagger=2 * IN)
        self.lay = layout.compute(self.t, self.s)
        self.assertTrue(self.lay.ok, self.lay.errors)

    def test_tie_positions(self):
        """A tie on the headblock, the set spacing, approach ties before the heel, tail past the frog."""
        lay, t = self.lay, self.t
        xs = lay.tie_x
        p = 20 * IN / N
        self.assertIn(0.0, [round(x, 9) for x in xs])
        wt = 9 * IN / N
        i = xs.index(min(xs, key=abs))
        self.assertAlmostEqual(xs[i] - xs[i - 1], 2 * wt)  # headblock pair: one tie width apart
        d = np.diff(xs)
        self.assertTrue(np.allclose(np.delete(d, i - 1), p))
        gap = layout.compute(self.t, ho_ties(headblock_tie_gap=4 * IN)).tie_x
        j = gap.index(min(gap, key=abs))
        self.assertAlmostEqual(gap[j] - gap[j - 1], wt + 4 * IN / N)
        heel_ties = [x for x in xs if x <= -t.movable_length + 1e-9]
        self.assertEqual(len(heel_ties), self.s.approach_ties + 1)
        self.assertEqual(len([x for x in xs if x > t.frog_heel_x]), self.s.tail_ties)

    def test_tie_lengths(self):
        """Ties line up on the straight side and grow in whole steps toward the diverging side."""
        lay = self.lay
        lt = 102 * IN / N
        step = 6 * IN / N
        for tie in lay.ties:
            if tie.headblock:
                continue
            self.assertAlmostEqual(tie.y0, -lt / 2, places=9)
            k = (tie.length - lt) / step
            self.assertAlmostEqual(k, round(k), places=6)
        self.assertGreater(lay.ties[-1].length, lay.ties[0].length)
        hb = [tie for tie in lay.ties if tie.headblock]
        self.assertEqual(len(hb), 2)
        self.assertAlmostEqual(hb[0].y0, -lt / 2 - 36 * IN / N, places=9)

    def test_every_rail_on_its_ties(self):
        """Each tie reaches a standard overhang past the outermost rail it carries."""
        lay, t = self.lay, self.t
        over = 102 * IN / N / 2 - t.rail_y
        outer = line(t, "Outer L").pts
        for tie in lay.ties:
            y = g2.y_span(outer, tie.x - lay.tie_width / 2, tie.x + lay.tie_width / 2)
            if y:
                self.assertGreaterEqual(tie.y1 + 1e-9, y[1] + over)

    def test_no_spikes_on_movable_rails(self):
        """Between the heel and the headblock only the... nothing is spiked to the movable rails."""
        lay, t = self.lay, self.t
        free = [h for h in lay.holes if -t.movable_length + 1.5 < h.x < -1.5]
        self.assertEqual(free, [])
        self.assertTrue(any(h.x < -t.movable_length for h in lay.holes))

    def test_holes_clear_of_rails(self):
        """No spike hole lands on a rail foot."""
        lay, t = self.lay, self.t
        half = 1.855 / 2
        for h in lay.holes:
            for ln in t.lines:
                if ln.ghost or not g2.covers(ln.pts, h.x):
                    continue
                y, hd = g2.y_at(ln.pts, h.x), g2.heading_at(ln.pts, h.x)
                self.assertGreater(abs(h.y - y) * math.cos(hd), half + h.d / 2 - 0.01, ln.name)

    def test_holes_never_overlap(self):
        """Rails meeting in line (closure rail and frog) never get two overlapping holes."""
        for kw in ({}, {"headblock_plate": False}, {"stagger": 0.0}):
            lay = layout.compute(self.t, ho_ties(stagger=2 * IN, **kw) if "stagger" not in kw
                                 else ho_ties(**kw))
            hs = lay.holes
            for i, a in enumerate(hs):
                for b in hs[i + 1:]:
                    self.assertGreaterEqual(math.hypot(a.x - b.x, a.y - b.y), a.d, (a, b))

    def test_plates_merge_and_stay_on_ties(self):
        """Plates never overlap on a tie and never hang off its ends."""
        lay = self.lay
        for tie in lay.ties:
            mine = sorted((b for b in lay.plates if abs((b.x0 + b.x1) / 2 - tie.x) < 1e-6),
                          key=lambda b: b.y0)
            for a, b in zip(mine, mine[1:]):
                self.assertGreater(b.y0, a.y1)
            for b in mine:
                self.assertGreaterEqual(b.y0, tie.y0 - 1e-9)
                self.assertLessEqual(b.y1, tie.y1 + 1e-9)
        self.assertTrue(lay.shoulders)

    def test_connectors_join_every_gap(self):
        """At least the two straight-route connectors bridge every gap between ties."""
        lay = self.lay
        for a, b in zip(lay.ties, lay.ties[1:]):
            here = [c for c in lay.connectors + lay.tabs if a.x < c.outline[0][0] < b.x]
            self.assertGreaterEqual(len(here), 2)

    def test_two_piece_joint(self):
        """Split before the headblock tie: two tabs reach into sockets in the headblock tie."""
        lay = self.lay
        wt = lay.tie_width
        hb = next(t for t in lay.ties if abs(t.x) < 1e-9)
        before = max(t.x for t in lay.ties if t.x < 0)
        self.assertAlmostEqual(lay.split_x, before / 2)
        self.assertEqual(len(lay.tabs), 2)
        self.assertEqual(len(lay.sockets), 2)
        for tab, sock in zip(lay.tabs, lay.sockets):
            tx = [p[0] for p in tab.outline]
            sx = [p[0] for p in sock.outline]
            self.assertAlmostEqual(max(tx), hb.x - wt / 2 + 1.0)  # 1 mm into the headblock tie
            self.assertAlmostEqual(max(sx), max(tx) + 0.1)  # with clearance
            self.assertLess(min(sx), hb.x - wt / 2)  # open to the gap
            self.assertLess(min(p[1] for p in sock.outline), min(p[1] for p in tab.outline))
            self.assertLess(sock.z0, 0)  # open at the bottom
        pair = layout.compute(self.t, ho_ties(split_at="PAIR"))
        self.assertLess(pair.split_x, before)
        whole = layout.compute(self.t, ho_ties(split=False))
        self.assertIsNone(whole.split_x)
        self.assertEqual(whole.tabs, [])
        self.assertFalse(layout.compute(self.t, ho_ties(tab_depth=2.5)).ok)

    def test_printed_spikes(self):
        """Printed spikes are turned with their rail and skip the movable rails."""
        s = ho_ties(fastening=layout.PRINTED, foot_edge=0.17, foot_web=0.36, web_width=0.42)
        lay = layout.compute(self.t, s)
        self.assertTrue(lay.ok, lay.errors)
        self.assertTrue(lay.spikes)
        self.assertTrue(any(abs(sp.angle) > 0.05 for sp in lay.spikes))
        v, tris = meshgen.spikes(lay.spikes)
        self.assertEqual(meshgen.open_edges(tris), 0)
        self.assertGreater(meshgen.signed_volume(v, tris), 0)

    def test_inner_rail_spiked_where_fixed_rails_meet(self):
        """Just past the headblock, both rails of each side-by-side pair get spike holes."""
        lay = layout.compute(self.t, ho_ties(headblock_plate=False, stagger=2 * IN))
        on_hb = sorted(h.y for h in lay.holes if abs(h.x) < lay.tie_width / 2)
        self.assertEqual(len(on_hb), 4)  # outside and inside of each pair (they touch between)
        yr = self.t.rail_y
        self.assertTrue(any(yr - 1.5 < y < yr for y in on_hb))  # inner rail, gauge side

    def test_headblock_plate_and_stops(self):
        """Headblock plates with four clips; stops either side of each movable rail's travel."""
        t, lay = self.t, layout.compute(self.t, ho_ties())
        ht = 7 * IN / N
        tp = 0.75 * IN / N
        hb = next(tie for tie in lay.ties if abs(tie.x) < 1e-9)
        self.assertAlmostEqual(hb.lowered, tp)  # no tie plates: the tie is made thinner
        self.assertEqual(len(lay.hb_plates), 2)
        for b in lay.hb_plates:
            self.assertAlmostEqual(b.z1, ht)  # plate top level with the other ties' tops
        self.assertEqual(len(lay.clips), 4)
        self.assertTrue(all(c.u0 + c.cx > 0 for c in lay.clips))  # on the fixed half only
        self.assertFalse([h for h in lay.holes if abs(h.x) < lay.tie_width / 2])
        self.assertEqual(len(lay.stops), 8)  # four stop blocks, each on a bolted base
        stop_tie = max(tie.x for tie in lay.ties if tie.x < 0)
        w = layout.turnout_bend(t, stop_tie)
        blocks = [b for b in lay.stops if b.z1 > lay.seat + 0.3]
        left = sorted((b for b in blocks if b.y0 > 0), key=lambda b: b.y0)
        half = 1.855 / 2
        self.assertAlmostEqual(left[0].y1, t.rail_y - half - 0.15)
        self.assertAlmostEqual(left[1].y0, t.rail_y + w + half + 0.15)
        # Bolts: two at each end of each headblock plate, two on each stop's base.
        self.assertEqual(len(lay.bolts), 2 * 4 + 4 * 2)
        bs = 1.5 * IN / N
        for b in lay.bolts:
            self.assertEqual(len(b.outline), 6)
            xs = [p[0] for p in b.outline]
            self.assertAlmostEqual(max(xs) - min(xs), 2 * bs / 2 / math.cos(math.pi / 6))
        for plate in lay.hb_plates:
            on = [b for b in lay.bolts if plate.y0 <= sum(p[1] for p in b.outline) / 6 <= plate.y1
                  and plate.x0 <= sum(p[0] for p in b.outline) / 6 <= plate.x1]
            self.assertEqual(len(on), 4)
            for b in on:
                self.assertAlmostEqual(b.z0, plate.z1 - 0.02)
        for c in lay.clips:  # bolts stay clear of the clips
            for b in lay.bolts[:8]:
                by = sum(p[1] for p in b.outline) / 6
                self.assertGreater(abs(by - c.cy), abs(c.v_shank_out))
        nobolts = layout.compute(self.t, ho_ties(bolts=False))
        self.assertEqual((nobolts.bolts, len(nobolts.stops)), ([], 4))
        plated = layout.compute(self.t, ho_ties(plates=True))
        self.assertEqual(next(tie for tie in plated.ties if abs(tie.x) < 1e-9).lowered, 0.0)
        self.assertAlmostEqual(plated.hb_plates[0].z1, plated.seat)
        none = layout.compute(self.t, ho_ties(headblock_plate=False, throw_stops=False))
        self.assertEqual((none.hb_plates, none.clips, none.stops), ([], [], []))

    def test_overlapping_ties(self):
        """Spacing no more than the tie width is an error."""
        lay = layout.compute(self.t, ho_ties(spacing=8 * IN))
        self.assertFalse(lay.ok)


class TestMeshes(unittest.TestCase):
    """Closed, outward-facing shapes."""

    def test_prisms_and_mirror(self):
        """Prisms are watertight; mirroring keeps them outward-facing."""
        lay = layout.compute(turnout.compute(ho_turnout()), ho_ties(plates=True))
        for mesh in (meshgen.prisms(lay.connectors), meshgen.prisms(lay.shoulders),
                     meshgen.boxes(lay.plates), meshgen.cylinders(lay.holes)):
            v, t = mesh
            self.assertEqual(meshgen.open_edges(t), 0)
            self.assertGreater(meshgen.signed_volume(v, t), 0)
            mv, mt = meshgen.mirror_y(mesh)
            self.assertGreater(meshgen.signed_volume(mv, mt), 0)


RAIL_DIR = os.path.join(os.path.dirname(ROOT), "RAIL")
FROG_DIR = os.path.join(os.path.dirname(ROOT), "SWITCH FROG")


@unittest.skipUnless(os.path.isdir(RAIL_DIR) and os.path.isdir(FROG_DIR),
                     "needs the RAIL and SWITCH FROG folders next to this one")
class TestWithFrogPresets(unittest.TestCase):
    """Every built-in frog preset makes a turnout."""

    @classmethod
    def setUpClass(cls):
        """Load the frog and rail add-ons' APIs, as their register() would."""
        for p in (RAIL_DIR, FROG_DIR):
            if p not in sys.path:
                sys.path.insert(0, p)
        from model_rail_generator import api as rail
        sys.modules["model_rail_api"] = rail
        from switch_frog import api as frog
        sys.modules["switch_frog_api"] = frog
        cls.frog = frog

    def test_builtin_presets(self):
        """Each built-in frog preset gives a valid turnout with a sensible lead."""
        from stub_switch import frog_bridge, scales
        for name in self.frog.list_builtin_presets():
            info, err = frog_bridge.frog_info(name)
            self.assertIsNotNone(info, err)
            n = scales.scale_n(info.scale, 87.1)
            gauge = scales.standard_gauge(info.scale)
            p = info.profile
            ts = TurnoutSpec(scale_n=n, gauge=gauge, head_width=p.head_width,
                             foot_width=p.base_width, frog_number=info.number,
                             frog_toe=info.toe, frog_heel=info.heel, frog_point=info.point,
                             flangeway=info.flangeway, movable_length=216 * IN,
                             frog_lines=info.lines)
            t = turnout.compute(ts)
            self.assertTrue(t.ok, (name, t.errors))
            # A turnout's lead is a few times the gauge times the frog number.
            self.assertTrue(0.8 < t.tp[0] / (gauge * info.number) < 3.0, (name, t.tp))
            lay = layout.compute(t, Spec(scale_n=n, tie_length=102 * IN, tie_width=9 * IN,
                                         tie_height=7 * IN, spacing=20 * IN,
                                         foot_width=p.base_width, head_width=p.head_width,
                                         foot_edge=p.base_edge_thickness,
                                         foot_web=p.base_thickness, web_width=p.web_thickness,
                                         frog_solid=info.solid))
            self.assertTrue(lay.ok, (name, lay.errors))


if __name__ == "__main__":
    unittest.main()
