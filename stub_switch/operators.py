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
    ("ENTIRE", "Entire Switch",
     "The fixed rail section with all its rails, guard rails and the frog in one file, the "
     "movable rail section's ties in another, and each movable rail in a file of its own"),
    ("TIES", "Tie Strips Only",
     "The movable and fixed rail sections' tie strips, two files; optionally with the frog and "
     "guard rails in the fixed section's file, so you can lay your own rail"),
    ("EACH", "Every Object to Its Own File",
     "Each tie strip section, rail, guard rail and the frog in a file of its own"),
]


def _safe(name: str) -> str:
    """``name`` with characters a file name can't hold replaced by _ (spaces too)."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


class STUBSWITCH_OT_export_stl(bpy.types.Operator, ExportHelper):
    """Export the selected stub switches as STL files in millimetres: the tie strip as two files (movable and fixed rail sections), with the rails and frog as you choose"""

    bl_idname = "stub_switch.export_stl"
    bl_label = "Export STL"
    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})
    export_what: EnumProperty(name="Export", items=EXPORT_WHAT, default="TIES",
                              description="What to write for each selected turnout")
    frog_and_guards: BoolProperty(
        name="Include Frog and Guard Rails", default=True,
        description="Tie Strips Only: put the frog and guard rails in the fixed rail section's "
                    "file (needs Include Frog)")

    @classmethod
    def poll(cls, context):
        """Only available when a stub switch, or a rail or frog on one, is selected."""
        return bool(build.selected_switches(context))

    def invoke(self, context, event):
        """Open the file browser on the default file name, next to the .blend file."""
        s = _settings(context)
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        self.filepath = os.path.join(folder, build.file_name(s))
        self.export_what = s.export_what
        self.frog_and_guards = s.export_frog_and_guards
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        """The export options, in the file browser's side panel."""
        col = self.layout.column()
        col.label(text="Export:")
        col.prop(self, "export_what", expand=True)
        sub = col.column()
        sub.enabled = self.export_what == "TIES"
        sub.prop(self, "frog_and_guards")
        col.separator()
        hint = col.column()
        hint.scale_y = 0.8
        hint.label(text="The tie strip is written as two", icon="INFO")
        hint.label(text="files, ending _fixed and _movable.")
        if self.export_what == "ENTIRE":
            hint.label(text="Each movable rail gets its own file.")
        elif self.export_what == "EACH":
            hint.label(text="Each rail, guard rail and the frog")
            hint.label(text="get their own files too.")
        hint.label(text="Each gauge bar gets its own file.")

    def execute(self, context):
        """Write the files ``build.export_plan`` lists for each selected turnout."""
        s = _settings(context)
        if s.export_what != self.export_what:
            s.export_what = self.export_what
        if s.export_frog_and_guards != self.frog_and_guards:
            s.export_frog_and_guards = self.frog_and_guards
        switches = build.selected_switches(context)
        stem, ext = os.path.splitext(self.filepath)
        count, missing = 0, []
        try:
            for obj in switches:
                base = stem if len(switches) == 1 else f"{stem}_{_safe(obj.name)}"
                kinds = {p.get(build.PART_TAG) for p in build.parts_of(obj)}
                if self.export_what == "ENTIRE" and "RAIL" not in kinds:
                    missing.append(f"{obj.name} has no rail (tick Include Rail)")
                if self.export_what == "TIES" and self.frog_and_guards and "FROG" not in kinds:
                    missing.append(f"{obj.name} has no frog (tick Include Frog)")
                for suffix, objs in build.export_plan(obj, self.export_what,
                                                      self.frog_and_guards):
                    build.export_stl(context, objs, f"{base}_{_safe(suffix)}{ext}")
                    count += 1
        except RuntimeError as err:
            self.report({"ERROR"}, f"Export failed: {err}")
            return {"CANCELLED"}
        what = dict((k, n) for k, n, _d in EXPORT_WHAT)[self.export_what].lower()
        note = (". " + "; ".join(missing)) if missing else ""
        self.report({"WARNING"} if missing else {"INFO"},
                    f"Exported {what} for {len(switches)} turnout(s): {count} files starting "
                    f"{os.path.basename(stem)}{note}")
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
