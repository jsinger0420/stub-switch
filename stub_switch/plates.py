"""Tie plate presets by era. No bpy.

A plate preset holds every tie plate setting. Lengths are stored in
inches, whatever units the panel shows, so a preset means the same thing
for every modeler. Shoulder clearance is not part of a preset: it depends
on the modeler's rail and printer, not on the era.

The same built-in presets as Tie Strip. Sources for the built-in values are listed
in the Tie Strip design doc. Values marked "estimate" there have
no published source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PLATE_LENGTH_KEYS = ("plate_length", "plate_width", "plate_thickness", "plate_bias",
                     "shoulder_height", "shoulder_width")
PLATE_KEYS = ("plates_on", "shoulders") + PLATE_LENGTH_KEYS


@dataclass(frozen=True)
class PlatePreset:
    """A built-in tie plate preset: menu name, tooltip, and the setting values."""

    name: str
    description: str
    values: Mapping[str, Any]  # lengths in inches


def _plate(on, length, width, thick, bias, shoulders, sh=0.5, sw=0.75):
    """A preset's values dict from positional sizes in inches (keys as in PLATE_KEYS)."""
    return {"plates_on": on, "plate_length": length, "plate_width": width,
            "plate_thickness": thick, "plate_bias": bias, "shoulders": shoulders,
            "shoulder_height": sh, "shoulder_width": sw}


BUILTIN_PLATES: tuple[PlatePreset, ...] = (
    PlatePreset("No plates",
                "Rail spiked straight to the ties: most lines before about 1900, "
                "and many branch lines and short lines later",
                _plate(False, 14.0, 7.75, 0.75, 1.0, "DOUBLE")),
    PlatePreset("Early flat plate",
                "About 1890-1910: small flat plate with no shoulders, 6 x 9 in, 3/16 in thick "
                "(Servis plate)",
                _plate(True, 9.0, 6.0, 0.1875, 0.0, "NONE")),
    PlatePreset("Single shoulder",
                "About 1910-1944: field-side shoulder only. Size and thickness are estimates",
                _plate(True, 10.0, 7.0, 0.5, 1.0, "FIELD")),
    PlatePreset("AREA double shoulder",
                "1944 on: AREA standard double-shoulder plate, 7-3/4 x 11 in. "
                "Thickness is an estimate",
                _plate(True, 11.0, 7.75, 0.625, 1.0, "DOUBLE")),
    PlatePreset("Modern heavy",
                "Today's heavy main lines: double-shoulder plate, 7-3/4 x 14 in. "
                "Thickness is an estimate",
                _plate(True, 14.0, 7.75, 0.75, 1.0, "DOUBLE")),
)


def get_builtin(name: str) -> PlatePreset | None:
    """The built-in preset with exactly this name, or None (e.g. for a saved preset)."""
    for p in BUILTIN_PLATES:
        if p.name == name:
            return p
    return None


def is_builtin(name: str) -> bool:
    """True if ``name`` matches a built-in preset, ignoring case, so saves can't shadow one."""
    return name.casefold() in {p.name.casefold() for p in BUILTIN_PLATES}
