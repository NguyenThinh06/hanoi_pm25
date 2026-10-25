"""Source extraction checks run offline; CI never depends on HDX availability."""
import hashlib
import io
import json
import zipfile

import pytest
from shapely.geometry import box, mapping

from src.ingest.fetch_hanoi_boundary import extract_hanoi


def source_archive(features):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("vnm_admin1.geojson", json.dumps({"type": "FeatureCollection", "features": features}))
    raw = buffer.getvalue()
    return raw, {"source": {"archive_sha256": hashlib.sha256(raw).hexdigest(), "archive_member": "vnm_admin1.geojson"}}


def test_extract_preserves_geometry_and_properties():
    hanoi = {"type": "Feature", "properties": {"adm1_pcode": "VN01", "adm1_name": "Ha Noi"}, "geometry": mapping(box(105, 20, 106, 21))}
    other = {**hanoi, "properties": {"adm1_pcode": "VN91", "adm1_name": "An Giang"}}
    raw, provenance = source_archive([other, hanoi])
    extracted = json.loads(extract_hanoi(raw, provenance))
    assert extracted["features"] == json.loads(json.dumps([hanoi]))


def test_reject_modified_archive():
    raw, provenance = source_archive([])
    with pytest.raises(ValueError, match="checksum"):
        extract_hanoi(raw + b"modified", provenance)


def test_reject_missing_hanoi():
    raw, provenance = source_archive([])
    with pytest.raises(ValueError, match="exactly one"):
        extract_hanoi(raw, provenance)
