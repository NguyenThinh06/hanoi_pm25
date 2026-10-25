"""Reproduce the frozen Hanoi boundary from the checksummed HDX source archive."""
from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/reference"


def extract_hanoi(archive_bytes: bytes, provenance: dict) -> bytes:
    source = provenance["source"]
    if hashlib.sha256(archive_bytes).hexdigest() != source["archive_sha256"]:
        raise ValueError("HDX archive checksum changed; review a new release explicitly")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        collection = json.loads(archive.read(source["archive_member"]))
    selected = [feature for feature in collection["features"]
                if feature["properties"].get("adm1_pcode") == "VN01"]
    if len(selected) != 1 or selected[0]["properties"]["adm1_name"] != "Ha Noi":
        raise ValueError("Expected exactly one Hanoi feature (VN01 / Ha Noi)")
    geometry = shape(selected[0]["geometry"])
    if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Hanoi geometry is invalid; do not silently repair source data")
    result = {"type": "FeatureCollection", "features": selected}
    return (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    provenance = json.loads((REFERENCE / "hanoi_boundary.provenance.json").read_text(encoding="utf-8"))
    cached = ROOT / provenance["source"]["local_archive"]
    if cached.exists():
        raw = cached.read_bytes()
    else:
        request = urllib.request.Request(provenance["source"]["download_url"], headers={"User-Agent": "Hanoi-PM25-research/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    boundary = extract_hanoi(raw, provenance)
    if hashlib.sha256(boundary).hexdigest() != provenance["sha256"]:
        raise ValueError("Extracted boundary differs from the frozen reference")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(raw)
    (REFERENCE / "hanoi_boundary.geojson").write_bytes(boundary)
    print("[BOUNDARY] Reproduced verified HDX COD-AB v02 Hanoi (VN01)")


if __name__ == "__main__":
    main()
