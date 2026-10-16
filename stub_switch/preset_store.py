"""Saved presets on disk: one small JSON file per preset.

Two kinds, each in its own folder inside the extension's user folder,
which Blender keeps when the add-on is updated:

- ``plate_presets``: tie plate settings (lengths in inches).
- ``switch_presets``: every Stub Switch setting.

Files can be copied between computers to share presets.
"""

from __future__ import annotations

import json
import os

import bpy

PLATE, SWITCH = "plate_presets", "switch_presets"
FILE_VERSION = 1
_BAD_CHARS = '<>:"/\\|?*'

# Tests point this at a temporary folder; None = the extension's user folder.
folder_override: str | None = None


class PresetError(ValueError):
    """A preset file can't be read or written."""


def folder(kind: str) -> str:
    """The folder for one kind of preset, created if needed."""
    if folder_override is not None:
        path = os.path.join(folder_override, kind)
        os.makedirs(path, exist_ok=True)
        return path
    try:
        return bpy.utils.extension_path_user(__package__, path=kind, create=True)
    except (ValueError, AttributeError):
        return bpy.utils.user_resource(
            "SCRIPTS", path=os.path.join("presets", "stub_switch", kind), create=True)


def clean_name(name: str) -> str:
    """A preset name without characters that can't go in a file name."""
    return "".join(c for c in name if c not in _BAD_CHARS and c >= " ").strip().strip(".")


def _path(kind: str, name: str) -> str:
    """The JSON file for a preset name."""
    return os.path.join(folder(kind), clean_name(name) + ".json")


def saved_names(kind: str) -> list[str]:
    """Names of the saved presets of one kind, alphabetically."""
    try:
        files = os.listdir(folder(kind))
    except OSError:
        return []
    return sorted((f[:-5] for f in files if f.lower().endswith(".json")), key=str.casefold)


def _stored_name(kind: str, name: str) -> str | None:
    """The saved preset's own spelling of ``name`` (case-insensitive), or None."""
    for stored in saved_names(kind):
        if stored.casefold() == name.casefold():
            return stored
    return None


def save(kind: str, name: str, values: dict) -> str:
    """Write a preset; returns its path. Replaces one of the same name."""
    path = _path(kind, name)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": FILE_VERSION, "values": values}, fh, indent=2)
    except OSError as err:
        raise PresetError(f"Couldn't save preset '{name}': {err.strerror}.") from None
    return path


def load(kind: str, name: str) -> dict:
    """A saved preset's values (name matched ignoring case)."""
    stored = _stored_name(kind, name)
    if stored is None:
        raise PresetError(f"No saved preset named '{name}'.")
    try:
        with open(_path(kind, stored), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as err:
        raise PresetError(f"Can't read preset '{name}': {err}.") from None
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        raise PresetError(f"'{name}' is not a Stub Switch preset file.")
    return data["values"]


def remove(kind: str, name: str) -> None:
    """Delete a saved preset (name matched ignoring case)."""
    stored = _stored_name(kind, name)
    if stored is None:
        raise PresetError(f"No saved preset named '{name}'.")
    os.remove(_path(kind, stored))
