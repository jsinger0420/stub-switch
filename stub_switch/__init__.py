"""Stub Switch Generator: 3D-printable model railroad stub switches (stub turnouts).

Builds the tie strip for a stub switch: ties of the lengths the turnout
needs, made by Weathered Board from a template tie, joined by low
connectors, with optional tie plates (slide plates under the movable
rails), spike holes or printed spikes, and optionally the rails (Model Rail
Generator) and the frog (Switch Frog Generator) laid on it. A Switch Frog
preset sets the turnout's angle and the rail profile. Exported as an STL in
millimetres.

The geometry (geom2d.py, turnout.py, layout.py, meshgen.py, plates.py,
scales.py) is plain Python with no bpy, so it can be tested outside
Blender. Blender modules are only imported in ``register``.
"""

_modules = None


def _load():
    """Import the Blender-only modules; returns (prefs, properties, operators, ui)."""
    from . import build, operators, prefs, properties, ui  # noqa: F401
    return prefs, properties, operators, ui


def _classes():
    """Every Blender class to register, in registration order."""
    prefs, properties, operators, ui = _load()
    return ((prefs.STUBSWITCH_Preferences, properties.STUBSWITCH_Settings)
            + operators.classes + ui.classes)


def register():
    """Register the classes and add the Stub Switch settings to every scene."""
    import bpy
    for cls in _classes():
        bpy.utils.register_class(cls)
    _load()[1].register()


def unregister():
    """Remove the scene settings, unregister the classes and drop cached boards."""
    import bpy
    from . import wb_bridge
    _load()[1].unregister()
    for cls in reversed(_classes()):
        bpy.utils.unregister_class(cls)
    wb_bridge.clear_cache()
