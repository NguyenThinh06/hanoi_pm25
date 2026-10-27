"""Fetch and verify Geofabrik's dated Vietnam OSM shapefile archives, 2021-2025.

Run: python -m src.ingest.download_osm_snapshots
Existing verified files are skipped. Large ZIPs stay ignored by Git.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data/raw/static/osm"
BASE = "https://download.geofabrik.de/asia"
SIZES = {
    2021: 375_675_976,
    2022: 563_496_126,
    2023: 579_586_840,
    2024: 603_362_070,
    2025: 637_279_888,
}


def download(url: str, target: Path) -> None:
    part = target.with_name(target.name + f".part_{os.getpid()}")
    try:
        subprocess.run(["curl", "-fL", "--silent", "--show-error", "--retry", "3",
                        "--max-time", "900", "--output", str(part), url], check=True)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for year, size in SIZES.items():
        tag = f"{year % 100:02d}0101"
        name = f"vietnam-{tag}-free.shp.zip"
        archive = DEST / name
        sidecar = DEST / (name + ".md5")
        if not sidecar.exists():
            download(f"{BASE}/{name}.md5", sidecar)
        expected_md5 = sidecar.read_text(encoding="utf-8").split()[0].lower()
        if not archive.exists() or archive.stat().st_size != size:
            download(f"{BASE}/{name}", archive)
        if archive.stat().st_size != size or md5(archive) != expected_md5:
            raise ValueError(f"Geofabrik size/MD5 check failed: {archive}")
        print(f"[OSM] Verified {name} ({size:,} bytes)", flush=True)


if __name__ == "__main__":
    main()
