"""Build an installable add-on zip:  python build.py  ->  dist/stub_switch-<version>.zip

Install it in Blender 4.5+ with Get Extensions > Install from Disk.
"""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = "stub_switch"


def main():
    """Zip the add-on package into dist/ and print the path of the zip."""
    with open(os.path.join(ROOT, PKG, "blender_manifest.toml"), encoding="utf-8") as fh:
        version = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"{PKG}-{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, PKG)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")]
            for f in sorted(filenames):
                if f.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(dirpath, f)
                zf.write(full, os.path.relpath(full, ROOT))
    print(out)


if __name__ == "__main__":
    main()
