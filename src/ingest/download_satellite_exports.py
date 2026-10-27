"""Fetch and verify the GEE v2 CSV exports listed in the frozen manifest.

Run from the repo root: python -m src.ingest.download_satellite_exports
For CSVs copied outside Drive, pass --source-dir /path/to/csvs.
CSV files stay ignored by Git under data/raw/earth_observation/exports/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/manifests/satellite_exports_v2.json"
DEST = ROOT / "data/raw/earth_observation/exports"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified(path: Path, item: dict) -> bool:
    return (path.is_file() and path.stat().st_size == item["size"]
            and sha256(path) == item["sha256"])


def main(source_dir: Path | None = None) -> None:
    exports = json.loads(MANIFEST.read_text(encoding="utf-8"))["exports"]
    DEST.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(exports, 1):
        target = DEST / item["file"]
        if verified(target, item):
            print(f"[{i}/{len(exports)}] verified: {target.name}", flush=True)
            continue
        part = target.with_name(target.name + f".part_{os.getpid()}")
        try:
            local = source_dir / item["file"] if source_dir else None
            if local is not None:
                if not local.is_file():
                    raise FileNotFoundError(local)
                shutil.copyfile(local, part)
            else:
                url = f"https://drive.google.com/uc?export=download&id={item['drive_id']}"
                subprocess.run(["curl", "-fL", "--silent", "--show-error", "--retry", "3",
                                "--max-time", "300", "--output", str(part), url], check=True)
            if not verified(part, item):
                raise ValueError(f"Size or SHA-256 differs from manifest: {target.name}")
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)
        print(f"[{i}/{len(exports)}] ready: {target.name} ({item['size']:,} bytes)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path,
                        help="Read the named CSVs from this directory instead of Drive")
    main(source_dir=parser.parse_args().source_dir)
