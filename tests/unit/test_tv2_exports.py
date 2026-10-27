"""Small integrity checks for the local GEE export downloader."""

import hashlib
import json

from src.ingest import download_satellite_exports
from src.ingest.download_satellite_exports import verified


def test_csv_verification_detects_same_size_corruption(tmp_path):
    path = tmp_path / "export.csv"
    contents = b"grid_id,date_id\ngrid_1,20210101\n"
    path.write_bytes(contents)
    item = {"size": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}

    assert verified(path, item)
    path.write_bytes(contents.replace(b"grid_1", b"grid_2"))
    assert path.stat().st_size == item["size"]
    assert not verified(path, item)


def test_copy_from_source_directory_uses_manifest_hash(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    name = "hanoi_aod_2021_q1_v2.csv"
    contents = b"grid_id,date_id\ngrid_1,20210101\n"
    (source / name).write_bytes(contents)
    manifest = tmp_path / "exports.json"
    manifest.write_text(json.dumps({"exports": [{
        "file": name, "size": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }]}))
    monkeypatch.setattr(download_satellite_exports, "MANIFEST", manifest)
    monkeypatch.setattr(download_satellite_exports, "DEST", tmp_path / "downloaded")

    download_satellite_exports.main(source_dir=source)

    assert (tmp_path / "downloaded" / name).read_bytes() == contents
