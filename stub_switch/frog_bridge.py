"""The frog: Switch Frog Generator's API, and through it the rail profile.

Switch Frog Generator (1.0 or later, API version 1) publishes its public
API as ``sys.modules["switch_frog_api"]`` while it is enabled. A frog
preset sets the frog number (so the turnout's angle), the flangeway, the
frog's length, and a Model Rail Generator rail preset; that rail profile
sizes every rail of the turnout: the rail seats, tie plates, spikes and
the rail objects. Both add-ons must be enabled.

``frog_info`` gathers what the turnout needs from a frog preset, in model
mm: the frog angle, how far the frog's toe, heel and actual point are from
its theoretical point, and the frog's rail lines (gauge lines in the frog's
own frame with the side each rail lies on, see turnout.py).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

API_ALIAS = "switch_frog_api"
RAIL_ALIAS = "model_rail_api"


class FrogBridgeError(RuntimeError):
    """The frog or rail add-on is missing, or the frog preset can't be used."""


@dataclass
class FrogInfo:
    """What the turnout needs from a frog preset. Lengths in model mm."""

    name: str
    spec: object  # switch_frog FrogSpec
    profile: object  # model_rail RailProfile
    number: float
    angle_deg: float
    toe: float  # TP to the toe, along a gauge line
    heel: float  # TP to the heel, along a gauge line
    point: float  # TP to the actual point, along the frog's centreline
    flangeway: float
    flare_length: float
    flare_angle: float
    lines: list  # [(gauge polyline in the frog frame, body side)]
    solid: bool  # the frog has a fill or a base plate (one piece)
    base_plate: bool
    plate_thickness: float
    scale: str
    length: float


def find_api():
    """Switch Frog Generator's api module. Raises FrogBridgeError with a fix if it can't."""
    api = sys.modules.get(API_ALIAS)
    if api is None:
        raise FrogBridgeError("Switch Frog Generator isn't enabled. Install and enable it "
                              "(1.0 or later); it sets the frog angle and the rail.")
    if tuple(getattr(api, "API_VERSION", (0,)))[0] != 1:
        raise FrogBridgeError("This Switch Frog Generator's API version isn't supported. "
                              "Update Stub Switch Generator.")
    return api


def available() -> str:
    """An empty string if frogs and rail profiles can be used, otherwise why not."""
    try:
        api = find_api()
    except FrogBridgeError as err:
        return str(err)
    return api.rail_api_status()


def preset_names() -> tuple[list[str], list[str]]:
    """(built-in frog presets, your saved frog presets); both empty without the add-on."""
    try:
        api = find_api()
        return list(api.list_builtin_presets()), list(api.list_user_presets())
    except Exception:  # a broken preset file must not break the panel
        return [], []


def default_preset() -> str:
    """The frog preset the panel starts with (HO #6 Code 83), or "" without the add-on."""
    try:
        return find_api().default_preset_name()
    except FrogBridgeError:
        return ""


_cache: dict = {}


def frog_info(name: str) -> tuple[FrogInfo | None, str]:
    """The turnout's view of frog preset ``name``: (FrogInfo, "") or (None, what to do)."""
    if not name:
        return None, "Choose a frog preset."
    try:
        api = find_api()
        spec = api.get_preset(name)
    except FrogBridgeError as err:
        return None, str(err)
    except KeyError:
        return None, f'There is no frog preset named "{name}".'
    try:
        key = (name, repr(spec.to_dict()))
        if key in _cache:
            return _cache[key], ""
        profile = api.resolve_rail_profile(None, spec)
        lay = api.frog_layout(spec, profile)
    except Exception as err:  # FrogError: no rail add-on, missing rail preset, bad settings
        return None, f'Frog preset "{name}": {err}'
    if lay.errors:
        return None, f'Frog preset "{name}": ' + "; ".join(lay.errors)
    t, k = lay.t, lay.k
    lines = [
        (list(lay.left_wing), 1),  # wing rail along the straight route's left rail
        (list(lay.right_wing), -1),  # wing rail along the diverging route's inner rail
        ([(lay.y_point * t, lay.y_point), (lay.y_heel * t, lay.y_heel)], 1),  # straight point rail
        ([(-lay.y_point * t, lay.y_point), (-lay.y_heel * t, lay.y_heel)], -1),  # diverging
    ]
    info = FrogInfo(
        name=name, spec=spec, profile=profile, number=spec.frog_number,
        angle_deg=lay.angle_deg, toe=-lay.y_toe * k, heel=lay.y_heel * k, point=lay.y_point,
        flangeway=spec.flangeway_width, flare_length=spec.flare_length,
        flare_angle=spec.flare_angle, lines=lines,
        solid=spec.fill != "NONE" or spec.base_plate, base_plate=spec.base_plate,
        plate_thickness=spec.plate_thickness, scale=spec.scale or "", length=lay.length)
    if len(_cache) > 50:
        _cache.clear()
    _cache[key] = info
    return info, ""


def create_frog(info: FrogInfo, name: str, collection, location, rotation_z_deg: float):
    """Build the frog as one merged solid with Switch Frog Generator and return the object."""
    api = find_api()
    return api.create_frog_object(info.spec, info.profile, name=name, collection=collection,
                                  location=location, rotation_z_deg=rotation_z_deg,
                                  alignment="CENTERED", merged=True)


def rail_api():
    """Model Rail Generator's api module (needed by the frog, so normally present), or None."""
    api = sys.modules.get(RAIL_ALIAS)
    if api is None or tuple(getattr(api, "API_VERSION", (0,)))[0] != 1:
        return None
    return api
