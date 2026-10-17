"""Building the stub switch objects and exporting them.

1. Read the frog preset (Switch Frog Generator) and the template tie
   (Weathered Board); lay out the turnout (turnout.py) and its ties
   (layout.py), and stop on any error.
2. Build the ties with Weathered Board: one board per tie, each at the
   length the turnout needs there, with the template's look, width and
   thickness (simplified and cached, wb_bridge.py).
3. Re-lay with the boards' real grain depth, which sets the connector
   overlap and the rail seat fill.
4. Make the connectors, rail seat pads, tie plates, shoulders, and either
   hole cutters or printed spikes; mirror everything for a right-hand
   turnout.
5. Join everything with Boolean modifiers (Manifold solver, falling back
   to Exact), cut the spike holes, clean up and check it is watertight.
   With Two Pieces on, this is done twice: the fixed rail piece (the
   turnout's main object) and the movable rail piece (its child), which
   carries the joint tabs; the sockets are cut in the fixed piece.
6. With Include Rail, sweep the rails with Model Rail Generator; with
   Include Frog, build the frog with Switch Frog Generator at its place,
   and the guard rails too even when Include Rail is off.
   Both are parented to the tie strip and left out of a ties-only export.
7. Place the new turnout at the 3D cursor and select it.

Like Tie Strip, every Generate adds a new turnout and leaves earlier ones
alone, and uses a new random seed unless Lock Seed is on.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field

import bmesh
import bpy
import numpy as np

from . import frog_bridge, geom2d, guard_hardware, layout, meshgen, prefs, turnout, wb_bridge
from .scales import scale_label

RESULT_NAME = "StubSwitch"
TAG = "stub_switch"  # custom property marking the turnout's tie strip
MOVABLE_TAG = "stub_switch_movable"  # on a rail: True for the movable rails
PART_TAG = "stub_switch_part"  # rails ("RAIL"), guard rails ("GUARD"), frog ("FROG"),
# movable ties ("TIES"), gauge bars ("GAUGE_BAR")
RAIL_MATERIAL = "Stub Switch Rail"
SETTINGS_KEY = "stub_switch_settings"
SEED_LIMIT = 2**31


class BuildError(RuntimeError):
    """The turnout can't be built; the message says why and how to fix it."""


@dataclass
class BuildResult:
    """The built tie strip object, warnings to show, and build statistics."""

    obj: bpy.types.Object
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def set_scene_millimetres(scene) -> None:
    """1 Blender unit = 1 mm, so the STL comes out in millimetres."""
    us = scene.unit_settings
    us.system = "METRIC"
    us.length_unit = "MILLIMETERS"
    us.scale_length = 0.001


def is_switch(obj) -> bool:
    """True when ``obj`` is a turnout tie strip made by Generate."""
    return obj is not None and obj.type == "MESH" and bool(obj.get(TAG))


def is_part(obj) -> bool:
    """True when ``obj`` is a rail or frog laid on a turnout."""
    return obj is not None and obj.type == "MESH" and bool(obj.get(PART_TAG))


def parts_of(strip) -> list:
    """The rail and frog objects on ``strip`` (not its other tie piece)."""
    return sorted((o for o in strip.children if is_part(o) and o.get(PART_TAG) != "TIES"),
                  key=lambda o: o.name)


def tie_pieces(strip) -> list:
    """The printed tie strip pieces: ``strip`` (the fixed piece) and its movable piece, if split."""
    return [strip] + [o for o in strip.children if is_part(o) and o.get(PART_TAG) == "TIES"]


def selected_switches(context) -> list:
    """The selected turnouts, each once; a selected rail or frog counts as its turnout."""
    out = []
    for o in context.selected_objects:
        if is_part(o) and is_switch(o.parent):
            o = o.parent
        if is_switch(o) and o not in out:
            out.append(o)
    return out


EXPORT_ENTIRE, EXPORT_TIES, EXPORT_EACH = "ENTIRE", "TIES", "EACH"


def is_movable_rail(obj) -> bool:
    """True for a movable rail (each is printed or bent on its own)."""
    if obj.get(PART_TAG) != "RAIL":
        return False
    tag = obj.get(MOVABLE_TAG)
    return bool(tag) if tag is not None else " Movable " in f" {obj.name} "


def part_role(strip, part) -> str:
    """A part's name without its turnout's name, e.g. "Movable L" or "Frog"."""
    name = part.name
    return (name[len(strip.name):].strip() if name.startswith(strip.name) else "") or name


def export_plan(strip, what: str, frog_and_guards: bool = True) -> list[tuple[str, list]]:
    """The files to write for ``strip``: (file name suffix, objects in that file).

    The tie strip is always two files, "fixed" and "movable" (one, "ties",
    for a turnout generated in one piece). "ENTIRE": the fixed file also
    holds every fixed rail, the guard rails and the frog; each movable rail
    is a file of its own. "TIES": just the tie strip, with the frog and
    guard rails in the fixed file if ``frog_and_guards``. "EACH": every
    object (tie pieces, rails, guard rails, frog) in a file of its own.
    """
    pieces = tie_pieces(strip)
    fixed, movable = pieces[0], (pieces[1] if len(pieces) > 1 else None)
    bars = [(part_role(strip, p), [p]) for p in parts_of(strip)
            if p.get(PART_TAG) == "GAUGE_BAR"]  # printed on their own: always their own files
    parts = [p for p in parts_of(strip) if p.get(PART_TAG) != "GAUGE_BAR"]
    moving = [p for p in parts if is_movable_rail(p)]
    others = [p for p in parts if p not in moving]
    own = [(part_role(strip, p), [p]) for p in parts]
    with_fixed = []
    if what == EXPORT_ENTIRE:
        with_fixed = others
        own = [(part_role(strip, p), [p]) for p in moving]
    elif what == EXPORT_TIES:
        if frog_and_guards:
            with_fixed = [p for p in others if p.get(PART_TAG) in ("FROG", "GUARD")]
        own = []
    if movable is None:
        return [("ties", [fixed] + with_fixed)] + own + bars
    return [("fixed", [fixed] + with_fixed), ("movable", [movable])] + own + bars


def _new_object(name, verts, tris, coll) -> bpy.types.Object:
    """A new mesh object from vertex and triangle arrays, linked to ``coll``."""
    obj = bpy.data.objects.new(name, wb_bridge.mesh_from_arrays(name, verts, tris))
    coll.objects.link(obj)
    return obj


def _boolean(base, adds, cutters, solver) -> tuple[np.ndarray, np.ndarray]:
    """Union ``adds`` into ``base``, subtract ``cutters``; return the result arrays."""
    base.modifiers.clear()
    for op, objs in (("UNION", adds), ("DIFFERENCE", cutters)):
        for obj in objs:
            mod = base.modifiers.new(f"{op.title()} {obj.name}", "BOOLEAN")
            mod.operation = op
            mod.operand_type = "OBJECT"
            mod.object = obj
            mod.solver = solver
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = base.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        verts, tris = wb_bridge.arrays_from_mesh(mesh)
    finally:
        evaluated.to_mesh_clear()
    base.modifiers.clear()
    return verts, tris


def _solver() -> str:
    """Manifold where this Blender has it (4.5+), otherwise Exact."""
    items = bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items.keys()
    return "MANIFOLD" if "MANIFOLD" in items else "EXACT"


def _clean(mesh: bpy.types.Mesh) -> int:
    """Merge duplicate points, fix normals, drop loose bits. Returns open-edge count."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        open_edges = sum(1 for e in bm.edges if not e.is_manifold)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return open_edges


def _rail_material() -> bpy.types.Material:
    """The shared steel-grey material for rails and frogs, made on first use."""
    mat = bpy.data.materials.get(RAIL_MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(RAIL_MATERIAL)
        mat.diffuse_color = (0.35, 0.33, 0.32, 1.0)
        mat.metallic, mat.roughness = 0.9, 0.45
    return mat


def _boards(s, api, tmpl, lay, scale, rng, seed, progress):
    """A board for every tie, and the variation of each: (boards, choice, turns, offsets, yaws)."""
    n = len(lay.ties)
    lj, ej = s.full_mm("length_jitter"), s.full_mm("end_jitter") / scale
    lengths = [tie.length * scale for tie in lay.ties]  # full-size mm
    thick = [tmpl.thickness - tie.lowered * scale for tie in lay.ties]
    if n <= s.pool_threshold:
        jobs = [(lengths[i] + rng.uniform(-lj, lj), thick[i]) for i in range(n)]
        choice = list(range(n))
    else:
        groups: dict[tuple, list[int]] = {}
        for i, length in enumerate(lengths):
            groups.setdefault((round(length, 1), round(thick[i], 3)), []).append(i)
        jobs, choice = [], [0] * n
        for (length, th), ties in groups.items():
            first = len(jobs)
            k = min(s.pool_size, len(ties))
            jobs += [(length + rng.uniform(-lj, lj), th) for _ in range(k)]
            for i in ties:
                choice[i] = first + rng.randrange(k)
    boards = []
    for j, (length, th) in enumerate(jobs):
        boards.append(wb_bridge.get_board(api, tmpl, length, scale, s.printer,
                                          (seed + j) % SEED_LIMIT, s.max_triangles,
                                          None if abs(th - tmpl.thickness) < 1e-9 else th))
        if progress:
            progress(j + 1, len(jobs) + 2)
    turns = [s.random_turn and rng.random() < 0.5 for _ in range(n)]
    offsets = [rng.uniform(-ej, ej) for _ in range(n)]
    yaws = [rng.uniform(-s.yaw_jitter, s.yaw_jitter) for _ in range(n)]
    return boards, choice, turns, offsets, yaws


def add_rails(s, info, t, lay, strip, coll, mirror: bool,
              guards_only: bool = False) -> tuple[list, str]:
    """Sweep the rails with Model Rail Generator and parent them to ``strip``.

    With ``guards_only`` just the guard rails (they go with the frog when
    Include Rail is off). Returns (rail objects, warning text or "").
    """
    api = frog_bridge.rail_api()
    if api is None:
        return [], "Rail not added: enable Model Rail Generator."
    rails = dict(t.rails)
    if s.points_set == "DIVERGING":
        rails.update(t.thrown_rails)
    mat = _rail_material()
    extras, warn = _guard_hardware(s, info, t, lay, rails) if s.guard_brackets else ({}, "")
    objs = []
    for name, pts in rails.items():
        key = name
        guard = name.startswith("Guard")
        if guards_only and not guard:
            continue
        pts = geom2d.clip_x(pts, lay.x_rail0, lay.x_rail1)
        if len(pts) < 2:
            continue
        if mirror:
            pts = geom2d.mirror(pts)
            name = name.replace(" L", " _R").replace(" R", " L").replace(" _R", " R")
        path = {"kind": "POLYLINE", "points": [(x, y, lay.seat) for x, y in pts], "closed": False}
        try:
            md = api.generate_rail_mesh(info.profile, path)
        except (ValueError, TypeError) as err:
            return objs, f"Rail '{name}' not added: {err}"
        verts = np.array(md.vertices, dtype=np.float64)
        tris = np.array(md.triangles(), dtype=np.int32)
        if extras.get(key):
            verts, tris = _with_parts(verts, tris, extras[key], mirror, coll)
        obj = _new_object(f"{strip.name} {name}", verts, tris, coll)
        if extras.get(key):
            _shade(obj.data, 35.0)  # rounded head corners smooth, web and foot flat
        obj.data.materials.append(mat)
        obj.parent = strip
        obj[PART_TAG] = "GUARD" if guard else "RAIL"
        obj[MOVABLE_TAG] = name.startswith("Movable")
        obj["rail_length_mm"] = round(float(geom2d.lengths(pts)[-1]), 3)
        objs.append(obj)
    return objs, warn


def _guard_hardware(s, info, t, lay, rails) -> tuple[dict, str]:
    """The guard rail brackets, nuts and washers and the running rails' bolt heads, by rail."""
    p = info.profile
    rail = guard_hardware.RailSize(
        height=p.height, head_width=p.head_width, head_depth=p.head_depth, web=p.web_thickness,
        base_width=p.base_width, base_thickness=p.base_thickness,
        base_edge=p.base_edge_thickness)
    spec = s.turnout_spec(info)
    b = guard_hardware.BracketSpec(
        scale_n=s.scale_n(), flangeway=info.flangeway, count=s.guard_bracket_count,
        length=s.full_mm("guard_bracket_length"), flange_depth=s.flange_depth,
        scale_name=info.scale or s.scale, flare_length=spec.model(spec.guard_flare_length))
    guards = {k: rails[k] for k in guard_hardware.RUNNING_RAIL if k in rails}
    out, warnings = guard_hardware.hardware(guards, b, rail, lay.seat)
    return out, " ".join(warnings)


def _with_parts(verts, tris, parts, mirror: bool, coll):
    """A rail's mesh joined (Manifold union) with its brackets, nuts or bolt heads."""
    if mirror:
        parts = [guard_hardware.mirror(v, t) for v, t in parts]
    pv = np.concatenate([v for v, _t in parts])
    offs = np.cumsum([0] + [len(v) for v, _t in parts[:-1]])
    pt = np.concatenate([t + o for (_v, t), o in zip(parts, offs)])
    base = _new_object("_ss_rail", verts, tris, coll)
    add = _new_object("_ss_rail_parts", pv, pt, coll)
    try:
        v2, t2 = _boolean(base, [add], [], _solver())
    finally:
        for o in (base, add):
            mesh = o.data
            bpy.data.objects.remove(o)
            bpy.data.meshes.remove(mesh)
    if len(t2) < len(tris):  # the union failed: keep the parts as separate shells
        return np.concatenate([verts, pv]), np.concatenate([tris, pt + len(verts)])
    return v2, t2


def add_gauge_bars(lay, strip, coll, mirror: bool) -> list:
    """Each gauge bar as an object of its own, parented to ``strip`` (they print separately)."""
    objs = []
    for i, bar in enumerate(lay.gauge_bars, 1):
        first, rest = meshgen.boxes(bar.boxes[:1]), meshgen.boxes(bar.boxes[1:])
        holes = meshgen.cylinders(bar.holes) if bar.holes else None
        if mirror:
            first, rest = meshgen.mirror_y(first), meshgen.mirror_y(rest)
            holes = meshgen.mirror_y(holes) if holes is not None else None
        name = f"{strip.name} Gauge Bar {i}"
        # Join the bar and its hooks (one box each) and cut the stand's bolt hole.
        base = _new_object(name, *first, coll)
        add = _new_object("_ss_bar_hooks", *rest, coll)
        cut = [_new_object("_ss_bar_hole", *holes, coll)] if holes is not None else []
        try:
            verts, tris = _boolean(base, [add], cut, _solver())
        finally:
            for o in [add] + cut:
                mesh = o.data
                bpy.data.objects.remove(o)
                bpy.data.meshes.remove(mesh)
        if len(tris) == 0:  # keep the pieces as they are rather than nothing
            verts, tris = meshgen.combine(first, rest)
        old = base.data
        base.data = wb_bridge.mesh_from_arrays(name, verts, tris)
        bpy.data.meshes.remove(old)
        _clean(base.data)
        _shade(base.data)
        base.parent = strip
        base[PART_TAG] = "GAUGE_BAR"
        base["stand_extension"] = bar.stand
        objs.append(base)
    return objs


def add_frog(info, t, lay, strip, coll, mirror: bool) -> tuple[object, str]:
    """Build the frog with Switch Frog Generator at the frog's place and parent it to ``strip``."""
    half = math.degrees(t.frog_angle) / 2
    x, y = t.tp
    rot = (-half if mirror else half) - 90.0
    if mirror:
        y = -y
    try:
        obj = frog_bridge.create_frog(info, f"{strip.name} Frog", coll, (x, y, lay.seat), rot)
    except Exception as err:  # FrogError from Switch Frog Generator
        return None, f"Frog not added: {err}"
    obj.data.materials.append(_rail_material())
    obj.parent = strip
    obj[PART_TAG] = "FROG"
    return obj, ""


EXACT_LIMIT = 60000  # triangles; the Exact Boolean is too slow on bigger pieces


def _piece(name, ties, parts, holes, coll, solver):
    """One printed piece: ties joined to their parts, holes and sockets cut. (obj, open edges, solver)."""
    base = _new_object(name, *ties, coll)
    adds = [_new_object(f"_ss_{n}", *arrays, coll) for n, arrays in parts if len(arrays[0])]
    cutters = [_new_object("_ss_Holes", *holes, coll)] if len(holes[0]) else []
    for helper in adds + cutters:
        helper.hide_render = True
        helper.display_type = "WIRE"
    if meshgen.open_edges(ties[1]) != 0 and len(ties[1]) <= EXACT_LIMIT:
        solver = "EXACT"
    try:
        verts, tris = _boolean(base, adds, cutters, solver)
        if solver == "MANIFOLD" and len(tris) == 0 and len(ties[1]) <= EXACT_LIMIT:
            # Manifold gave nothing: try Exact. It is only tried on small pieces, since
            # on a whole turnout it can run for many minutes (Blender looks hung) and
            # it can drop whole ties. Manifold's few open edges, where two parts just
            # touch, are left as they are: slicers handle them.
            verts, tris = _boolean(base, adds, cutters, "EXACT")
            solver = "EXACT"
    finally:
        for helper in adds + cutters:
            mesh = helper.data
            bpy.data.objects.remove(helper)
            bpy.data.meshes.remove(mesh)
    if len(tris) < 0.5 * len(ties[1]):
        mesh = base.data
        bpy.data.objects.remove(base)
        bpy.data.meshes.remove(mesh)
        raise BuildError(f"Joining the parts of {name} failed (the {solver.title()} Boolean "
                         "solver lost the ties). Try a different seed, or change Max Triangles "
                         "per Tie, and generate again.")
    old = base.data
    base.data = wb_bridge.mesh_from_arrays(name, verts, tris)
    bpy.data.meshes.remove(old)
    edges = _clean(base.data)
    _shade(base.data)
    return base, edges, solver


def _shade(mesh: bpy.types.Mesh, angle: float = 60.0) -> None:
    """Smooth the weathered wood but keep flat faces flat (smooth by angle, 60 degrees).

    Fully smooth shading spreads the light across the big flat faces of the
    connectors and plates, which then show odd light and dark triangles.
    """
    try:
        mesh.set_sharp_from_angle(angle=math.radians(angle))
    except (AttributeError, TypeError):
        mesh.shade_flat()


def generate(context, progress=None) -> BuildResult:
    """Build the turnout from the scene's Stub Switch settings.

    ``progress(done, total)``, if given, is called as each board is ready.
    """
    started = time.perf_counter()
    scene = context.scene
    s = scene.stub_switch
    api = wb_bridge.find_api()
    info, err = s.frog()
    if info is None:
        raise BuildError(err)
    tmpl, err = s.template()
    if tmpl is None:
        raise BuildError(err)
    t = turnout.compute(s.turnout_spec(info))
    lay = layout.compute(t, s.layout_spec(info, tmpl))
    if not lay.ok:
        raise BuildError("\n".join(lay.errors))
    scale = s.scale_n()
    seed = s.seed if s.lock_seed else random.randrange(1, SEED_LIMIT)
    rng = random.Random(seed)
    boards, choice, turns, offsets, yaws = _boards(s, api, tmpl, lay, scale, rng, seed, progress)

    # ---- re-lay with the real grain depth ----
    top_cut = max(b.face_depth.get("top", 0.0) for b in boards)
    side_cut = max(max(b.face_depth.get("front", 0.0), b.face_depth.get("back", 0.0))
                   for b in boards)
    spec = s.layout_spec(info, tmpl, connector_overlap=side_cut + 0.2,
                         seat_depth=top_cut if s.seat_pad else 0.0, seat_inset=side_cut + 0.1)
    lay = layout.compute(t, spec)
    if not lay.ok:
        raise BuildError("\n".join(lay.errors))

    # ---- meshes, built left-handed, one set per printed piece ----
    split = lay.split_x
    for i, tie in enumerate(lay.ties):
        # The two ties at the joint stay square so the tabs fit, and so does the
        # double tie, which the headblock plates span.
        if lay.in_unit(tie.x) or (split is not None
                                  and abs(tie.x - split) < lay.summary["spacing"]):
            offsets[i] = yaws[i] = 0.0

    def side(x):
        """0 for the fixed piece, 1 for the movable piece."""
        return 1 if split is not None and x < split else 0

    pieces = []
    for k in ((0, 1) if split is not None else (0,)):
        idx = [i for i, tie in enumerate(lay.ties) if side(tie.x) == k]
        ties = meshgen.combine(*[
            (meshgen.place_board(boards[choice[i]].vertices,
                                 lay.tie_height - lay.ties[i].lowered, lay.ties[i].x,
                                 lay.ties[i].y_centre + offsets[i], turns[i], yaws[i]),
             boards[choice[i]].triangles) for i in idx])
        parts = [
            ("Connectors", meshgen.prisms([c for c in lay.connectors
                                           if side(c.outline[0][0]) == k]
                                          + (lay.tabs if k == 1 else []))),
            ("RailSeats", meshgen.boxes([b for b in lay.seats if side(b.x0) == k])),
            ("TiePlates", meshgen.boxes([b for b in lay.plates if side(b.x0) == k])),
            ("Footings", meshgen.boxes([b for b in lay.footings if side(b.x0) == k])),
            ("Shoulders", meshgen.prisms([b for b in lay.shoulders
                                          if side(b.outline[0][0]) == k])),
            ("Spikes", meshgen.spikes([sp for sp in lay.spikes if side(sp.cx) == k])),
            ("HeadblockPlates", meshgen.boxes([b for b in lay.hb_plates if side(b.x0) == k])),
            ("Clips", meshgen.spikes([c for c in lay.clips if side(c.cx) == k])),
            ("ThrowStops", meshgen.boxes([b for b in lay.stops if side(b.x0) == k])),
            ("Bolts", meshgen.prisms([b for b in lay.bolts if side(b.outline[0][0]) == k]))]
        holes = meshgen.combine(meshgen.cylinders([h for h in lay.holes if side(h.x) == k]),
                                meshgen.prisms(lay.sockets if k == 0 else []))
        pieces.append((ties, parts, holes))

    mirror = s.hand == "RIGHT"
    set_scene_millimetres(scene)
    coll = context.collection or scene.collection
    objs, open_edges, solver = [], 0, ""
    for k, (ties, parts, holes) in enumerate(pieces):
        if mirror:
            ties = meshgen.mirror_y(ties)
            parts = [(name, meshgen.mirror_y(m)) for name, m in parts]
            holes = meshgen.mirror_y(holes)
        name = RESULT_NAME if k == 0 else f"{RESULT_NAME} Movable"
        if progress:
            progress(len(boards) + 1, len(boards) + 2)
        try:
            obj, edges, solver = _piece(name, ties, parts, holes, coll, _solver())
        except BuildError:
            for done in objs:
                mesh = done.data
                bpy.data.objects.remove(done)
                bpy.data.meshes.remove(mesh)
            raise
        objs.append(obj)
        open_edges += edges
    base = objs[0]
    for piece in objs[1:]:
        piece.name = f"{base.name} Movable"
        piece.data.name = piece.name
        piece.parent = base
        piece[PART_TAG] = "TIES"

    # ---- report ----
    warnings = list(t.warnings) + list(lay.warnings)
    p = prefs.get(context)
    grain = layout.grain_warning(top_cut, lay.tie_height, tmpl.label, p.grain_limit if p else 20.0)
    if grain:
        warnings.append(grain)
    warnings += layout.printability(spec, lay, s.printer, p.thresholds(s.printer) if p else None)
    if open_edges:
        warnings.append(f"The tie strip has {open_edges} open edges and may not slice cleanly.")
    m = lay.summary
    info_out = {"triangles": sum(len(o.data.polygons) for o in objs), "pieces": len(objs), "open_edges": open_edges, "solver": solver,
                "seconds": time.perf_counter() - started, "top_cut": top_cut,
                "side_cut": side_cut, "boards": len(boards), "ties": len(lay.ties)}
    if s.seed != seed:
        from .properties import quiet
        with quiet():
            s.seed = seed
    base[TAG] = True
    base[SETTINGS_KEY] = json.dumps(s.switch_values(), default=str)
    base["frog_preset"] = info.name
    base["lead_mm"] = round(m["lead"], 3)
    base["lead_radius_mm"] = round(m["lead_radius"], 3)
    added = []
    if s.rail_on or (s.frog_on and s.guard_rails):
        rails, warn = add_rails(s, info, t, lay, base, coll, mirror, guards_only=not s.rail_on)
        if warn:
            warnings.append(warn)
        info_out["rails"] = len(rails)
        if rails:
            added.append("rail" if s.rail_on else "guard rails")
    if s.frog_on:
        frog, warn = add_frog(info, t, lay, base, coll, mirror)
        if warn:
            warnings.append(warn)
        if frog:
            added.append("frog")
            if info.base_plate and abs(info.plate_thickness - (lay.seat - lay.tie_height)) > 0.05:
                warnings.append("The frog has a base plate, which sits below the rail seat; "
                                "make its thickness match the tie plates (or turn it off in the "
                                "frog preset) so the frog sits flat.")
    if lay.gauge_bars:
        bars = add_gauge_bars(lay, base, coll, mirror)
        if bars:
            added.append(f"{len(bars)} gauge bar{'s' if len(bars) != 1 else ''}")
    s.last_report = (f"{base.name} (seed {seed}): {len(lay.ties)} ties, "
                     f"{info_out['triangles']:,} triangles, {info_out['seconds']:.1f} s."
                     + (f" Added {' and '.join(added)}." if added else ""))
    base.location = scene.cursor.location.copy()
    base.select_set(True)
    context.view_layer.objects.active = base
    return BuildResult(base, warnings, info_out)


def file_name(s) -> str:
    """The default STL file name from the settings' template."""
    info, _err = s.frog()
    frog = f"no{info.number:g}" if info else "frog"
    name = s.export_template.format(scale=scale_label(s.scale, s.scale_custom), frog=frog,
                                    hand="lh" if s.hand == "LEFT" else "rh")
    return name if name.lower().endswith(".stl") else name + ".stl"


def export_stl(context, objects, path: str) -> None:
    """Write exactly ``objects`` to one STL file in millimetres, restoring the selection after."""
    before = list(context.selected_objects)
    active = context.view_layer.objects.active
    for o in before:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, global_scale=1.0,
                              use_scene_unit=False, ascii_format=False, apply_modifiers=True)
    finally:
        for o in objects:
            o.select_set(False)
        for o in before:
            o.select_set(True)
        context.view_layer.objects.active = active
