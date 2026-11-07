"""Build or verify data/model delivery archives using an explicit file allowlist."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "handover_bundles"


def digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def verify(path):
    with tarfile.open(path, "r:gz") as archive:
        manifest = json.load(archive.extractfile("HANDOVER_MANIFEST.json"))
        expected = {record["path"]: record for record in manifest["files"]}
        names = archive.getnames()
        if len(names) != len(set(names)) or set(names) != set(expected) | {"HANDOVER_MANIFEST.json"}:
            raise ValueError("Archive members do not match manifest")
        for name, record in expected.items():
            member = archive.getmember(name)
            if not member.isfile() or member.size != record["size_bytes"]:
                raise ValueError(f"Invalid file or size: {name}")
            if digest(archive.extractfile(member)) != record["sha256"]:
                raise ValueError(f"Checksum mismatch: {name}")
    print(f"Verified {len(expected)} files: {path.name}", flush=True)


def build(kind):
    if kind == "deployment":
        inputs = [
            "data/core", "data/reference",
            "data/marts/mart_grid_daily_features.parquet",
            "data/marts/mart_station_daily_training.parquet",
            "outputs/models", "outputs/evaluation", "outputs/registry",
        ]
    else:
        inputs = ["data/raw", "data/staging"]
    files = []
    for relative in inputs:
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError(source)
        files.extend(sorted(source.rglob("*")) if source.is_dir() else [source])
    files = sorted(p for p in files if p.is_file())
    if any(p.is_symlink() or ".env" in p.name or p.suffix == ".tmp" for p in files):
        raise ValueError("Unexpected symlink, environment file or temporary file")
    records = []
    for path in files:
        with path.open("rb") as stream:
            checksum = digest(stream)
        records.append({"path": path.relative_to(ROOT).as_posix(),
                        "size_bytes": path.stat().st_size, "sha256": checksum})
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_worktree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip()),
        "files": records,
        "excluded": ["sql", ".env", ".venv", "archive",
                     "data/marts/pred_grid_daily_pm25.parquet (unverified legacy predictions)"],
    }
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / f"pm25-{kind}-2026-11-04.tar.gz"
    if path.exists():
        raise FileExistsError(f"Preserve existing bundle before rebuilding: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    with tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
        for source in files:
            archive.add(source, arcname=source.relative_to(ROOT).as_posix(), recursive=False)
        info = tarfile.TarInfo("HANDOVER_MANIFEST.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    verify(temporary)
    temporary.replace(path)
    with path.open("rb") as stream:
        checksum = digest(stream)
    path.with_suffix(path.suffix + ".sha256").write_text(f"{checksum}  {path.name}\n", encoding="utf-8")
    path.with_suffix(path.suffix + ".manifest.json").write_bytes(payload)
    print(json.dumps({"file": str(path), "size_bytes": path.stat().st_size,
                      "files": len(files), "sha256": checksum}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["deployment", "source"], default="deployment")
    parser.add_argument("--verify", type=Path, help="Verify an existing bundle without extracting it")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify)
    else:
        build(args.kind)
