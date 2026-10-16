"""All Stub Switch settings, kept on the scene (``scene.stub_switch``) so they save with the .blend.

Prototype sizes (movable rail and guard rail lengths, tie spacing, tie
length steps, variation, stagger, tie plates) are in the units chosen by
``proto_units``, inches by default. The gauge, throw, gaps, holes,
clearances and spike sizes are model millimetres. Rail sizes are not
settings: they come from the frog preset's rail profile.
"""

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)

from . import frog_bridge, scales, wb_bridge
from .layout import Spec
from .plates import PLATE_KEYS
from .turnout import TurnoutSpec

PROTO_LENGTH_KEYS = (
    "movable_length", "guard_length", "guard_frog_margin", "guard_flare_length",
    "tie_spacing", "length_step", "headblock_extra", "headblock_tie_gap", "double_tie_gap",
    "length_jitter", "end_jitter", "stagger",
    "plate_length", "plate_width", "plate_thickness", "plate_bias",
    "shoulder_height", "shoulder_width", "headblock_plate_thickness",
    "bolt_size", "bolt_height",
)

_quiet = False


class quiet:
    """Context manager: suppress update callbacks while writing settings."""

    def __enter__(self):
        """Turn updates off, remembering the previous state so blocks can nest."""
        global _quiet
        self._prev, _quiet = _quiet, True

    def __exit__(self, *exc):
        """Put updates back as they were."""
        global _quiet
        _quiet = self._prev


def _changed(self, context):
    """Mark the chosen switch preset as modified when any setting is edited."""
    if not _quiet and self.switch_preset:
        self.switch_modified = True


def _scale_update(self, context):
    """Set the gauge to the new scale's standard gauge (custom scales keep theirs)."""
    if _quiet:
        return
    gauge = scales.standard_gauge(self.scale)
    if gauge is not None:
        self.gauge = gauge
    _changed(self, context)


def _units_update(self, context):
    """Convert every prototype length when the units change."""
    if _quiet or self.proto_units == self.proto_units_prev:
        return
    with quiet():
        for key in PROTO_LENGTH_KEYS:
            mm = scales.to_full_mm(getattr(self, key), self.proto_units_prev)
            setattr(self, key, scales.from_full_mm(mm, self.proto_units))
        self.proto_units_prev = self.proto_units


def _plate_update(self, context):
    """Mark the chosen plate preset (and the switch preset) as modified."""
    if not _quiet:
        if self.plate_preset:
            self.plate_modified = True
        _changed(self, context)


def _poll_board(self, obj):
    """Only Weathered Board boards can be the template tie."""
    return wb_bridge.is_board(obj)


def _proto(name, default, desc, update=None, soft_max=1000.0):
    """A prototype length property, in the units chosen by ``proto_units``."""
    return FloatProperty(name=name, description=desc + " (prototype size, in the chosen units)",
                         default=default, min=0.0, soft_max=soft_max, precision=3,
                         update=update or _changed)


def _model(name, default, desc, update=None):
    """A model-millimetre length property."""
    return FloatProperty(name=name, description=desc + " (model millimetres)",
                         default=default, min=0.0, soft_max=50.0, precision=3, step=1,
                         update=update or _changed)


class STUBSWITCH_Settings(bpy.types.PropertyGroup):
    """Every Stub Switch setting, stored on the scene as ``scene.stub_switch``."""

    # ---- frog, scale and track ----
    frog_preset: StringProperty(
        name="Frog Preset", default="", update=_changed,
        description="Switch Frog Generator preset: sets the frog number (the turnout's angle), "
                    "the flangeway, and the rail profile used for every rail")
    scale: EnumProperty(
        name="Scale", default="HO", update=_scale_update,
        description="Model railroad scale; sets the size ratio and pre-fills the standard gauge. "
                    "Choosing a frog preset sets it to the frog's scale",
        items=[(k, v[0], f"1:{v[1]:g}, standard gauge {v[2]:g} mm") for k, v in scales.SCALES.items()]
        + [(scales.CUSTOM, "Custom", "Enter your own ratio")])
    scale_custom: FloatProperty(name="Ratio 1:", default=87.1, min=1.0, soft_max=500.0,
                                description="N in 1:N for a custom scale", update=_changed)
    gauge: _model("Gauge", 16.5, "Distance between the inner faces of the railheads")
    hand: EnumProperty(
        name="Hand", default="LEFT", update=_changed,
        description="Which way the diverging route turns, looking from the headblock end",
        items=[("LEFT", "Left Hand", "The diverging route turns left"),
               ("RIGHT", "Right Hand", "The diverging route turns right")])
    movable_length: _proto(
        "Movable Rail Length", 216.0,
        "Length of the free part of the movable rails, from where they are last spiked (the "
        "heel) to the headblock. Prototype stub switches used about 15 to 24 ft. Longer rails "
        "bend more gently, giving a smaller switch angle and a longer turnout")
    throw_auto: BoolProperty(
        name="Auto Throw", default=True, update=_changed,
        description="Set the throw to the rail foot width plus a small clearance, so the "
                    "straight and diverging rail ends sit side by side at the headblock")
    throw: _model("Throw", 2.1, "How far the movable rails move sideways at the headblock")
    headblock_gap: _model("Headblock Gap", 0.1,
                          "Gap between the ends of the movable rails and the fixed rails at "
                          "the headblock")
    points_set: EnumProperty(
        name="Set For", default="STRAIGHT", update=_changed,
        description="Which route the movable rails are drawn lined up with (Include Rail)",
        items=[("STRAIGHT", "Straight", "Movable rails lined up with the straight route"),
               ("DIVERGING", "Diverging", "Movable rails bent to the diverging route")])
    guard_rails: BoolProperty(
        name="Guard Rails", default=True, update=_changed,
        description="Guard rails opposite the frog, one flangeway inside the running rails, on "
                    "both routes. They get tie plates and spikes, and rail objects with Include Rail")
    split: BoolProperty(
        name="Two Pieces", default=True, update=_changed,
        description="Print the tie strip in two pieces, the movable rail section and the fixed "
                    "rail section, joined by tabs that fit sockets so they line up for gluing")
    split_at: EnumProperty(
        name="Split", default="HEADBLOCK", update=_changed,
        description="Where the two pieces meet",
        items=[("HEADBLOCK", "Before Double Tie", "The double tie at the headblock goes with "
                                                    "the fixed piece, the tie before it with the "
                                                    "movable"),
               ("PAIR", "Before Headblock Pair", "Both headblock ties go with the fixed piece")])
    tab_depth: _model("Tab Depth", 1.0, "How far each joint tab reaches into the fixed piece's tie")
    joint_clearance: _model("Joint Clearance", 0.1,
                            "Play around each tab in its socket, for glue and printer tolerance")
    heel_rails: BoolProperty(
        name="Frog Heel Rails", default=True, update=_changed,
        description="With Include Rail, start each route leaving the frog's heel with a short "
                    "rail as long as the guard rails, so it can be laid with the frog")
    guard_mode: EnumProperty(
        name="Guard Rail Length", default="FROG", update=_changed,
        description="How long the guard rails are",
        items=[("FROG", "From Frog", "A little shorter than the frog: the frog reaches past "
                                     "each end of the guard rail by the amount below"),
               ("LENGTH", "Custom", "A length you enter, centred opposite the frog's point")])
    guard_frog_margin: _proto("Frog Past Guard Rail", 12.0,
                              "How far the frog reaches past each end of the guard rails")
    guard_length: _proto("Guard Rail Length", 72.0, "Overall length of each guard rail")
    guard_flare_length: _proto("Bend Length", 18.0,
                               "Length of the bent end at each end of a guard rail, which bends "
                               "in toward the middle of the track")
    guard_flare_angle: FloatProperty(
        name="Bend Angle", default=15.0, min=0.0, max=45.0, precision=1, update=_changed,
        description="Angle at which each guard rail end bends in toward the middle of the track")

    # ---- template tie (Weathered Board) ----
    tie_source: EnumProperty(
        name="Template Tie", default="OBJECT", update=_changed,
        description="Where the ties' look, width and thickness come from",
        items=[("OBJECT", "Board Object", "A board you made with the Weathered Board panel, "
                                          "sized as a standard tie"),
               ("PRESET", "Board Preset", "A saved Weathered Board preset")])
    tie_object: PointerProperty(
        name="Template Tie", type=bpy.types.Object, poll=_poll_board, update=_changed,
        description="A board made with Weathered Board's Add Board: its look, width and "
                    "thickness are used for every tie, and its length is the standard tie length")
    board_preset: StringProperty(name="Tie Preset", default="", update=_changed,
                                 description="Weathered Board preset for the ties' look and size")
    proto_units: EnumProperty(
        name="Prototype Units", default="IN", update=_units_update,
        description="Units for the full-size (prototype) measurements. Changing it converts them",
        items=[("IN", "Inches", "Prototype sizes in inches"),
               ("MM", "Millimetres", "Prototype sizes in millimetres")])
    proto_units_prev: StringProperty(default="IN", options={"HIDDEN"})
    tie_spacing: _proto("Tie Spacing", 20.0, "Centre-to-centre distance between ties")
    approach_ties: IntProperty(name="Approach Ties", default=2, min=0, soft_max=20,
                               update=_changed,
                               description="Ties before the heel of the movable rails")
    tail_ties: IntProperty(name="Ties Past Frog", default=3, min=0, soft_max=20, update=_changed,
                           description="Ties past the heel of the frog")
    length_step: _proto("Length Step", 6.0,
                        "Long turnout ties are rounded up to the standard tie length plus a "
                        "whole number of these steps (6 in on the prototype); 0 = exact lengths")
    headblock_ties: IntProperty(name="Headblock Ties", default=2, min=0, max=2, update=_changed,
                                description="Ties at the headblock lengthened to carry the "
                                            "switch stand: the long tie of the double tie at "
                                            "the headblock, and the one before it")
    headblock_tie_gap_auto: BoolProperty(
        name="Gap = Tie Width", default=True, update=_changed,
        description="Leave one tie width between the two long headblock ties")
    headblock_tie_gap: _proto("Headblock Tie Gap", 9.0,
                              "Gap between the two long headblock ties, face to face")
    double_tie_gap: _proto("Double Tie Gap", 0.5,
                           "Gap between the two ties of the double tie at the headblock (the long "
                           "headblock tie and the standard tie next to it), face to face")
    headblock_extra: _proto("Headblock Extension", 36.0,
                            "How much longer the headblock ties are, on the switch stand side")
    stand_side: EnumProperty(
        name="Switch Stand", default="STRAIGHT", update=_changed,
        description="Which side of the turnout the switch stand is on",
        items=[("STRAIGHT", "Straight Side", "Away from the diverging route"),
               ("DIVERGING", "Diverging Side", "On the diverging route's side")])
    printer: EnumProperty(
        name="Printer", default="RESIN", update=_changed,
        description="Printer type: sets the grain detail and the too-small-to-print warnings",
        items=[("RESIN", "Resin", "Fine detail; resin printer thresholds"),
               ("FDM", "FDM", "Filament printer; coarser detail and thresholds")])
    seed: IntProperty(name="Seed", default=0, min=0, update=_changed,
                      description="Number that picks the ties' random grain, lengths and offsets. "
                                  "Generate shows the seed it used here")
    lock_seed: BoolProperty(
        name="Lock Seed", default=False,
        description="Use the seed above for new turnouts instead of a random one, to repeat one "
                    "you liked. Also makes regenerating faster, since the ties are reused")
    pool_threshold: IntProperty(
        name="Unique Up To", default=80, min=2, soft_max=500, update=_changed,
        description="Turnouts with up to this many ties get a separate board per tie; "
                    "larger ones share boards between ties of the same length")
    pool_size: IntProperty(name="Boards per Length", default=4, min=1, soft_max=20,
                           update=_changed,
                           description="For large turnouts: boards built for each tie length")
    max_triangles: IntProperty(
        name="Max Triangles per Tie", default=15000, min=500, soft_max=100000, update=_changed,
        description="Each tie is simplified to about this many triangles before joining")

    # ---- variation ----
    length_jitter: _proto("Length Variation", 1.0, "Ties vary in length by up to this, plus or minus")
    end_jitter: _proto("End Offset", 0.5, "Ties shift across the track by up to this, plus or minus")
    yaw_jitter: FloatProperty(name="Angle Variation", default=0.3, min=0.0, max=5.0,
                              description="Ties turn by up to this many degrees, plus or minus",
                              update=_changed)
    random_turn: BoolProperty(name="Random Turn", default=True, update=_changed,
                              description="Turn random ties end for end")

    # ---- strip ----
    connector_width: _model("Connector Width", 0.0,
                            "Width of each connector; 0 uses the rail foot width")
    connector_height: FloatProperty(
        name="Connector Height", subtype="FACTOR", default=0.5, min=0.05, max=1.0,
        description="Connector height as a fraction of the tie height", update=_changed)
    seat_pad: BoolProperty(name="Flatten Rail Seats", default=True, update=_changed,
                           description="Fill the grain flat where the rail or tie plate sits")

    # ---- spikes ----
    fastening: EnumProperty(
        name="Fastening", default="HOLES", update=_changed,
        description="How the rail is held: holes for real spikes, spikes printed on the ties, "
                    "or neither (glue)",
        items=[("HOLES", "Spike Holes", "Holes for real spikes; you spike the rail down"),
               ("PRINTED", "Printed Spikes", "Spikes printed on the ties; the rail slides in "
                                             "under the spike heads"),
               ("NONE", "None", "No spikes or holes")])
    spike_shank: _model("Shank Width", 0.4, "Width of each printed spike's square shank")
    spike_overhang: _model("Head Overhang", 0.2, "How far each spike head reaches over the rail foot")
    spike_head: _model("Head Thickness", 0.2, "Thickness of each printed spike head")
    spike_side_clear: _model("Side Clearance", 0.15, "Gap between the rail foot edge and each shank")
    spike_top_clear: _model("Top Clearance", 0.10,
                            "Gap between the top of the rail foot and the underside of each head")
    spike_chamfer: FloatProperty(
        name="Head Chamfer", default=45.0, min=0.0, max=80.0, precision=0, step=500,
        update=_changed,
        description="Angle from horizontal of the slope under each spike head. 45 prints "
                    "without supports; 0 leaves the underside flat")
    spike_every: IntProperty(name="Spike Every Nth Tie", default=1, min=1, soft_max=6,
                             update=_changed,
                             description="1 spikes every tie; 2 or 3 makes the rail easier to slide in")
    spike_bare_ends: IntProperty(name="Bare End Ties", default=1, min=0, soft_max=5,
                                 update=_changed,
                                 description="Ties at each end left without printed spikes, so "
                                             "rail joiners slide onto the foot")
    hole_diameter: _model("Hole Diameter", 0.5, "Spike hole diameter; match your spikes")
    hole_clearance: _model("Clearance from Foot", 0.0, "Gap between the rail foot and each hole")
    use_stagger: BoolProperty(name="Stagger", default=True, update=_changed,
                              description="Offset the two spikes on each rail along the rail, "
                                          "as on the prototype")
    stagger: _proto("Stagger", 2.0, "Distance between the two spikes of a rail, along the rail")

    # ---- tie plates ----
    plates_on: BoolProperty(name="Tie Plates", default=False, update=_plate_update,
                            description="Tie plates under the rails (slide plates under the "
                                        "movable rails), merged where rails are close")
    plate_length: _proto("Plate Length", 14.0, "Tie plate length, across the track", _plate_update)
    plate_width: _proto("Plate Width", 7.75, "Tie plate width, along the track", _plate_update)
    plate_thickness: _proto("Plate Thickness", 0.75, "Tie plate thickness", _plate_update)
    plate_bias: _proto("Field-Side Bias", 1.0, "Plate shifted toward the outside of the rail",
                       _plate_update)
    shoulders: EnumProperty(
        name="Shoulders", default="DOUBLE", update=_plate_update,
        description="Raised ribs on the tie plate beside the rail foot, following the rail",
        items=[("NONE", "None", "Flat plate"),
               ("FIELD", "Field Side Only", "One shoulder outboard of each rail"),
               ("DOUBLE", "Double", "Shoulders on both sides of the rail foot")])
    shoulder_height: _proto("Shoulder Height", 0.5, "Shoulder height above the plate", _plate_update)
    shoulder_width: _proto("Shoulder Width", 0.75, "Shoulder width", _plate_update)
    shoulder_clearance: _model("Shoulder Clearance", 0.05,
                               "Gap between the rail foot and each shoulder, so the rail drops in")
    # ---- headblock hardware (separate from the tie plates) ----
    headblock_plate: BoolProperty(
        name="Headblock Plates", default=True, update=_changed,
        description="One plate each side of the track, across the double tie at the headblock, "
                    "under each pair of rail ends (straight and diverging), with clips along "
                    "both sides of the pair that hold the rail ends in line and the throw stops "
                    "on it: the headblock as one unit. Works with or without tie plates: "
                    "without them, the double tie is made thinner so the rails stay level")
    headblock_plate_thickness: _proto(
        "Headblock Plate Thickness", 0.75,
        "Thickness of the headblock plates when tie plates are off (the double tie is "
        "lowered by this much); with tie plates on they match the tie plates")
    throw_stops: BoolProperty(
        name="Throw Stops", default=True, update=_changed,
        description="Blocks on the double tie's long tie (on the headblock plate when it's on), "
                    "either side of each movable rail, that stop it at the straight and at the "
                    "diverging route")
    stops_every_tie: BoolProperty(
        name="On Every Movable Tie", default=False, update=_changed,
        description="Also put a throw stop on the outside of each movable rail on every tie "
                    "under the movable rails, from the heel to the headblock, set to the rail's "
                    "travel at that tie")
    stop_width: _model("Stop Width", 0.5, "Width of each throw stop across the track")
    stop_clearance: _model("Stop Clearance", 0.15,
                           "Play between a throw stop and the rail foot at each end of travel")
    bolts: BoolProperty(
        name="Bolts", default=True, update=_changed,
        description="Hex bolt heads fastening the headblock plates and throw stops to the ties. "
                    "Each throw stop gets a thin base plate for its bolts")
    bolt_size: _proto("Bolt Head Size", 1.5, "Bolt head width, across the flats")
    bolt_height: _proto("Bolt Head Height", 0.75, "Height of each bolt head")
    plate_preset: StringProperty(default="Modern heavy", options={"HIDDEN"})
    plate_modified: BoolProperty(default=False, options={"HIDDEN"})

    # ---- rail and frog laid on the ties ----
    rail_on: BoolProperty(
        name="Include Rail", default=False, update=_changed,
        description="Also add the rails (movable, stock, closure, diverging and guard rails) "
                    "on the tie strip, parented to it, for fit checks and renders. They use the "
                    "frog preset's rail profile")
    frog_on: BoolProperty(
        name="Include Frog", default=True, update=_changed,
        description="Also add the frog, built by Switch Frog Generator from the frog preset, "
                    "on the tie strip at the frog's place, parented to it, with the guard rails "
                    "(even without Include Rail), so the ties, frog and guard rails can be "
                    "exported together")

    # ---- presets and output ----
    switch_preset: StringProperty(default="", options={"HIDDEN"})
    switch_modified: BoolProperty(default=False, options={"HIDDEN"})
    export_what: EnumProperty(  # the last choice made in Export STL's file browser
        name="Export", default="TIES", options={"HIDDEN"},
        items=[("TIES", "Ties Only", ""), ("TIES_FROG", "Ties, Frog and Guard Rails", ""),
               ("ALL", "Entire Turnout", ""), ("RAIL", "Rail and Frog", "")])
    export_template: StringProperty(
        name="File Name", default="stub_switch_{scale}_{frog}_{hand}.stl",
        description="Default STL file name; {scale}, {frog} and {hand} are filled in")
    last_report: StringProperty(default="", options={"HIDDEN"})
    show_info: BoolProperty(
        name="Show Info", default=True,
        description="Show the informational lines in the panel (summary, sizes, hints). Turn "
                    "off to see only the settings; errors and warnings are always shown")

    # ------------------------------------------------------------------

    def scale_n(self) -> float:
        """N in 1:N for the chosen scale."""
        return scales.scale_n(self.scale, self.scale_custom)

    def full_mm(self, key: str) -> float:
        """A prototype setting in full-size millimetres."""
        return scales.to_full_mm(getattr(self, key), self.proto_units)

    def frog_name(self) -> str:
        """The frog preset in use: the one chosen, or Switch Frog Generator's default."""
        return self.frog_preset or frog_bridge.default_preset()

    def frog(self):
        """The frog preset's details, as frog_bridge.frog_info returns them: (info, error)."""
        return frog_bridge.frog_info(self.frog_name())

    def template(self):
        """The template tie, as wb_bridge.template returns it: (Template or None, error)."""
        return wb_bridge.template(self.tie_source, self.tie_object, self.board_preset)

    def turnout_spec(self, info=None) -> TurnoutSpec:
        """The settings and the frog as a turnout.TurnoutSpec."""
        err = ""
        if info is None:
            info, err = self.frog()
        n = self.scale_n()
        if info is None:
            return TurnoutSpec(scale_n=n, gauge=self.gauge, head_width=1.0, foot_width=1.0,
                               frog_number=6.0, frog_toe=1.0, frog_heel=1.0, frog_point=0.0,
                               flangeway=1.0, movable_length=self.full_mm("movable_length"),
                               frog_error=err or "Choose a frog preset.")
        p = info.profile
        return TurnoutSpec(
            scale_n=n, gauge=self.gauge, head_width=p.head_width, foot_width=p.base_width,
            frog_number=info.number, frog_toe=info.toe, frog_heel=info.heel,
            frog_point=info.point, flangeway=info.flangeway,
            movable_length=self.full_mm("movable_length"),
            throw=0.0 if self.throw_auto else self.throw, headblock_gap=self.headblock_gap,
            guard_rails=self.guard_rails, guard_mode=self.guard_mode, heel_rails=self.heel_rails,
            guard_frog_margin=self.full_mm("guard_frog_margin"),
            guard_length=self.full_mm("guard_length"),
            guard_flare_length=self.full_mm("guard_flare_length"),
            guard_flare_angle=self.guard_flare_angle,
            frog_lines=info.lines)

    def layout_spec(self, info=None, tmpl=None, **overrides) -> Spec:
        """The settings, frog and template tie as a layout.Spec (prototype lengths in full mm).

        ``overrides`` set Spec fields the settings don't hold, such as the
        grain depth measured from the built boards.
        """
        f = self.full_mm
        if info is None:
            info, _err = self.frog()
        tie_error = ""
        if tmpl is None:
            tmpl, tie_error = self.template()
        p = info.profile if info else None
        spec = Spec(
            scale_n=self.scale_n(),
            tie_length=tmpl.length if tmpl else 0.0, tie_width=tmpl.width if tmpl else 0.0,
            tie_height=tmpl.thickness if tmpl else 0.0, tie_error=tie_error,
            spacing=f("tie_spacing"),
            foot_width=p.base_width if p else 1.0, head_width=p.head_width if p else 1.0,
            approach_ties=self.approach_ties, tail_ties=self.tail_ties,
            length_step=f("length_step"), headblock_ties=self.headblock_ties,
            headblock_extra=f("headblock_extra"), stand_side=self.stand_side,
            headblock_tie_gap=-1.0 if self.headblock_tie_gap_auto else f("headblock_tie_gap"),
            double_tie_gap=f("double_tie_gap"),
            connector_width=self.connector_width, connector_height_frac=self.connector_height,
            fastening=self.fastening, hole_diameter=self.hole_diameter,
            hole_clearance=self.hole_clearance,
            stagger=f("stagger") if self.use_stagger else 0.0,
            foot_edge=p.base_edge_thickness if p else 0.0,
            foot_web=p.base_thickness if p else 0.0, web_width=p.web_thickness if p else 0.0,
            spike_shank=self.spike_shank, spike_overhang=self.spike_overhang,
            spike_head=self.spike_head, spike_side_clear=self.spike_side_clear,
            spike_chamfer=self.spike_chamfer, spike_top_clear=self.spike_top_clear,
            spike_every=self.spike_every, spike_bare_ends=self.spike_bare_ends,
            length_jitter=f("length_jitter"), end_jitter=f("end_jitter"),
            yaw_jitter=self.yaw_jitter,
            plates=self.plates_on, plate_length=f("plate_length"), plate_width=f("plate_width"),
            plate_thickness=f("plate_thickness"), plate_bias=f("plate_bias"),
            shoulders=self.shoulders, shoulder_height=f("shoulder_height"),
            shoulder_width=f("shoulder_width"), shoulder_clearance=self.shoulder_clearance,
            seat_pad=self.seat_pad,
            headblock_plate=self.headblock_plate,
            headblock_plate_thickness=f("headblock_plate_thickness"),
            bolts=self.bolts, bolt_size=f("bolt_size"), bolt_height=f("bolt_height"),
            throw_stops=self.throw_stops, stops_every_tie=self.stops_every_tie,
            stop_width=self.stop_width,
            stop_clearance=self.stop_clearance,
            split=self.split, split_at=self.split_at, tab_depth=self.tab_depth,
            joint_clearance=self.joint_clearance,
            frog_solid=bool(info and self.frog_on and info.solid),
            frog_base_plate=bool(info and self.frog_on and info.base_plate),
        )
        for k, v in overrides.items():
            setattr(spec, k, v)
        return spec

    # ---- presets ----

    def apply_frog(self, name: str) -> None:
        """Choose frog preset ``name`` and set the scale (and gauge) to the frog's scale."""
        self.frog_preset = name
        info, _err = frog_bridge.frog_info(name)
        if info and info.scale in scales.SCALES and info.scale != self.scale:
            self.scale = info.scale

    def plate_values(self) -> dict:
        """Tie plate settings with lengths in inches, for a plate preset."""
        out = {}
        for key in PLATE_KEYS:
            value = getattr(self, key)
            if key in PROTO_LENGTH_KEYS:
                value = scales.from_full_mm(self.full_mm(key), "IN")
            out[key] = value
        return out

    def apply_plate_values(self, values: dict, name: str) -> None:
        """Load a plate preset's values (lengths in inches) and select it as ``name``."""
        with quiet():
            for key in PLATE_KEYS:
                if key not in values:
                    continue
                value = values[key]
                if key in PROTO_LENGTH_KEYS:
                    value = scales.from_full_mm(scales.to_full_mm(float(value), "IN"),
                                                self.proto_units)
                setattr(self, key, value)
            self.plate_preset = name
            self.plate_modified = False
        _changed(self, None)

    def switch_values(self) -> dict:
        """Every setting, for a switch preset (the template tie object is stored by name)."""
        skip = {"rna_type", "name", "proto_units_prev", "plate_modified", "switch_preset",
                "switch_modified", "last_report", "export_what", "tie_object", "show_info"}
        out = {p.identifier: getattr(self, p.identifier)
               for p in self.bl_rna.properties if p.identifier not in skip}
        out["tie_object_name"] = self.tie_object.name if self.tie_object else ""
        return out

    def apply_switch_values(self, values: dict, name: str) -> None:
        """Load a switch preset's values and select it as ``name``.

        Units first, so saved lengths aren't converted. Unknown keys and
        values this version rejects are skipped, so older presets load. The
        template tie object is found by name in this file, if it is there.
        """
        names = {p.identifier for p in self.bl_rna.properties}
        with quiet():
            if "proto_units" in values:
                self.proto_units = self.proto_units_prev = values["proto_units"]
            for key, value in values.items():
                if key in names and key != "proto_units":
                    try:
                        setattr(self, key, value)
                    except (TypeError, ValueError, AttributeError):
                        pass
            obj = bpy.data.objects.get(values.get("tie_object_name", "") or "")
            if obj is not None and wb_bridge.is_board(obj):
                self.tie_object = obj
            self.switch_preset = name
            self.switch_modified = False


def register():
    """Add ``scene.stub_switch``. STUBSWITCH_Settings must already be registered."""
    bpy.types.Scene.stub_switch = bpy.props.PointerProperty(type=STUBSWITCH_Settings)


def unregister():
    """Remove ``scene.stub_switch``."""
    del bpy.types.Scene.stub_switch
