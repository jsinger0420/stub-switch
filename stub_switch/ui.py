"""The Stub Switch tab in the 3D Viewport sidebar (N panel)."""


import bpy

from . import (frog_bridge, layout, operators, plates, preset_store, scales, turnout,
               wb_bridge)


def _s(context):
    """The scene's Stub Switch settings."""
    return context.scene.stub_switch


def _u(s):
    """Short label for the prototype units: "in" or "mm"."""
    return "in" if s.proto_units == "IN" else "mm"


_last: list = [None, None]  # [key, (frog info, turnout, layout, template)]


def compute(s):
    """(frog info, turnout, layout, template) for the panel, recomputed only when inputs change."""
    info, _err = s.frog()
    tmpl, _terr = s.template()
    tspec = s.turnout_spec(info)
    lspec = s.layout_spec(info, tmpl)
    key = repr((tspec, lspec))
    if _last[0] != key:
        t = turnout.compute(tspec)
        _last[0], _last[1] = key, (info, t, layout.compute(t, lspec), tmpl)
    return _last[1]


# ---- menus ----

class STUBSWITCH_MT_frog_presets(bpy.types.Menu):
    """Switch Frog Generator presets: the frog sets the angle, flangeway and rail"""

    bl_label = "Frog Presets"
    bl_idname = "STUBSWITCH_MT_frog_presets"

    def draw(self, context):
        """Your saved frog presets, then the built-in ones, or why there are none."""
        col = self.layout
        missing = frog_bridge.available()
        if missing:
            col.label(text=missing, icon="ERROR")
            return
        builtin, saved = frog_bridge.preset_names()
        if saved:
            col.label(text="Your frogs")
            for name in saved:
                col.operator("stub_switch.set_frog_preset", text=name).name = name
            col.separator()
        col.label(text="Built-in")
        for name in builtin:
            col.operator("stub_switch.set_frog_preset", text=name).name = name


class STUBSWITCH_MT_board_presets(bpy.types.Menu):
    """Choose the Weathered Board preset that sets the ties' look and size"""

    bl_label = "Weathered Board Presets"
    bl_idname = "STUBSWITCH_MT_board_presets"

    def draw(self, context):
        """One item per Weathered Board preset, or why there are none."""
        names = wb_bridge.preset_names()
        if not names:
            self.layout.label(text=wb_bridge.available() or "No presets found", icon="ERROR")
        for name, _desc in names:
            self.layout.operator("stub_switch.set_board_preset", text=name).name = name


class STUBSWITCH_MT_plate_presets(bpy.types.Menu):
    """Built-in tie plate presets by era, then your saved ones"""

    bl_label = "Tie Plate Presets"
    bl_idname = "STUBSWITCH_MT_plate_presets"

    def draw(self, context):
        """Built-in presets, then saved presets each with a delete button."""
        col = self.layout
        for p in plates.BUILTIN_PLATES:
            col.operator("stub_switch.apply_plate_preset", text=p.name).name = p.name
        saved = preset_store.saved_names(preset_store.PLATE)
        if saved:
            col.separator()
            for name in saved:
                row = col.row(align=True)
                row.operator("stub_switch.apply_plate_preset", text=name).name = name
                row.operator("stub_switch.remove_plate_preset", text="", icon="X").name = name


class STUBSWITCH_MT_switch_presets(bpy.types.Menu):
    """Your saved switch presets"""

    bl_label = "Switch Presets"
    bl_idname = "STUBSWITCH_MT_switch_presets"

    def draw(self, context):
        """Saved switch presets, each with a delete button."""
        saved = preset_store.saved_names(preset_store.SWITCH)
        if not saved:
            self.layout.label(text="No switch presets saved yet")
        for name in saved:
            row = self.layout.row(align=True)
            row.operator("stub_switch.apply_switch_preset", text=name).name = name
            row.operator("stub_switch.remove_switch_preset", text="", icon="X").name = name


def _preset_row(layout_, menu, label, current, modified, save_op):
    """A preset menu showing the current preset (marked if modified), plus a save button."""
    row = layout_.row(align=True)
    text = (current or label) + (" (modified)" if current and modified else "")
    row.menu(menu, text=text)
    row.operator(save_op, text="", icon="ADD")


def _info(context=None) -> bool:
    """True when the informational lines are shown (Show Info in the main panel's header)."""
    return (context or bpy.context).scene.stub_switch.show_info


def _hint(col, *lines):
    """Small grey info lines, shown only with Show Info on."""
    if not _info():
        return
    sub = col.column()
    sub.scale_y = 0.8
    for i, line in enumerate(lines):
        sub.label(text=line, icon="INFO" if i == 0 else "BLANK1")


# ---- panels ----

class _Panel:
    """Shared placement: the Stub Switch tab in the 3D Viewport sidebar."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Stub Switch"


class STUBSWITCH_PT_main(_Panel, bpy.types.Panel):
    """Generate and export the stub switch, and check its size"""

    bl_label = "Stub Switch"

    def draw_header(self, context):
        """The Show Info toggle, beside the panel's name."""
        s = _s(context)
        self.layout.prop(s, "show_info", text="", icon="INFO" if s.show_info else "HIDE_ON",
                         emboss=False)

    def draw(self, context):
        """Presets, Generate and Export, then a live summary or the layout errors."""
        s = _s(context)
        col = self.layout.column()
        _preset_row(col, "STUBSWITCH_MT_switch_presets", "Switch Presets", s.switch_preset,
                    s.switch_modified, "stub_switch.save_switch_preset")
        missing = wb_bridge.available() or frog_bridge.available()
        if missing:
            box = col.box()
            box.alert = True
            box.label(text=missing, icon="ERROR")
        row = col.row(align=True)
        row.scale_y = 1.4
        if operators.is_busy():
            row.alert = True
            row.label(text="Generating stub switch, please wait...", icon="SORTTIME")
        else:
            row.enabled = not missing
            row.operator("stub_switch.generate", icon="MESH_GRID")
        col.operator("stub_switch.export_stl", icon="EXPORT")
        show = s.show_info
        if s.last_report and show:
            col.label(text=s.last_report)

        info, t, lay, _tmpl = compute(s)
        if lay.errors:  # problems are always shown
            box = col.box()
            box.alert = True
            for e in lay.errors:
                box.label(text=e, icon="ERROR")
            return
        problems = t.warnings + lay.warnings
        if not show:
            if problems:
                box = col.box()
                for w in problems:
                    box.label(text=w, icon="ERROR")
            return
        box = col.box()
        m = lay.summary
        n = s.scale_n()
        box.label(text=f"#{info.number:g} frog ({m['frog_angle']:.2f} deg), "
                       f"{'left' if s.hand == 'LEFT' else 'right'} hand", icon="INFO")
        box.label(text=f"Headblock to frog point {m['lead']:.1f} mm "
                       f"({scales.feet_inches(m['lead'] * n)})")
        box.label(text=f"Lead curve radius {m['lead_radius']:.0f} mm "
                       f"({m['lead_radius'] / 25.4:.1f} in)")
        box.label(text=f"Throw {m['throw']:.2f} mm, switch angle {m['switch_angle']:.2f} deg")
        box.label(text=f"Printed size {m['overall_length']:.1f} x {m['overall_width']:.1f} x "
                       f"{m['top']:.2f} mm")
        box.label(text=f"{len(lay.ties)} ties, longest {m['longest_tie']:.1f} mm "
                       f"({scales.feet_inches(m['longest_tie_full'])})")
        if lay.split_x is not None:
            n_mov = sum(1 for tie in lay.ties if tie.x < lay.split_x)
            box.label(text=f"Two pieces: {n_mov} ties movable, {len(lay.ties) - n_mov} fixed, "
                           f"{len(lay.tabs)} joint tabs")
        if s.fastening == "HOLES":
            box.label(text=f"{len(lay.holes)} spike holes")
        elif s.fastening == "PRINTED":
            box.label(text=f"{len(lay.spikes)} printed spikes")
        for w in problems:
            box.label(text=w, icon="ERROR")


class STUBSWITCH_PT_track(_Panel, bpy.types.Panel):
    """The frog (angle and rail), scale, hand and the movable rails"""

    bl_label = "Frog and Track"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Frog preset and what it sets, scale and gauge, hand, movable rails, guard rails."""
        s = _s(context)
        col = self.layout.column()
        if s.show_info:
            col.label(text="Frog preset (from Switch Frog Generator):")
        col.menu("STUBSWITCH_MT_frog_presets", text=s.frog_name() or "Choose a frog preset",
                 icon="IPO_LINEAR")
        info, err = s.frog()
        if info is None:
            box = col.box()
            box.alert = True
            box.label(text=err, icon="ERROR")
        elif s.show_info:
            box = col.box()
            p = info.profile
            box.label(text=f"#{info.number:g} frog, {info.angle_deg:.3f} deg, "
                           f"{info.length:.1f} mm long")
            box.label(text=f"Rail {p.name}: {p.height:.2f} mm high, foot {p.base_width:.2f} mm")
            box.label(text=f"Flangeway {info.flangeway:.2f} mm")
        _hint(col, "To change the frog or rail, edit and save", "the preset in the Frog panel.")
        col.separator()
        col.prop(s, "scale")
        if s.scale == "CUSTOM":
            col.prop(s, "scale_custom")
        col.prop(s, "gauge", text="Gauge (mm)")
        col.prop(s, "hand", expand=True)
        col.separator()
        u = _u(s)
        col.prop(s, "movable_length", text=f"Movable Rail Length ({u})")
        row = col.row(align=True)
        row.prop(s, "throw_auto")
        sub = row.row()
        sub.enabled = not s.throw_auto
        sub.prop(s, "throw", text="Throw (mm)")
        col.prop(s, "headblock_gap", text="Headblock Gap (mm)")
        col.prop(s, "guard_rails")
        sub = col.column()
        sub.enabled = s.guard_rails
        sub.prop(s, "guard_mode", expand=True)
        if s.guard_mode == "FROG":
            sub.prop(s, "guard_frog_margin", text=f"Frog Past Guard Rail ({u})")
        else:
            sub.prop(s, "guard_length", text=f"Guard Rail Length ({u})")
        sub.prop(s, "guard_flare_length", text=f"Bend Length ({u})")
        sub.prop(s, "guard_flare_angle", text="Bend Angle (degrees)")
        _info, t, _lay, _tmpl = compute(s)
        if s.guard_rails and t.ok and s.show_info:
            g0, g1 = t.guard_span
            sub.label(text=f"Guard rails {g1 - g0:.1f} mm "
                           f"({scales.feet_inches((g1 - g0) * s.scale_n())})", icon="INFO")


class STUBSWITCH_PT_ties(_Panel, bpy.types.Panel):
    """The template tie, spacing and the special ties"""

    bl_label = "Ties"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Template tie, its size, spacing, ends of the strip, long ties, printer and seed."""
        s, u = _s(context), _u(_s(context))
        col = self.layout.column()
        col.prop(s, "tie_source", expand=True)
        if s.tie_source == "OBJECT":
            row = col.row(align=True)
            row.prop(s, "tie_object", text="")
            row.operator("stub_switch.use_active_board", text="", icon="EYEDROPPER")
        else:
            col.menu("STUBSWITCH_MT_board_presets", text=s.board_preset or "Choose a tie preset",
                     icon="MESH_PLANE")
        tmpl, err = s.template()
        if tmpl is None:
            box = col.box()
            box.alert = True
            box.label(text=err, icon="ERROR")
        elif s.show_info:
            box = col.box()
            box.label(text=f"Standard tie {scales.feet_inches(tmpl.length)} x "
                           f"{scales.feet_inches(tmpl.width)} x {scales.feet_inches(tmpl.thickness)}")
            n = s.scale_n()
            box.label(text=f"Model: {tmpl.length / n:.2f} x {tmpl.width / n:.2f} x "
                           f"{tmpl.thickness / n:.2f} mm")
        _hint(col, "Make a board sized as a standard tie with", "Weathered Board's Add Board. Its look,",
              "width and thickness are used for every tie;", "the lengths are worked out.")
        col.separator()
        col.prop(s, "proto_units")
        col.prop(s, "tie_spacing", text=f"Spacing ({u})")
        col.prop(s, "approach_ties")
        col.prop(s, "tail_ties")
        col.prop(s, "length_step", text=f"Length Step ({u})")
        col.prop(s, "double_tie_gap", text=f"Double Tie Gap ({u})")
        col.prop(s, "headblock_ties")
        sub = col.column()
        sub.enabled = s.headblock_ties > 0
        row = sub.row()
        row.enabled = s.headblock_ties == 2
        row.prop(s, "headblock_tie_gap_auto")
        gap = row.row()
        gap.enabled = not s.headblock_tie_gap_auto
        gap.prop(s, "headblock_tie_gap", text=f"Gap ({u})")
        sub.prop(s, "headblock_extra", text=f"Headblock Extension ({u})")
        sub.prop(s, "stand_side")
        col.separator()
        col.prop(s, "printer", expand=True)
        row = col.row(align=True)
        row.prop(s, "seed")
        row.prop(s, "lock_seed", text="", icon="LOCKED" if s.lock_seed else "UNLOCKED")
        row.operator("stub_switch.new_seed", text="", icon="FILE_REFRESH")


class STUBSWITCH_PT_strip(_Panel, bpy.types.Panel):
    """Printing in two pieces, connectors joining the ties, and rail seats"""

    bl_label = "Strip"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Two pieces and their joint, connector size and rail seat flattening."""
        s = _s(context)
        col = self.layout.column()
        col.prop(s, "split")
        sub = col.column()
        sub.enabled = s.split
        sub.prop(s, "split_at", text="")
        sub.prop(s, "tab_depth", text="Tab Depth (mm)")
        sub.prop(s, "joint_clearance", text="Joint Clearance (mm)")
        col.separator()
        col.prop(s, "connector_width", text="Connector Width (mm)")
        col.prop(s, "connector_height")
        col.prop(s, "seat_pad")


class STUBSWITCH_PT_variation(_Panel, bpy.types.Panel):
    """Random differences in tie length, position and angle"""

    bl_label = "Variation"
    bl_parent_id = "STUBSWITCH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        """Length, end offset and angle variation, and random turning."""
        s, u = _s(context), _u(_s(context))
        col = self.layout.column()
        col.prop(s, "length_jitter", text=f"Length +/- ({u})")
        col.prop(s, "end_jitter", text=f"End Offset +/- ({u})")
        col.prop(s, "yaw_jitter", text="Angle +/- (degrees)")
        col.prop(s, "random_turn")


class STUBSWITCH_PT_spikes(_Panel, bpy.types.Panel):
    """Spike holes for real spikes, printed spikes, or neither"""

    bl_label = "Spikes"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Fastening choice, then hole or printed spike sizes, then stagger."""
        s, u = _s(context), _u(_s(context))
        col = self.layout.column()
        col.prop(s, "fastening", expand=True)
        if s.fastening == "HOLES":
            col.prop(s, "hole_diameter", text="Diameter (mm)")
            col.prop(s, "hole_clearance", text="Clearance from Foot (mm)")
        if s.fastening == "PRINTED" or s.headblock_plate:
            if s.fastening != "PRINTED":
                col.label(text="Headblock clip sizes:")
            col.prop(s, "spike_shank", text="Shank Width (mm)")
            col.prop(s, "spike_overhang", text="Head Overhang (mm)")
            col.prop(s, "spike_head", text="Head Thickness (mm)")
            col.prop(s, "spike_side_clear", text="Side Clearance (mm)")
            col.prop(s, "spike_top_clear", text="Top Clearance (mm)")
            col.prop(s, "spike_chamfer", text="Head Chamfer (degrees)")
        if s.fastening == "PRINTED":
            col.prop(s, "spike_every")
            col.prop(s, "spike_bare_ends")
            _hint(col, "Slide each rail in from its end. Bend", "the curved rails first. Keep slicer",
                  "supports off the top face.")
        if s.fastening == "NONE":
            return
        col.prop(s, "use_stagger")
        sub = col.column()
        sub.enabled = s.use_stagger
        sub.prop(s, "stagger", text=f"Stagger ({u})")
        _hint(col, "The movable rails are not spiked between", "their heel and the headblock.")


class STUBSWITCH_PT_plates(_Panel, bpy.types.Panel):
    """Tie plates, slide plates and shoulders under the rails"""

    bl_label = "Tie Plates"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw_header(self, context):
        """The on/off checkbox in the panel header."""
        self.layout.prop(_s(context), "plates_on", text="")

    def draw(self, context):
        """Plate presets, then plate and shoulder sizes (greyed out when plates are off)."""
        s, u = _s(context), _u(_s(context))
        col = self.layout.column()
        _preset_row(col, "STUBSWITCH_MT_plate_presets", "Plate Presets", s.plate_preset,
                    s.plate_modified, "stub_switch.save_plate_preset")
        body = col.column()
        body.enabled = s.plates_on
        body.prop(s, "plate_length", text=f"Length ({u})")
        body.prop(s, "plate_width", text=f"Width ({u})")
        body.prop(s, "plate_thickness", text=f"Thickness ({u})")
        body.prop(s, "plate_bias", text=f"Field-Side Bias ({u})")
        body.prop(s, "shoulders")
        sub = body.column()
        sub.enabled = s.shoulders != "NONE"
        sub.prop(s, "shoulder_height", text=f"Shoulder Height ({u})")
        sub.prop(s, "shoulder_width", text=f"Shoulder Width ({u})")
        sub.prop(s, "shoulder_clearance", text="Shoulder Clearance (mm)")


class STUBSWITCH_PT_headblock(_Panel, bpy.types.Panel):
    """Headblock plates holding the rail ends, and throw stops for the movable rails"""

    bl_label = "Headblock"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Headblock plates (and their thickness without tie plates), and throw stops."""
        s, u = _s(context), _u(_s(context))
        col = self.layout.column()
        col.prop(s, "headblock_plate")
        sub = col.column()
        sub.enabled = s.headblock_plate and not s.plates_on
        sub.prop(s, "headblock_plate_thickness", text=f"Plate Thickness ({u})")
        if s.headblock_plate:
            _hint(col, "Clips use the printed spike sizes", "(Spikes panel). Without tie plates the",
                  "double tie is made thinner by the", "plate thickness. The throw stops",
                  "stand on the plate.")
        col.separator()
        col.prop(s, "throw_stops")
        sub = col.column()
        sub.enabled = s.throw_stops
        sub.prop(s, "stops_every_tie")
        sub.prop(s, "stop_width", text="Stop Width (mm)")
        sub.prop(s, "stop_clearance", text="Stop Clearance (mm)")
        col.separator()
        col.prop(s, "bolts")
        sub = col.column()
        sub.enabled = s.bolts and (s.headblock_plate or s.throw_stops)
        sub.prop(s, "bolt_size", text=f"Bolt Head Size ({u})")
        sub.prop(s, "bolt_height", text=f"Bolt Head Height ({u})")


class STUBSWITCH_PT_rail(_Panel, bpy.types.Panel):
    """Rails and frog laid on the ties, for fit checks and renders"""

    bl_label = "Rail and Frog"
    bl_parent_id = "STUBSWITCH_PT_main"

    def draw(self, context):
        """Include Rail (and which route the movable rails are set for) and Include Frog."""
        s = _s(context)
        col = self.layout.column()
        col.prop(s, "rail_on")
        sub = col.row()
        sub.enabled = s.rail_on
        sub.prop(s, "points_set", expand=True)
        sub = col.row()
        sub.enabled = s.rail_on
        sub.prop(s, "heel_rails")
        col.prop(s, "frog_on")
        info, err = s.frog()
        if s.frog_on and info is not None and info.base_plate:
            _hint(col, "This frog has a base plate; it sits", "below the rail seat.")


class STUBSWITCH_PT_build(_Panel, bpy.types.Panel):
    """Mesh detail and board reuse, trading build time for variety"""

    bl_label = "Build Options"
    bl_parent_id = "STUBSWITCH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        """Triangle limit and board sharing for large turnouts."""
        s = _s(context)
        col = self.layout.column()
        col.prop(s, "max_triangles")
        col.prop(s, "pool_threshold")
        sub = col.column()
        sub.enabled = len(compute(s)[2].ties) > s.pool_threshold
        sub.prop(s, "pool_size")


classes = (
    STUBSWITCH_MT_frog_presets, STUBSWITCH_MT_board_presets, STUBSWITCH_MT_plate_presets,
    STUBSWITCH_MT_switch_presets,
    STUBSWITCH_PT_main, STUBSWITCH_PT_track, STUBSWITCH_PT_ties, STUBSWITCH_PT_strip,
    STUBSWITCH_PT_variation, STUBSWITCH_PT_spikes, STUBSWITCH_PT_plates, STUBSWITCH_PT_headblock,
    STUBSWITCH_PT_rail,
    STUBSWITCH_PT_build,
)
