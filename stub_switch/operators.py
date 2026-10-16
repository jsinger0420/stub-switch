"""Operators: the buttons in the Stub Switch panel. Each docstring is its tooltip."""

import os
import random

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import build, frog_bridge, plates, preset_store, wb_bridge
from .preset_store import PresetError


def _settings(context):
    """The scene's Stub Switch settings."""
    return context.scene.stub_switch


_busy = False


def is_busy() -> bool:
    """True while a turnout is being generated (the panel shows a wait message)."""
    return _busy


def _redraw(context):
    """Ask every area on the screen to redraw, so the panel shows the busy state."""
    screen = context.screen
    if screen:
        for area in screen.areas:
            area.tag_redraw()


class STUBSWITCH_OT_generate(bpy.types.Operator):
    """Add a new stub switch at the 3D cursor from these settings, with a random seed unless Lock Seed is on. Turnouts made earlier are kept"""

    bl_idname = "stub_switch.generate"
    bl_label = "Generate Stub Switch"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None

    def _run(self, context, progress=None):
        """Build the turnout and report errors, warnings and the summary line."""
        try:
            result = build.generate(context, progress)
        except (build.BuildError, wb_bridge.BridgeError, frog_bridge.FrogBridgeError) as err:
            for line in str(err).splitlines():
                self.report({"ERROR"}, line)
            _settings(context).last_report = str(err).splitlines()[0]
            return {"CANCELLED"}
        for w in result.warnings:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, _settings(context).last_report)
        return {"FINISHED"}

    def execute(self, context):
        """Build straight away, with no wait message (scripts and the redo panel)."""
        return self._run(context)

    def invoke(self, context, event):
        """Show the wait message and busy cursor first, then build on the next timer tick."""
        global _busy
        if _busy:
            return {"CANCELLED"}
        _busy = True
        wm = context.window_manager
        context.window.cursor_modal_set("WAIT")
        if context.workspace:
            context.workspace.status_text_set("Generating stub switch, please wait...")
        _redraw(context)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        """On the first timer tick, build with a progress bar, then restore the cursor."""
        global _busy
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_begin(0, 1)
        try:
            return self._run(context, lambda done, total: wm.progress_update(done / total))
        finally:
            wm.progress_end()
            context.window.cursor_modal_restore()
            if context.workspace:
                context.workspace.status_text_set(None)
            _busy = False
            _redraw(context)


class STUBSWITCH_OT_new_seed(bpy.types.Operator):
    """Pick a new random seed for different-looking ties"""

    bl_idname = "stub_switch.new_seed"
    bl_label = "New Seed"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Set a random seed."""
        _settings(context).seed = random.randrange(1, 2**31 - 1)
        return {"FINISHED"}


EXPORT_WHAT = [
    ("TIES", "Ties Only", "Just the tie strip, ready to print"),
    ("TIES_FROG", "Ties, Frog and Guard Rails",
     "The tie strip with the frog and guard rails, so you can lay your own rail "
     "(needs Include Frog)"),
    ("ALL", "Entire Turnout", "Tie strip, rails, guard rails and frog"),
    ("RAIL", "Rail and Frog", "Just the rails, guard rails and the frog"),
]


def _safe(name: str) -> str:
    """``name`` with characters a file name can't hold replaced by _ (spaces too)."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


class STUBSWITCH_OT_export_stl(bpy.types.Operator, ExportHelper):
    """Export the selected stub switches (ties, rail and frog, or a part) as STL files in millimetres"""

    bl_idname = "stub_switch.export_stl"
    bl_label = "Export STL"
    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})
    export_what: EnumProperty(name="Export", items=EXPORT_WHAT, default="TIES",
                              description="What to write for each selected turnout")
    separate_pieces: BoolProperty(
        name="Each Tie Piece to Its Own File", default=True,
        description="For a tie strip printed in two pieces: write the fixed rail piece and the "
                    "movable rail piece to separate files, ending _fixed and _movable")

    @classmethod
    def poll(cls, context):
        """Only available when a stub switch, or a rail or frog on one, is selected."""
        return bool(build.selected_switches(context))

    def invoke(self, context, event):
        """Open the file browser on the default file name, next to the .blend file."""
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        self.filepath = os.path.join(folder, build.file_name(_settings(context)))
        self.export_what = _settings(context).export_what
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        """The export options, in the file browser's side panel."""
        col = self.layout.column()
        col.label(text="Export:")
        col.prop(self, "export_what", expand=True)
        col.separator()
        sub = col.row()
        sub.enabled = self.export_what != "RAIL"
        sub.prop(self, "separate_pieces")
        col.separator()
        _hint = col.column()
        _hint.scale_y = 0.8
        _hint.label(text="Each rail, guard rail and the frog", icon="INFO")
        _hint.label(text="are written to their own files,")
        _hint.label(text="named after the file name chosen.")

    def execute(self, context):
        """Write the chosen parts of the selected turnouts: the tie strip (one file, or one per
        piece) and every rail, guard rail and frog in a file of its own."""
        if _settings(context).export_what != self.export_what:
            _settings(context).export_what = self.export_what
        switches = build.selected_switches(context)
        groups = [(obj, build.export_objects(obj, self.export_what)) for obj in switches]
        groups = [(obj, objs) for obj, objs in groups if objs]
        if not groups:
            self.report({"ERROR"}, "The selected turnouts have no frog to export. Tick Include "
                                   "Frog (Rail and Frog panel) and generate them again."
                        if self.export_what == "TIES_FROG" else
                        "The selected turnouts have no rail or frog. Tick Include Rail or "
                        "Include Frog and generate them again.")
            return {"CANCELLED"}
        stem, ext = os.path.splitext(self.filepath)
        count = 0
        try:
            for obj, objs in groups:
                base = stem if len(groups) == 1 else f"{stem}_{_safe(obj.name)}"
                pieces = [o for o in build.tie_pieces(obj) if o in objs]
                parts = [o for o in objs if o not in pieces]
                if len(pieces) > 1 and self.separate_pieces:
                    for label, piece in zip(("fixed", "movable"), pieces):
                        build.export_stl(context, [piece], f"{base}_{label}{ext}")
                        count += 1
                elif pieces:
                    build.export_stl(context, pieces, f"{base}{ext}")
                    count += 1
                for part in parts:  # every rail, guard rail and the frog on its own
                    role = (part.name[len(obj.name):].strip()
                            if part.name.startswith(obj.name) else "") or part.name
                    build.export_stl(context, [part], f"{base}_{_safe(role)}{ext}")
                    count += 1
        except RuntimeError as err:
            self.report({"ERROR"}, f"Export failed: {err}")
            return {"CANCELLED"}
        written = (os.path.basename(self.filepath) if count == 1
                   else f"{count} files next to {os.path.basename(self.filepath)}")
        what = dict((k, n) for k, n, _d in EXPORT_WHAT)[self.export_what].lower()
        self.report({"INFO"}, f"Exported {what} for {len(groups)} turnout(s) to {written}")
        return {"FINISHED"}


class STUBSWITCH_OT_set_frog_preset(bpy.types.Operator):
    """Use this Switch Frog Generator preset: it sets the turnout's angle, flangeway, rail profile and scale"""

    bl_idname = "stub_switch.set_frog_preset"
    bl_label = "Frog Preset"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    name: StringProperty()

    def execute(self, context):
        """Store the chosen frog preset and match the scale to it."""
        _settings(context).apply_frog(self.name)
        return {"FINISHED"}


class STUBSWITCH_OT_set_board_preset(bpy.types.Operator):
    """Use this Weathered Board preset for the ties"""

    bl_idname = "stub_switch.set_board_preset"
    bl_label = "Board Preset"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    name: StringProperty()

    def execute(self, context):
        """Store the chosen preset name in the settings."""
        _settings(context).board_preset = self.name
        return {"FINISHED"}


class STUBSWITCH_OT_use_active_board(bpy.types.Operator):
    """Use the active object, a board made with Weathered Board, as the template tie"""

    bl_idname = "stub_switch.use_active_board"
    bl_label = "Use Active Board"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        """Only when the active object is a Weathered Board board."""
        return wb_bridge.is_board(context.active_object)

    def execute(self, context):
        """Set the template tie to the active board."""
        s = _settings(context)
        s.tie_source = "OBJECT"
        s.tie_object = context.active_object
        return {"FINISHED"}


# ---- tie plate presets ----

class STUBSWITCH_OT_apply_plate_preset(bpy.types.Operator):
    """Fill in every tie plate setting from this preset"""

    bl_idname = "stub_switch.apply_plate_preset"
    bl_label = "Apply Plate Preset"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    name: StringProperty()

    @classmethod
    def description(cls, context, properties):
        """Tooltip: the built-in preset's description, or a generic one for a saved preset."""
        preset = plates.get_builtin(properties.name)
        return preset.description if preset else f"Apply your saved plate preset '{properties.name}'"

    def execute(self, context):
        """Load the built-in or saved preset's values into the settings."""
        preset = plates.get_builtin(self.name)
        try:
            values = dict(preset.values) if preset else preset_store.load(preset_store.PLATE, self.name)
        except PresetError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        _settings(context).apply_plate_values(values, self.name)
        return {"FINISHED"}


class STUBSWITCH_OT_save_plate_preset(bpy.types.Operator):
    """Save the current tie plate settings as a preset of your own"""

    bl_idname = "stub_switch.save_plate_preset"
    bl_label = "Save Plate Preset"
    name: StringProperty(name="Name", description="Saving under an existing name replaces it")

    def invoke(self, context, event):
        """Ask for a name, suggesting the current saved preset (not a built-in one)."""
        current = _settings(context).plate_preset
        self.name = "" if plates.is_builtin(current) else current
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        """Save the plate settings under the name, refusing built-in names."""
        name = preset_store.clean_name(self.name)
        if not name:
            self.report({"ERROR"}, "Give the preset a name.")
            return {"CANCELLED"}
        if plates.is_builtin(name):
            self.report({"ERROR"}, f"'{name}' is a built-in preset. Pick another name.")
            return {"CANCELLED"}
        s = _settings(context)
        try:
            preset_store.save(preset_store.PLATE, name, s.plate_values())
        except PresetError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        s.plate_preset, s.plate_modified = name, False
        self.report({"INFO"}, f"Saved plate preset '{name}'.")
        return {"FINISHED"}


class STUBSWITCH_OT_remove_plate_preset(bpy.types.Operator):
    """Delete one of your saved plate presets"""

    bl_idname = "stub_switch.remove_plate_preset"
    bl_label = "Delete Plate Preset"
    bl_options = {"INTERNAL"}
    name: StringProperty()

    def invoke(self, context, event):
        """Ask before deleting."""
        return context.window_manager.invoke_confirm(
            self, event, title=f"Delete plate preset '{self.name}'?", confirm_text="Delete")

    def execute(self, context):
        """Delete the preset file, and clear the panel's preset name if it was this one."""
        try:
            preset_store.remove(preset_store.PLATE, self.name)
        except (PresetError, OSError) as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        s = _settings(context)
        if s.plate_preset == self.name:
            s.plate_preset = ""
        return {"FINISHED"}


# ---- switch presets ----

class STUBSWITCH_OT_apply_switch_preset(bpy.types.Operator):
    """Fill in every setting from this saved switch preset"""

    bl_idname = "stub_switch.apply_switch_preset"
    bl_label = "Apply Switch Preset"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    name: StringProperty()

    def execute(self, context):
        """Load the saved preset's values into the settings."""
        try:
            values = preset_store.load(preset_store.SWITCH, self.name)
        except PresetError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        _settings(context).apply_switch_values(values, self.name)
        return {"FINISHED"}


class STUBSWITCH_OT_save_switch_preset(bpy.types.Operator):
    """Save every current setting as a switch preset, for example 'HO #6 code 83 branch line'"""

    bl_idname = "stub_switch.save_switch_preset"
    bl_label = "Save Switch Preset"
    name: StringProperty(name="Name", description="Saving under an existing name replaces it")

    def invoke(self, context, event):
        """Ask for a name, suggesting the current switch preset."""
        self.name = _settings(context).switch_preset
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        """Save every setting under the name."""
        name = preset_store.clean_name(self.name)
        if not name:
            self.report({"ERROR"}, "Give the preset a name.")
            return {"CANCELLED"}
        s = _settings(context)
        try:
            preset_store.save(preset_store.SWITCH, name, s.switch_values())
        except PresetError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        s.switch_preset, s.switch_modified = name, False
        self.report({"INFO"}, f"Saved switch preset '{name}'.")
        return {"FINISHED"}


class STUBSWITCH_OT_remove_switch_preset(bpy.types.Operator):
    """Delete one of your saved switch presets"""

    bl_idname = "stub_switch.remove_switch_preset"
    bl_label = "Delete Switch Preset"
    bl_options = {"INTERNAL"}
    name: StringProperty()

    def invoke(self, context, event):
        """Ask before deleting."""
        return context.window_manager.invoke_confirm(
            self, event, title=f"Delete switch preset '{self.name}'?", confirm_text="Delete")

    def execute(self, context):
        """Delete the preset file, and clear the panel's preset name if it was this one."""
        try:
            preset_store.remove(preset_store.SWITCH, self.name)
        except (PresetError, OSError) as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        s = _settings(context)
        if s.switch_preset == self.name:
            s.switch_preset = ""
        return {"FINISHED"}


classes = (
    STUBSWITCH_OT_generate, STUBSWITCH_OT_new_seed, STUBSWITCH_OT_export_stl,
    STUBSWITCH_OT_set_frog_preset, STUBSWITCH_OT_set_board_preset, STUBSWITCH_OT_use_active_board,
    STUBSWITCH_OT_apply_plate_preset, STUBSWITCH_OT_save_plate_preset,
    STUBSWITCH_OT_remove_plate_preset,
    STUBSWITCH_OT_apply_switch_preset, STUBSWITCH_OT_save_switch_preset,
    STUBSWITCH_OT_remove_switch_preset,
)
