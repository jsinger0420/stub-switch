"""Add-on preferences: printability thresholds and the grain-depth warning."""

import bpy
from bpy.props import FloatProperty

from .layout import DEFAULT_THRESHOLDS


def _t(printer, key, label, desc):
    """A threshold property, defaulting to the value in layout.DEFAULT_THRESHOLDS."""
    return FloatProperty(name=label + " (mm)", description=desc + ", in model millimetres",
                         min=0.0, soft_max=2.0,
                         precision=3, default=DEFAULT_THRESHOLDS[printer][key])


class STUBSWITCH_Preferences(bpy.types.AddonPreferences):
    """Thresholds behind the printability warnings, one set per printer type."""

    bl_idname = __package__

    grain_limit: FloatProperty(
        name="Grain Depth Warning", subtype="PERCENTAGE", min=0.0, max=100.0, default=20.0,
        description="Warn when the grain cuts deeper than this share of the tie height")

    resin_hole: _t("RESIN", "hole", "Smallest Hole", "Smallest spike hole a resin printer prints")
    resin_plate: _t("RESIN", "plate", "Thinnest Plate", "Thinnest tie plate that shows on resin")
    resin_connector: _t("RESIN", "connector", "Thinnest Connector",
                        "Thinnest connector a resin printer prints reliably")
    resin_gap: _t("RESIN", "gap", "Smallest Gap", "Smallest gap between ties that stays open on resin")
    resin_shoulder: _t("RESIN", "shoulder", "Smallest Shoulder", "Smallest plate shoulder on resin")

    fdm_hole: _t("FDM", "hole", "Smallest Hole", "Smallest spike hole an FDM printer prints")
    fdm_plate: _t("FDM", "plate", "Thinnest Plate", "Thinnest tie plate that shows on FDM")
    fdm_connector: _t("FDM", "connector", "Thinnest Connector",
                      "Thinnest connector an FDM printer prints reliably")
    fdm_gap: _t("FDM", "gap", "Smallest Gap", "Smallest gap between ties that stays open on FDM")
    fdm_shoulder: _t("FDM", "shoulder", "Smallest Shoulder", "Smallest plate shoulder on FDM")

    def thresholds(self, printer: str) -> dict:
        """This printer's thresholds, keyed like layout.DEFAULT_THRESHOLDS."""
        p = "resin" if printer == "RESIN" else "fdm"
        return {k: getattr(self, f"{p}_{k}") for k in ("hole", "plate", "connector", "gap", "shoulder")}

    def draw(self, context):
        """The grain limit, then resin and FDM thresholds side by side."""
        layout = self.layout
        layout.prop(self, "grain_limit")
        row = layout.row()
        for title, p in (("Resin", "resin"), ("FDM", "fdm")):
            col = row.column()
            col.label(text=title)
            for k in ("hole", "plate", "connector", "gap", "shoulder"):
                col.prop(self, f"{p}_{k}")


def get(context=None):
    """This add-on's preferences, or None when not registered as an add-on."""
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None
