"""Model railroad scales and unit conversion. No bpy, so it can be tested.

The scale keys match the Switch Frog add-on's (HO, N, Fn3, LS ...), so the
scale is picked up from the frog preset. Prototype (full-size) lengths are
entered in inches or millimetres and kept as full-size millimetres; model
lengths are printed millimetres, full-size mm divided by N (as in 1:N).
"""

from __future__ import annotations

MM_PER_INCH = 25.4

# key: (menu label, N in 1:N, standard gauge in model mm)
SCALES: dict[str, tuple[str, float, float]] = {
    "Z": ("Z 1:220", 220.0, 6.5),
    "N": ("N 1:160", 160.0, 9.0),
    "TT": ("TT 1:120", 120.0, 12.0),
    "HO": ("HO 1:87.1", 87.1, 16.5),
    "OO": ("OO 1:76.2", 76.2, 16.5),
    "S": ("S 1:64", 64.0, 22.4),
    "O": ("O 1:48 (US)", 48.0, 31.75),
    "Fn3": ("Fn3 1:20.3 (3 ft gauge)", 20.3, 45.0),
    "F": ("F 1:20.3 (standard gauge)", 20.3, 70.69),
    "LS": ("Large Scale 1:29 (45 mm gauge)", 29.0, 45.0),
}
CUSTOM = "CUSTOM"


def scale_n(key: str, custom: float) -> float:
    """N in 1:N for a scale key (the custom ratio for CUSTOM)."""
    if key == CUSTOM or key not in SCALES:
        return float(custom)
    return SCALES[key][1]


def standard_gauge(key: str) -> float | None:
    """Standard gauge for a scale in model mm, or None for a custom scale."""
    entry = SCALES.get(key)
    return entry[2] if entry else None


def to_full_mm(value: float, units: str) -> float:
    """A prototype value in ``units`` ("IN" or "MM") as full-size millimetres."""
    return value * MM_PER_INCH if units == "IN" else value


def from_full_mm(value_mm: float, units: str) -> float:
    """Full-size millimetres back into ``units``."""
    return value_mm / MM_PER_INCH if units == "IN" else value_mm


def scale_label(key: str, custom: float) -> str:
    """Short text used in file names, e.g. 'HO' or '1-100'."""
    if key == CUSTOM or key not in SCALES:
        return f"1-{custom:g}"
    return key


def feet_inches(full_mm: float) -> str:
    """Full-size mm as feet and inches to the nearest 1/8 in, e.g. 8' 6\"."""
    inches = round(full_mm / MM_PER_INCH * 8) / 8
    if inches >= 12:
        feet, rest = divmod(inches, 12)
        return f"{int(feet)}' {rest:g}\"" if rest else f"{int(feet)}'"
    return f"{inches:g}\""
