"""Build a Home Assistant installer and a separate brand asset archive."""

import argparse
import hashlib
import json
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "thermo_control"
BRAND_FILES = tuple(
    f"{prefix}{kind}{density}.png"
    for prefix in ("", "dark_")
    for kind in ("icon", "logo")
    for density in ("", "@2x")
)


def validate_brands():
    for name in BRAND_FILES:
        data = (COMPONENT / "brand" / name).read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"{name}: PNG required")
        width, height, depth, color = struct.unpack(">IIBB", data[16:26])
        size = 512 if "@2x" in name else 256
        if depth != 8 or color != 6 or height != size or ("icon" in name and width != size):
            raise ValueError(f"{name}: invalid RGBA dimensions: {width}x{height}")


def archive(destination, files):
    with ZipFile(destination, "w") as output:
        for path, name in sorted(files, key=lambda item: item[1]):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes(), compresslevel=9)
    with ZipFile(destination) as output:
        if output.testzip() is not None:
            raise ValueError(f"Corrupt archive: {destination}")
    print(f"{destination.name}: {destination.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Verify that the release tag matches manifest.version")
    args = parser.parse_args()
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    if args.tag is not None and args.tag != f"v{version}":
        raise ValueError(f"Tag {args.tag} does not match manifest version {version}")
    validate_brands()
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    installer = destination / f"thermo-control-{version}.zip"
    files = [
        (path, path.relative_to(ROOT).as_posix())
        for path in COMPONENT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in (".py", ".json", ".yaml", ".js", ".png")
    ]
    files += [(ROOT / name, name) for name in ("README.md", "SPECIFICATION.md")]
    archive(installer, files)
    brand = destination / f"thermo-control-brands-{version}.zip"
    archive(brand, [(COMPONENT / "brand" / name, f"thermo_control/{name}") for name in BRAND_FILES])
    checksum = destination / "SHA256SUMS"
    checksum.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (installer, brand)
        )
    )


if __name__ == "__main__":
    main()
