"""The template tie: Weathered Board's API, and building and caching boards.

The ties are Weathered Board boards. The template is either a board you
made with the Weathered Board panel (any board object in the scene), or a
Weathered Board preset. Either way it gives the ties' look (grain, rounding,
weathering) and the standard tie's full-size length, width and thickness;
every tie of the turnout is built with that look, width and thickness at
the length the turnout needs there.

Weathered Board (0.1.5 or later) provides ``api.build_board``. Blender
extensions can't declare dependencies on each other, so the add-on is
found at runtime among the enabled add-ons. Boards are simplified
(Decimate, collapse) to about ``max_triangles`` each and cached, so a
rebuild with Lock Seed on reuses them.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass

import bpy
import numpy as np

MIN_VERSION_TEXT = "Weathered Board 0.1.5 or later"
MM_PER_INCH = 25.4
SIZE_KEYS = ("units", "length", "width", "thickness")


class BridgeError(RuntimeError):
    """Weathered Board is missing, too old, or couldn't build a board."""


@dataclass(frozen=True)
class Board:
    """One simplified board, as Weathered Board orients it (length on X)."""

    vertices: np.ndarray
    triangles: np.ndarray
    face_depth: dict


@dataclass(frozen=True)
class Template:
    """The template tie: its look, full-size size in mm, and a name for messages."""

    look: dict
    length: float
    width: float
    thickness: float
    label: str


def find_api():
    """Weathered Board's api module. Raises BridgeError with a fix if it can't."""
    for name in bpy.context.preferences.addons.keys():
        if name == "weathered_board" or name.endswith(".weathered_board"):
            try:
                api = importlib.import_module(name + ".api")
            except ImportError:
                raise BridgeError(f"Weathered Board is enabled but too old. Install "
                                  f"{MIN_VERSION_TEXT}.") from None
            if tuple(getattr(api, "API_VERSION", (0, 0)))[0] != 1:
                raise BridgeError("This Weathered Board's API version isn't supported. "
                                  "Update Stub Switch Generator.")
            return api
    raise BridgeError(f"Weathered Board isn't enabled. Install and enable {MIN_VERSION_TEXT}.")


def available() -> str:
    """An empty string if Weathered Board can be used, otherwise the reason it can't."""
    try:
        find_api()
    except BridgeError as err:
        return str(err)
    return ""


def preset_names() -> list[tuple[str, str]]:
    """(name, description) for every Weathered Board preset, or [] if unavailable."""
    try:
        return [(p.name, p.description) for p in find_api().list_presets()]
    except BridgeError:
        return []


def is_board(obj) -> bool:
    """True when ``obj`` is a board made with the Weathered Board panel."""
    settings = getattr(obj, "weathered_board", None) if obj is not None else None
    return bool(settings and getattr(settings, "is_board", False))


def _keys(api) -> list[str]:
    """Every look and size setting Weathered Board takes (the keys of a preset)."""
    first = api.list_presets()[0].name
    return list(api.get_preset_values(first).keys())


def _size(values: dict) -> tuple[float, float, float]:
    """A board's (length, width, thickness) in full-size mm from its settings."""
    k = MM_PER_INCH if values.get("units", "IN") == "IN" else 1.0
    return (float(values["length"]) * k, float(values["width"]) * k,
            float(values["thickness"]) * k)


def template(source: str, obj, preset: str) -> tuple[Template | None, str]:
    """The template tie from a board object (``source`` "OBJECT") or a preset ("PRESET").

    Returns (Template, "") or (None, what to do).
    """
    try:
        api = find_api()
    except BridgeError as err:
        return None, str(err)
    if source == "OBJECT":
        if obj is None:
            return None, ("Pick the template tie: a board made with the Weathered Board panel "
                          "(Add Board), sized as a standard tie.")
        if not is_board(obj):
            return None, f'"{obj.name}" is not a Weathered Board board; pick one made with Add Board.'
        settings = obj.weathered_board
        values = {k: getattr(settings, k) for k in _keys(api) if hasattr(settings, k)}
        label = obj.name
    else:
        if not preset:
            return None, "Choose a Weathered Board preset for the ties."
        try:
            values = dict(api.get_preset_values(preset))
        except Exception as err:  # api.BoardError: preset deleted or unreadable
            return None, f'Weathered Board preset "{preset}": {err}'
        label = preset
    try:
        length, width, thickness = _size(values)
    except (KeyError, TypeError, ValueError):
        return None, f'The template tie "{label}" has no size.'
    look = {k: v for k, v in values.items() if k not in SIZE_KEYS}
    return Template(look, length, width, thickness, label), ""


_cache: dict[tuple, Board] = {}
CACHE_LIMIT = 400


def clear_cache() -> None:
    """Forget every cached board."""
    _cache.clear()


def get_board(api, tmpl: Template, length_mm: float, scale: float, printer: str, seed: int,
              max_triangles: int, thickness_mm: float | None = None) -> Board:
    """One board with the template's look, at ``length_mm`` (full size), from the cache or new.

    ``thickness_mm`` (full size) replaces the template's thickness, for a
    tie lowered under a headblock plate.
    """
    look = json.dumps(tmpl.look, sort_keys=True, default=str)
    thickness = tmpl.thickness if thickness_mm is None else thickness_mm
    key = (look, round(length_mm, 6), round(tmpl.width, 6), round(thickness, 6),
           round(scale, 6), printer, int(seed), int(max_triangles))
    board = _cache.get(key)
    if board is not None:
        return board
    try:
        mesh = api.build_board(values=tmpl.look, length_mm=length_mm, width_mm=tmpl.width,
                               thickness_mm=thickness, scale=scale, printer=printer,
                               seed=seed, weather_bottom=False)
    except api.BoardError as err:
        raise BridgeError(f'Template tie "{tmpl.label}": {err}') from None
    verts, tris = decimate(np.asarray(mesh.vertices), np.asarray(mesh.triangles), max_triangles)
    board = Board(verts, tris, dict(mesh.face_depth))
    if len(_cache) >= CACHE_LIMIT:
        _cache.clear()
    _cache[key] = board
    return board


def mesh_from_arrays(name: str, verts: np.ndarray, tris: np.ndarray) -> bpy.types.Mesh:
    """A new Blender mesh from vertex and triangle arrays."""
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    mesh.loops.add(len(tris) * 3)
    mesh.loops.foreach_set("vertex_index", tris.astype(np.int32).ravel())
    mesh.polygons.add(len(tris))
    mesh.polygons.foreach_set("loop_start", np.arange(0, len(tris) * 3, 3, dtype=np.int32))
    mesh.update()
    mesh.validate()
    return mesh


def arrays_from_mesh(mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray]:
    """Vertex and triangle arrays from a Blender mesh."""
    mesh.calc_loop_triangles()
    verts = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    return verts.reshape(-1, 3).astype(np.float64), tris.reshape(-1, 3)


def decimate(verts: np.ndarray, tris: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    """Simplify a mesh to about ``target`` triangles with Blender's Decimate (collapse)."""
    if len(tris) <= target:
        return verts, tris
    mesh = mesh_from_arrays("_stub_switch_decimate", verts, tris)
    obj = bpy.data.objects.new("_stub_switch_decimate", mesh)
    bpy.context.scene.collection.objects.link(obj)
    try:
        mod = obj.modifiers.new("Decimate", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.use_collapse_triangulate = True
        mod.ratio = target / len(tris)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        result = evaluated.to_mesh()
        out = arrays_from_mesh(result)
        evaluated.to_mesh_clear()
    finally:
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
    return out
